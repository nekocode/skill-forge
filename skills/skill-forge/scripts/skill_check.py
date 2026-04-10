"""Stop hook check script (Python version).

Equivalent fallback for shell version skill_check.sh.
Check current create/evolve session state, output plain text hints to stdout.
"""

from __future__ import annotations

import re
from pathlib import Path

# shared module from same directory
from shared import DRAFT_FILE, STATE_FILE, TOOL_CALL_THRESHOLD, load_state


# ── core functions ────────────────────────────────────


def check_draft_status(draft_path: Path) -> str | None:
    """Check draft file status.

    File not found returns None.
    Content contains complete/done (case-insensitive) -> prompt to run evaluator.
    Otherwise -> prompt draft in progress + current Phase (if any).
    """
    if not draft_path.is_file():
        return None

    content = draft_path.read_text()

    # exact match content on the line after ## Status
    status_match = re.search(r"^## Status\s*\n(.+)", content, re.MULTILINE)
    if status_match:
        status_value = status_match.group(1).lower()
        if "complete" in status_value or "done" in status_value:
            return (
                "[skill-forge] Draft complete but not yet written to disk.\n"
                "Run the evaluator and write to .claude/skills/<name>/SKILL.md"
            )

    # in progress: extract Phase line (two-line format preferred, single-line fallback)
    lines: list[str] = [
        "[skill-forge] Draft still in progress.",
    ]
    # two-line format (DRAFT_TEMPLATE default): "## Phase\n<content>"
    phase_match = re.search(r"^## Phase[ \t]*$\n(.+)", content, re.MULTILINE)
    if not phase_match:
        # single-line format: "## Phase 1: xxx"
        phase_match = re.search(r"^## (Phase .+)", content, re.MULTILINE)
    if phase_match:
        lines.append(f"Current: {phase_match.group(1).strip()}")
    lines.append(
        "Continue from current phase or delete .claude/skill_draft.md to abort."
    )
    return "\n".join(lines)


def check_tool_calls(state_path: Path) -> str | None:
    """Check tool call count.

    File missing / corrupted JSON / below threshold returns None.
    At threshold -> prompt to consider creating a skill.
    """
    data = load_state(state_path)
    tool_calls = data.get("tool_calls", 0)
    if not isinstance(tool_calls, (int, float)):
        return None
    tool_calls = int(tool_calls)

    if tool_calls < TOOL_CALL_THRESHOLD:
        return None

    return (
        f"[skill-forge] Complex workflow detected ({tool_calls} tool calls).\n"
        "Consider: /skill-forge create <name> to capture this pattern."
    )


def main(
    draft_path: Path = DRAFT_FILE,
    state_path: Path = STATE_FILE,
) -> None:
    """Entry point. Check draft first, then tool calls. Output first non-None result."""
    result = check_draft_status(draft_path)
    if result is not None:
        print(result)
        return

    result = check_tool_calls(state_path)
    if result is not None:
        print(result)


if __name__ == "__main__":  # pragma: no cover — entry guard
    main()
