"""Real-execution trigger eval.

Spawns `claude -p <query>` subprocesses and parses their stream-json output
to detect whether the Skill tool fires with a target skill name. Adapted
from Anthropic skill-creator's run_eval.py.

Why subprocess + stream parsing (instead of LLM-as-judge):
- A model asked "would this trigger?" confabulates — its answer depends on
  how the question is phrased, not on actual runtime behavior.
- Real runtime observes the actual trigger path: Claude Code's loader sees
  the description in the skills index, decides, and emits a tool_use. That
  is ground truth.
- stream-json + `--include-partial-messages` lets us early-exit the instant
  `content_block_start` announces our skill's tool_use — ~1s signal vs.
  ~10s waiting for the assistant message.

Note on subprocess cwd: this module deliberately runs `claude -p` with
`cwd=project_root` — not `/tmp` as the generation-path rule in
LEARNED.local.md prescribes. Rationale: that rule addresses CLAUDE.md
leaking house style into *generated text*; here the child's textual
output is irrelevant — we only observe whether/when the Skill tool fires.
Running inside project_root is required so Claude Code discovers
`.claude/commands/<slug>.md` and offers the skill as a candidate.
"""

from __future__ import annotations

import json
import os
import select
import subprocess
import time
import uuid
from pathlib import Path

# Defaults match Anthropic skill-creator's run_eval.py. Callers override via
# the `timeout` kwarg; DEFAULT_TIMEOUT exported for consistency.
DEFAULT_TIMEOUT = 30


def find_project_root(start: Path | None = None) -> Path:
    """Walk up from `start` (cwd default) looking for a `.claude/` directory.

    Claude Code uses the same walk to discover its project root. The temp
    command file we write below must land inside *that* `.claude/commands/`,
    or `claude -p` won't see it as a skill candidate. Returns `start` itself
    when no `.claude/` is found upward (caller's own cwd assumption wins).

    Uses os.path.abspath (not Path.resolve) to avoid symlink expansion.
    On macOS, `/tmp` → `/private/tmp` under resolve, which changes the
    recorded project root across processes and breaks anything that
    assumes a stable string path (command file cleanup races, log
    correlation). Shell hooks don't canonicalize either — keeping the
    Python side literal keeps the two aligned.
    """
    start_path = start or Path.cwd()
    current = Path(os.path.abspath(str(start_path)))
    for parent in [current, *current.parents]:
        if (parent / ".claude").is_dir():
            return parent
    return current


def run_single_query(
    query: str,
    skill_name: str,
    description: str,
    *,
    timeout: int = DEFAULT_TIMEOUT,
    project_root: Path | None = None,
    model: str | None = None,
) -> bool:
    """Run `claude -p <query>` and detect whether the skill fired.

    Writes a throwaway command file under `<project_root>/.claude/commands/`
    with a unique `<skill_name>-eval-<uuid>` slug so it appears as a Skill
    candidate without colliding with real commands. Parse stream-json; return
    True at first tool_use input containing our slug — then kill the child.

    Returns False on timeout, unrelated tool firing, or clean completion
    without our slug ever appearing. Temp command file is removed in finally.
    """
    root = project_root or find_project_root()
    unique_id = uuid.uuid4().hex[:8]
    clean_name = f"{skill_name}-eval-{unique_id}"
    commands_dir = root / ".claude" / "commands"
    command_file = commands_dir / f"{clean_name}.md"

    try:
        commands_dir.mkdir(parents=True, exist_ok=True)
        # Normalize line endings before indenting — stray CR in a block-literal
        # YAML value becomes part of the string on strict parsers, corrupting
        # the description the loader reads back.
        normalized = description.replace("\r\n", "\n").replace("\r", "\n")
        # YAML block scalar avoids quote-escaping trouble on arbitrary descriptions.
        indented = "\n  ".join(normalized.split("\n"))
        command_file.write_text(
            f"---\ndescription: |\n  {indented}\n---\n\n"
            f"# {skill_name}\n\nThis skill handles: {normalized}\n"
        )

        cmd = [
            "claude", "-p", query,
            "--output-format", "stream-json",
            "--verbose",
            "--include-partial-messages",
        ]
        if model:
            cmd.extend(["--model", model])

        # CLAUDECODE guards against interactive terminal nesting; programmatic
        # subprocess invocation is fine, so drop the flag to let the child run.
        env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            cwd=str(root),
            env=env,
        )
        return _parse_stream_for_trigger(process, clean_name, timeout)
    except (OSError, FileNotFoundError):
        return False
    finally:
        if command_file.exists():
            try:
                command_file.unlink()
            except OSError:
                pass  # best-effort cleanup; orphaned files are harmless


