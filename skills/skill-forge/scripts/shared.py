"""Shared utilities for hooks directory.

Single source of truth for state file, registry, and frontmatter parsing.
Shared across hook scripts to prevent default value drift and parsing inconsistency.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

# ── path constants ───────────────────────────────────────

SKILLS_DIR = Path(".claude/skills")
USER_SKILLS_DIR = Path.home() / ".claude" / "skills"
REGISTRY_FILE = SKILLS_DIR / "skill_registry.json"

# Workspace lives OUTSIDE `.claude/` entirely. Claude Code's trust boundary
# only exempts `.claude/commands/**`, `.claude/agents/**`, and real skill
# dirs (those containing SKILL.md). In plugin mode the project has no
# `.claude/skills/skill-forge/SKILL.md`, so nesting workspace under
# `.claude/skills/skill-forge/.workspace/` was still prompting on Write.
# Putting it in $HOME sidesteps the boundary. Per-project isolation uses
# Claude Code's own slug convention (matches ~/.claude/projects/<slug>/)
# so the same project's workspace is stable across sessions.
WORKSPACE_DIR_NAME = ".skill-forge"
_DEFAULT_WORKSPACE_ROOT = Path.home() / WORKSPACE_DIR_NAME
_WORKSPACE_ROOT_ENV = "SKILL_FORGE_WORKSPACE_ROOT"


def _workspace_root() -> Path:
    """Resolve workspace root. Env override wins (tests)."""
    override = os.environ.get(_WORKSPACE_ROOT_ENV)
    if override:
        return Path(override)
    return _DEFAULT_WORKSPACE_ROOT


def cwd_slug(project_dir: Path) -> str:
    """Absolute project path → slug (Claude Code convention).

    /Users/x/proj → -Users-x-proj. Matches ~/.claude/projects/ naming so the
    same project's workspace is discoverable by humans grepping both trees.

    Uses os.path.abspath (not Path.resolve) so symlinks stay unresolved —
    matches the shell-hook slug which runs `tr '/' '-'` on $PWD /
    $CLAUDE_PROJECT_DIR without canonicalization. On macOS, /tmp vs
    /private/tmp would otherwise yield different slugs between the hook and
    the Python helpers, silently breaking draft injection.
    """
    absolute = os.path.abspath(str(project_dir))
    # Strip trailing slash so `/proj` and `/proj/` yield the same slug, mirroring
    # the shell hook which does `ROOT="${ROOT%/}"` before slugging.
    if absolute != "/" and absolute.endswith("/"):
        absolute = absolute.rstrip("/")
    return absolute.replace("/", "-")


def workspace_dir(project_dir: Path | None = None) -> Path:
    """Per-project workspace dir under the workspace root.

    None falls back to cwd — callers in tests should always pass explicitly to
    avoid the tmp-vs-home leak caught by pytest.
    """
    if project_dir is None:
        project_dir = Path.cwd()
    return _workspace_root() / cwd_slug(project_dir)


def draft_file(project_dir: Path | None = None) -> Path:
    return workspace_dir(project_dir) / "draft.md"


def insights_file(project_dir: Path | None = None) -> Path:
    return workspace_dir(project_dir) / "insights.md"


def state_file(project_dir: Path | None = None) -> Path:
    return workspace_dir(project_dir) / "state.json"

# ── threshold constants ──────────────────────────────────

TOOL_CALL_THRESHOLD = 5

# ── tool classification ──────────────────────────────────

# tools that write/modify files, used for SKILL.md change detection and draft write matching
FILE_WRITE_TOOLS = frozenset({"Write", "Edit", "MultiEdit"})

# ── state defaults (shared across all hooks) ─────────────

DEFAULT_STATE: dict = {
    "tool_calls": 0,
    "compacted": False,
}

# Bridge key between `record_eval_score.py` (writer) and `skill_forge_post_tool.py` (consumer).
# Renaming in one module without the other silently breaks score propagation (stays 0/8).
PENDING_EVAL_SCORE_KEY = "pending_eval_score"


# ── State I/O ───────────────────────────────────────────


def load_state(path: Path | None = None) -> dict:
    """Read state file. Corrupted/missing returns default copy.

    path None uses the cwd-derived per-project state file. Pass explicit path in tests.
    Catches FileNotFoundError + JSON decode errors. Other OSError (e.g. PermissionError)
    is logged to stderr before returning default — silent corruption is dangerous.
    """
    if path is None:
        path = state_file()
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        return dict(DEFAULT_STATE)
    except OSError as e:
        log_stderr(f"skill-forge: state file read error ({e}), using defaults")
        return dict(DEFAULT_STATE)


def save_state(state: dict, path: Path | None = None) -> None:
    """Write state file. Auto-creates parent directory."""
    if path is None:
        path = state_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2))


# ── Registry I/O ────────────────────────────────────────


def load_registry(path: Path = REGISTRY_FILE) -> dict:
    """Read skill registry. Corrupted/missing returns empty registry."""
    try:
        return json.loads(path.read_text())
    except Exception:
        return {"version": "1", "skills": []}


def save_registry(registry: dict, path: Path = REGISTRY_FILE) -> None:
    """Write skill registry. Auto-creates parent directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(registry, indent=2))


