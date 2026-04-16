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
from shared import DEFAULT_STATE, TOOL_CALL_THRESHOLD, load_state, save_state  # noqa: E402


def should_trigger(state: dict) -> tuple[bool, str]:
    """Return (trigger, reason) based on state thresholds.

    tool count unreliable after compact — skip trigger.
    """
    if state.get("compacted"):
        return False, "compacted"
    n = state.get("tool_calls", 0)
    if n >= TOOL_CALL_THRESHOLD:
        return True, f"{n} tool calls — complex workflow"
    return False, ""


def build_message(reason: str) -> str:
    lines = [
        f"[skill-forge] Potential reusable pattern detected ({reason}).",
        "",
        "Ask the user:",
        "  'That looked like a reusable workflow. Should I create a skill for it?'",
        "  Options to present: [y] Create skill  [n] Skip",
        "",
        "If user says yes → run /skill-forge create <prompt describing the workflow>.",
        "If user says no → reset the counter silently, do not mention skill-forge again.",
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
