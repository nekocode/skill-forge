#!/usr/bin/env python3
"""
PreCompact hook: mark compact state to prevent false positives.

Sets compacted=True in state before context compact, so the Stop hook
knows this turn's tool count is unreliable due to compaction.

Output: empty JSON (no systemMessage).
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
from shared import STATE_FILE, load_state, save_state  # noqa: E402


def mark_compacted(state_path: Path = STATE_FILE) -> None:
    """Set compacted=True in the state file.

    Missing/corrupted file -> create new one. Preserves existing fields.
    """
    state = load_state(state_path)
    state["compacted"] = True
    save_state(state, state_path)


def main() -> None:
    """Entry point. Consume stdin (hook protocol), mark state, output empty JSON."""
    sys.stdin.read()  # consume stdin
    mark_compacted(STATE_FILE)
    print(json.dumps({}))


if __name__ == "__main__":
    main()
