"""Improve mode session initializer.

Two jobs in one script:

  1. Seed staging from the live skill dir — `.claude/skills/<name>/*` →
     `.skill-forge/staging/<name>/*`. Claude's Edit calls during improve
     then land in staging, keeping `.claude/` untouched until
     `finalize_skill.py --mode update` copies the result back atomically.
  2. Copy the SKILL.md into the active draft workspace file as the
     attention anchor (the hooks re-read draft.md before every tool
     call, keeping Claude oriented mid-session).

Unified staging across create and improve means one finalize path for
both, and no branch where Claude edits a file the user didn't approve.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

# same directory — init_staging + shared both sit in scripts/
from init_staging import prepare as init_staging
from shared import SKILLS_DIR, draft_file


def init_improve_session(
    name: str,
    project_dir: Path | None = None,
) -> bool:
    """Initialize improve session.

    Seeds staging from the live skill dir and writes the draft. Returns
    False (no changes) when the target skill doesn't exist — the caller
    should surface that to the user since there's nothing to improve.
    """
    if project_dir is None:
        project_dir = Path.cwd()

    skill_dir = project_dir / SKILLS_DIR / name
    skill_file = skill_dir / "SKILL.md"
    if not skill_file.is_file():
        return False

    # Stage first so Edit/Write on the draft never races an unseeded
    # staging dir. init_staging wipes any stale staging for this name.
    init_staging(name, source=skill_dir, project_dir=project_dir)

    content = skill_file.read_text()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    content += f"\n## Improve session — {timestamp}\n"

    draft_path = draft_file(project_dir)
    draft_path.parent.mkdir(parents=True, exist_ok=True)
    draft_path.write_text(content)
    return True


def main(
    name: str | None = None,
    project_dir: Path | None = None,
) -> None:
    """Entry point. Get name from params or sys.argv, initialize improve session."""
    if name is None:
        if len(sys.argv) < 2:
            print("Usage: init_improve.py <name>")
            sys.exit(1)
        name = sys.argv[1]

    success = init_improve_session(name, project_dir=project_dir)
    if success:
        print(f"[skill-forge] Improve session initialized: {name}")
    else:
        print(f"[skill-forge] Skill not found: {name}")


if __name__ == "__main__":  # pragma: no cover — entry guard
    main()
