#!/usr/bin/env python3
"""
PreCompact hook: mark compact state to prevent false positives.

Sets compacted=True in state before context compact, so the Stop hook
knows this turn's tool count is unreliable due to compaction.

Output: empty JSON (no systemMessage).
"""

import json
import sys
from pathlib import Path

# Bootstrap: resolve scripts path from shared _bootstrap.py (avoids duplication)
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bootstrap import resolve_scripts_path  # noqa: E402
sys.path.insert(0, resolve_scripts_path())
from shared import load_state, save_state, state_file  # noqa: E402


def mark_compacted(state_path: Path | None = None) -> None:
    """Set compacted=True in the state file.

    Missing/corrupted file -> create new one. Preserves existing fields.
    """
    if state_path is None:
        state_path = state_file()
    state = load_state(state_path)
    state["compacted"] = True
    save_state(state, state_path)


def main() -> None:
    """Entry point. Consume stdin (hook protocol), mark state, output empty JSON."""
    sys.stdin.read()  # consume stdin
    mark_compacted()
    print(json.dumps({}))


if __name__ == "__main__":
    main()
