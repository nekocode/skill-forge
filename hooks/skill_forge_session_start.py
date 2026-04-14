#!/usr/bin/env python3
"""
SessionStart hook (matcher: startup) for skill-forge.

Injects a brief skills inventory into context so skill-forge's
context assembler doesn't need to scan the filesystem cold.
Keeps it short — SessionStart runs on every session, must be fast.

Output: additionalContext string via JSON stdout.
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
from shared import DEFAULT_STATE, load_registry, load_state, save_state  # noqa: E402

MAX_SKILLS_SHOWN = 8  # only show the most recently updated


def main():
    hook_input = json.loads(sys.stdin.read())
    source = hook_input.get("source", "startup")

    # only run on new session — skip resume/compact
    if source not in ("startup", "clear"):
        print(json.dumps({}))
        return

    registry = load_registry()
    state = load_state()
    skills = registry.get("skills", [])

    # full state reset on new session — prevent stale counters from misleading Stop hook
    state.update(DEFAULT_STATE)
    save_state(state)

    if not skills:
        context = "skill-forge: no project skills yet. Run /skill-forge scan to discover opportunities."
    else:
        recent = sorted(skills, key=lambda s: s.get("updated", ""), reverse=True)
        lines = [f"skill-forge: {len(skills)} project skill(s) registered."]
        lines.append("Most recently updated:")
        for s in recent[:MAX_SKILLS_SHOWN]:
            auto = "auto" if s.get("auto_trigger") else "manual"
            lines.append(f"  /{s['name']}  v{s.get('version','?')}  [{auto}]  updated {s.get('updated','?')}")
        if len(skills) > MAX_SKILLS_SHOWN:
            lines.append(f"  ... and {len(skills) - MAX_SKILLS_SHOWN} more. Run /skill-forge list for full registry.")
        lines.append("Run /skill-forge improve <n> to iterate any of these.")
        context = "\n".join(lines)

    print(json.dumps({"additionalContext": context}))


if __name__ == "__main__":
    main()
