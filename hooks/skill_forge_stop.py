#!/usr/bin/env python3
"""
Stop hook for skill-forge auto mode.

Fires when Claude finishes a response. Reads the tool-call counter written
by the PostToolUse hook, checks thresholds, and injects a systemMessage
that prompts Claude to offer skill-forge options to the user.

Threshold trigger: 5+ tool calls in this turn.

Output contract: print JSON to stdout with optional systemMessage and
continue=true. Never blocks (no exit 2).
"""

import json
import sys
from pathlib import Path

# Bootstrap: resolve scripts path from shared _bootstrap.py (avoids duplication)
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bootstrap import resolve_scripts_path  # noqa: E402
sys.path.insert(0, resolve_scripts_path())
from shared import (  # noqa: E402
    DEFAULT_STATE,
    TOOL_CALL_THRESHOLD,
    draft_file,
    load_state,
    save_state,
)


def _has_active_draft(project_dir: Path | None = None) -> bool:
    """True iff a non-empty draft.md exists in the workspace.

    Non-empty is the right signal: `finalize_skill.py` clears the draft
    by writing an empty string (rather than unlinking it) so downstream
    file-existence checks stay stable. Treating the empty file as
    "inactive" keeps us from re-triggering right after a finalize.
    """
    draft = draft_file(project_dir)
    if not draft.is_file():
        return False
    try:
        return bool(draft.read_text().strip())
    except OSError:
        return False


def should_trigger(state: dict, project_dir: Path | None = None) -> tuple[bool, str]:
    """Return (trigger, reason) based on state thresholds.

    Skip when compacted (tool count unreliable post-compact) or when an
    improve/create session is already in flight — otherwise skill-forge's
    own runs (scan, improve) rack up 5+ tool calls and the Stop hook
    suggests the user "capture this workflow as a skill", which is
    recursion into itself. Draft presence is the reliable signal: all
    skill-forge modes set it in Step 1, finalize clears it.
    """
    if state.get("compacted"):
        return False, "compacted"
    if _has_active_draft(project_dir):
        return False, "active draft"
    n = state.get("tool_calls", 0)
    if n >= TOOL_CALL_THRESHOLD:
        return True, f"{n} tool calls — complex workflow"
    return False, ""


def build_message(reason: str) -> str:
    lines = [
        f"[skill-forge] Reusable pattern detected ({reason}).",
        "Ask via AskUserQuestion (load with ToolSearch if missing): "
        "'Create a skill for this workflow?' — options Create / Skip.",
        "Create → /skill-forge create <workflow prompt>. Skip → reset silently, drop it.",
    ]
    return "\n".join(lines)


def main():
    json.loads(sys.stdin.read())  # consume stdin (hook protocol requirement)
    state = load_state()

    trigger, reason = should_trigger(state)

    if trigger:
        msg = build_message(reason)
        _reset_state(state)
        print(json.dumps({"systemMessage": msg, "continue": True}))
    else:
        if reason == "compacted":
            _reset_state(state)
        print(json.dumps({}))


def _reset_state(state: dict) -> None:
    """Reset counters and flags after trigger or compact."""
    state.update(DEFAULT_STATE)
    save_state(state)


if __name__ == "__main__":
    main()
