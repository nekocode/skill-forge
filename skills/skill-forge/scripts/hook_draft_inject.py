"""Unified hook entrypoint for the three draft-injection hooks.

Replaces the previous three inline bash snippets in SKILL.md's frontmatter.
One Python script beats three shell snippets for a few reasons:

- Cross-platform. The bash versions used `${VAR:-default}`, `[ -f ]`, and
  `head -N` — all absent on Windows cmd.exe. Python works on every OS
  where skill-forge already requires python3.
- Single source of truth for workspace paths. Previously the shell hook
  and Python helpers each computed the project slug independently, which
  drifted on macOS (`/tmp` vs `/private/tmp`) and silently broke draft
  injection. Here we just import `shared.draft_file` / `insights_file`.
- Room to grow. Filtering (only inject when draft is non-empty, only on
  specific tool matches, etc.) stays readable in Python; bash conditionals
  get unreadable fast.

Modes:
  prompt   — UserPromptSubmit: print draft head + insights pointer
  pretool  — PreToolUse: print draft head (small, for attention anchoring)
  posttool — PostToolUse: nudge user to update draft after Write/Edit
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# scripts/ is already on sys.path when invoked as a hook command
from shared import draft_file, insights_file


def _project_dir() -> Path:
    """Hook execution dir. Claude Code sets CLAUDE_PROJECT_DIR; fall back to cwd."""
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    return Path(env) if env else Path.cwd()


def _read_nonempty(path: Path) -> str | None:
    """Return file contents only if non-empty; else None. Missing is None."""
    if not path.is_file():
        return None
    text = path.read_text()
    return text if text.strip() else None


def _head(text: str, lines: int) -> str:
    return "\n".join(text.splitlines()[:lines])


def inject_prompt(project_dir: Path, lines: int) -> str:
    """UserPromptSubmit body — full context reminder when a draft is active.

    Injected on every user prompt so Claude reorients after context shifts.
    Quiet when no draft exists (no noise between skill-forge sessions).
    """
    draft_path = draft_file(project_dir)
    text = _read_nonempty(draft_path)
    if text is None:
        return ""
    insights_path = insights_file(project_dir)
    return (
        "[skill-forge] ACTIVE SKILL DRAFT — current state:\n"
        f"{_head(text, lines)}\n\n"
        f"[skill-forge] Review {insights_path} for codebase context. "
        "Continue from current phase."
    )


def inject_pretool(project_dir: Path, lines: int) -> str:
    """PreToolUse body — short reminder before Read/Glob/Grep/Bash.

    Kept tiny (5 lines default) because this fires on every tool call and
    a 20-line dump floods the transcript. Header + Phase + Status is
    enough to anchor attention without blowing context.
    """
    draft_path = draft_file(project_dir)
    text = _read_nonempty(draft_path)
    if text is None:
        return ""
    return _head(text, lines)


def inject_posttool(project_dir: Path) -> str:
    """PostToolUse body — nudge to sync findings into draft after Write/Edit.

    Stat-only check (no read) — this fires on every Write/Edit, and the
    draft body is discarded; reading it just to test non-empty would
    scale with draft length per tool call.
    """
    draft_path = draft_file(project_dir)
    try:
        if draft_path.stat().st_size == 0:
            return ""
    except OSError:
        return ""
    return (
        f"[skill-forge] Update {draft_path} with what you just found. "
        "If a codebase pattern is confirmed, move it from insights.md into the draft steps."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="skill-forge draft hook injector")
    parser.add_argument(
        "--mode",
        choices=["prompt", "pretool", "posttool"],
        required=True,
    )
    parser.add_argument(
        "--lines",
        type=int,
        default=None,
        help="Draft head line count. Defaults: prompt=40, pretool=5.",
    )
    args = parser.parse_args(argv)

    project_dir = _project_dir()

    if args.mode == "prompt":
        output = inject_prompt(project_dir, args.lines if args.lines is not None else 40)
    elif args.mode == "pretool":
        output = inject_pretool(project_dir, args.lines if args.lines is not None else 5)
    else:
        output = inject_posttool(project_dir)

    if output:
        print(output)
    return 0


if __name__ == "__main__":  # pragma: no cover — entry guard
    sys.exit(main())