# ── Subprocess ─────────────────────────────────────────


def run_subprocess(cmd: list[str], timeout: int = 30, cwd: str | None = None) -> str:
    """Run subprocess, return stdout. Failure/timeout returns empty string.

    cwd: working directory. Pass `"/tmp"` for `claude -p` calls — the CLI otherwise
    walks up the tree and loads any CLAUDE.md it finds, contaminating prompts.
    """
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd,
        )
        if result.returncode != 0:
            return ""
        return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return ""


# ── logging ─────────────────────────────────────────────


def log_stderr(message: str) -> None:
    """Progress log output to stderr."""
    print(message, file=sys.stderr)


# ── rate limiter ─────────────────────────────────────────

# Tier-1 Anthropic cap is 50 RPM — default leaves 4 RPM headroom for retries.
# Raise via constructor on higher tiers. Each optimizer gets its own instance
# so tests stay isolated; self_evolve and optimize_description do not share state.
DEFAULT_RPM = 46


class RateLimiter:
    """Token-bucket style inter-launch throttle for concurrent API callers.

    Only serializes call-start timestamps — the underlying subprocess work
    proceeds concurrently once launched. `sleep` is monkey-patchable by tests.
    Thread-safe; one instance shared across a pool of worker threads.
    """

    def __init__(self, rpm: int = DEFAULT_RPM) -> None:
        self._min_interval = 60.0 / max(rpm, 1)
        self._lock = threading.Lock()
        # Negative infinity makes the first call's gap check pass without sleep
        # regardless of the current monotonic clock reading.
        self._last_launch = float("-inf")

    def throttle(self) -> None:
        """Block until the minimum inter-launch gap has elapsed.

        Lock scopes only the slot reservation — sleep happens unlocked so
        concurrent callers can compute their own future slot in parallel.
        Holding the lock across sleep would collapse pool throughput to a
        single thread.
        """
        with self._lock:
            now = time.monotonic()
            wait = self._min_interval - (now - self._last_launch)
            self._last_launch = now + max(wait, 0.0)
        if wait > 0:
            time.sleep(wait)


# ── frontmatter parsing ──────────────────────────────────


def parse_frontmatter(content: str) -> dict | None:
    """Parse YAML frontmatter into flat dict.

    Supports single-line `key: value` and YAML folded multiline `key: >\\n  line1\\n  line2`.
    No frontmatter returns None.
    """
    match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
    if not match:
        return None

    raw = match.group(1)
    result: dict = {}
    lines = raw.splitlines()
    index = 0

    while index < len(lines):
        line = lines[index]
        if ":" not in line:
            index += 1
            continue

        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()

        # YAML folded multiline: `key: >`
        if value == ">":
            continuation: list[str] = []
            index += 1
            while index < len(lines) and lines[index].startswith((" ", "\t")):
                continuation.append(lines[index].strip())
                index += 1
            result[key] = " ".join(continuation)
            continue

        result[key] = value.strip('"').strip("'")
        index += 1

    return result
