#!/usr/bin/env python3
"""
Stop hook for skill-forge auto mode.

Fires when Claude finishes a response. Reads the tool-call counter written
by the PostToolUse hook, checks thresholds, and injects a systemMessage
that prompts Claude to offer skill-forge options to the user.

Threshold triggers (mirrors Hermes):
  - 5+ tool calls in this turn
  - error recovery flag set (PostToolUseFailure hook writes this)
  - user correction flag set (UserPromptSubmit hook writes this)

Output contract: print JSON to stdout with optional systemMessage and
continue=true. Never blocks (no exit 2).
"""

import json
import os
import sys
from pathlib import Path

# shared module lives under skills/skill-forge/scripts/
_plugin_root = Path(os.environ.get(
    "CLAUDE_PLUGIN_ROOT", str(Path(__file__).resolve().parent.parent)
))
sys.path.insert(0, str(_plugin_root / "skills" / "skill-forge" / "scripts"))
from shared import TOOL_CALL_THRESHOLD, load_state, save_state  # noqa: E402


def should_trigger(state: dict) -> tuple[bool, str]:
    """Return (trigger, reason) based on state thresholds.

    tool count unreliable after compact — skip trigger.
    """
    # tool count unreliable after compact — skip but reset flag for subsequent turns
    if state.get("compacted"):
        return False, "compacted"
    n = state.get("tool_calls", 0)
    if state.get("error_recovery"):
        return True, f"error recovery during this task ({n} tool calls)"
    if state.get("user_correction"):
        return True, f"user correction mid-task ({n} tool calls)"
    if n >= TOOL_CALL_THRESHOLD:
        return True, f"{n} tool calls — complex workflow"
    return False, ""


def build_message(reason: str, summary: str) -> str:
    lines = [
        f"[skill-forge] Potential reusable pattern detected ({reason}).",
    ]
    if summary:
        lines.append(f"Task summary: {summary}")
    lines += [
        "",
        "Ask the user:",
        "  'That looked like a reusable workflow. Should I create a skill for it?'",
        "  Options to present: [y] Create skill  [n] Skip  [rename: ___] Use a different name",
        "",
        "If user says yes or provides a name → run /skill-forge create <name>.",
        "If user says no → reset the counter silently, do not mention skill-forge again.",
    ]
    return "\n".join(lines)


def main():
    json.loads(sys.stdin.read())  # consume stdin (hook protocol requirement)
    state = load_state()

    trigger, reason = should_trigger(state)

    if trigger:
        summary = state.get("pending_summary", "")
        msg = build_message(reason, summary)

        state.update({"tool_calls": 0, "error_recovery": False,
                       "user_correction": False, "pending_summary": "",
                       "compacted": False})
        save_state(state)

        print(json.dumps({"systemMessage": msg, "continue": True}))
    else:
        # full reset after compact — prevent stale error_recovery/user_correction from false-triggering next turn
        if reason == "compacted":
            state.update({"tool_calls": 0, "error_recovery": False,
                           "user_correction": False, "pending_summary": "",
                           "compacted": False})
            save_state(state)
        print(json.dumps({}))


if __name__ == "__main__":
    main()