def _parse_stream_for_trigger(
    process: subprocess.Popen, clean_name: str, timeout: int,
) -> bool:
    """Read stream-json line-by-line, return True on first Skill/Read hit.

    Always terminates the process before returning — orphaned claude children
    would hold file locks on the temp command file.
    """
    triggered = False
    start = time.time()
    buffer = ""
    pending_tool_name: str | None = None
    accumulated_json = ""

    try:
        while time.time() - start < timeout:
            if process.poll() is not None:
                remaining = process.stdout.read() if process.stdout else b""
                if remaining:
                    buffer += remaining.decode("utf-8", errors="replace")
                break

            if not process.stdout:
                break
            ready, _, _ = select.select([process.stdout], [], [], 1.0)
            if not ready:
                continue

            chunk = os.read(process.stdout.fileno(), 8192)
            if not chunk:
                break
            buffer += chunk.decode("utf-8", errors="replace")

            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue

                verdict = _handle_event(event, clean_name, pending_tool_name, accumulated_json)
                # verdict is (state_update_or_None, final_bool_or_None)
                state_update, final = verdict
                if state_update is not None:
                    pending_tool_name, accumulated_json = state_update
                if final is not None:
                    return final

                if event.get("type") == "result":
                    return triggered
    finally:
        # Close stdout before wait(): claude can easily write > 64KB of stream
        # events before we kill it. On macOS kernel-pipe buffers that exceed
        # the PIPE_BUF limit make wait() block until the writer side is
        # drained, producing a deadlock. Closing our read end lets the kernel
        # reap the child's write syscalls with EPIPE.
        if process.stdout:
            try:
                process.stdout.close()
            except OSError:
                pass
        if process.poll() is None:
            process.kill()
            process.wait()

    return triggered


def _handle_event(
    event: dict, clean_name: str,
    pending_tool_name: str | None, accumulated_json: str,
) -> tuple[tuple[str | None, str] | None, bool | None]:
    """Classify one stream-json event. Return (state_update, final_verdict).

    state_update: new (pending_tool_name, accumulated_json) if the event
    advances parser state, else None.
    final_verdict: True/False if the event resolves the run, else None.
    """
    # Fast path: stream_event arrives before the full assistant message.
    if event.get("type") == "stream_event":
        se = event.get("event", {})
        se_type = se.get("type", "")
        if se_type == "content_block_start":
            cb = se.get("content_block", {})
            if cb.get("type") == "tool_use":
                tool_name = cb.get("name", "")
                if tool_name in ("Skill", "Read"):
                    return ((tool_name, ""), None)
                # Unrelated tool as the first tool_use -> skill did not
                # trigger on this query. Matches official skill-creator
                # semantics (skill must fire as the first action, else
                # Claude is handling the task without it).
                return (None, False)
        elif se_type == "content_block_delta" and pending_tool_name:
            delta = se.get("delta", {})
            if delta.get("type") == "input_json_delta":
                accumulated_json += delta.get("partial_json", "")
                if clean_name in accumulated_json:
                    return (None, True)
                return ((pending_tool_name, accumulated_json), None)
        elif se_type in ("content_block_stop", "message_stop"):
            if pending_tool_name:
                return (None, clean_name in accumulated_json)
            if se_type == "message_stop":
                return (None, False)
    # Slow path: full assistant message arrived (no partial-stream flag or
    # missed partial). Inspect tool_use content blocks directly.
    elif event.get("type") == "assistant":
        message = event.get("message", {})
        for content in message.get("content", []):
            if content.get("type") != "tool_use":
                continue
            tool_name = content.get("name", "")
            tool_input = content.get("input", {})
            if tool_name == "Skill" and clean_name in tool_input.get("skill", ""):
                return (None, True)
            if tool_name == "Read" and clean_name in tool_input.get("file_path", ""):
                return (None, True)
        return (None, False)
    return (None, None)
