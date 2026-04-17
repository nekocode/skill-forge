"""
Bootstrap helper for hook scripts.

Resolves the path to skills/skill-forge/scripts/ so hooks can import
shared.py. Needed because hooks can't import shared.py without first
knowing its path — and that logic was otherwise duplicated in every hook.
"""

import os
from pathlib import Path


def resolve_scripts_path() -> str:
    """Resolve scripts dir: plugin env -> embed env -> embed shape -> dev fallback.

    The embed-shape branch matters when CLAUDE_PROJECT_DIR is stripped from the
    hook env (shouldn't happen under Claude Code, but guards against it). In
    embed install, _bootstrap.py lives at `.claude/hooks/skill-forge/` which is
    three levels above the skills tree root (`.claude/`).
    """
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if plugin_root:
        return str(Path(plugin_root) / "skills" / "skill-forge" / "scripts")
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR")
    if project_dir:
        candidate = Path(project_dir) / ".claude" / "skills" / "skill-forge" / "scripts"
        if candidate.is_dir():
            return str(candidate)
    here = Path(__file__).resolve().parent
    embed_candidate = here.parent.parent / "skills" / "skill-forge" / "scripts"
    if embed_candidate.is_dir():
        return str(embed_candidate)
    # Dev/test fallback: repo/hooks/ sibling to repo/skills/
    return str(here.parent / "skills" / "skill-forge" / "scripts")
