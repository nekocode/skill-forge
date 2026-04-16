"""
Bootstrap helper for hook scripts.

Resolves the path to skills/skill-forge/scripts/ so hooks can import
shared.py. Needed because hooks can't import shared.py without first
knowing its path — and that logic was otherwise duplicated in every hook.
"""

import os
from pathlib import Path


def resolve_scripts_path() -> str:
    """Resolve scripts dir: plugin mode -> embed mode -> dev fallback."""
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if plugin_root:
        return str(Path(plugin_root) / "skills" / "skill-forge" / "scripts")
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR")
    if project_dir:
        candidate = Path(project_dir) / ".claude" / "skills" / "skill-forge" / "scripts"
        if candidate.is_dir():
            return str(candidate)
    # dev/test fallback: hooks/ is sibling to skills/
    return str(Path(__file__).resolve().parent.parent / "skills" / "skill-forge" / "scripts")
