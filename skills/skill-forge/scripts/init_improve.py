"""Improve mode session initializer.

Copy existing skill's SKILL.md to .claude/skill_draft.md,
append improve session timestamp header, activate hooks attention loop.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

# shared module from same directory
from shared import DRAFT_FILE, SKILLS_DIR


def init_improve_session(
    name: str,
    project_dir: Path | None = None,
) -> bool:
    """Initialize improve session.

    Copy .claude/skills/<name>/SKILL.md to .claude/skill_draft.md,
    append improve session timestamp.

    Skill not found returns False, no draft created.
    """
    if project_dir is None:
        project_dir = Path.cwd()

    skill_file = project_dir / SKILLS_DIR / name / "SKILL.md"
    if not skill_file.is_file():
        return False

    content = skill_file.read_text()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    content += f"\n## Improve session — {timestamp}\n"

    draft_path = project_dir / DRAFT_FILE
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
