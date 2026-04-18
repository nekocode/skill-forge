"""Create mode draft initializer.

Generate the active draft file (under SKILLS_DIR/skill-forge/.workspace/) from name and goal,
serving as the attention anchor file for hooks.
"""

from __future__ import annotations

import sys
from pathlib import Path

# shared module from same directory
from shared import DRAFT_FILE

DRAFT_TEMPLATE = """\
# {name} — IN PROGRESS
## Goal
{goal}
## Phase
Phase 1: codebase research
## Status
pending
"""


def create_draft(
    name: str,
    goal: str,
    project_dir: Path | None = None,
) -> None:
    """Create the active draft file.

    Auto-creates the workspace directory. Overwrites existing draft.
    """
    if project_dir is None:
        project_dir = Path.cwd()

    draft_path = project_dir / DRAFT_FILE
    draft_path.parent.mkdir(parents=True, exist_ok=True)
    draft_path.write_text(DRAFT_TEMPLATE.format(name=name, goal=goal))


def main(
    name: str | None = None,
    goal: str | None = None,
    project_dir: Path | None = None,
) -> None:
    """Entry point. Get name/goal from params or sys.argv, create draft."""
    if name is None:
        if len(sys.argv) < 3:
            print("Usage: init_draft.py <name> <goal>")
            sys.exit(1)
        name = sys.argv[1]
        goal = " ".join(sys.argv[2:])

    if goal is None:
        goal = ""

    create_draft(name, goal, project_dir=project_dir)
    print(f"[skill-forge] Draft initialized: {name}")


if __name__ == "__main__":  # pragma: no cover — entry guard
    main()
