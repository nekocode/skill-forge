"""Phase 0 context loader.

Merge four separate Phase 0 commands from SKILL.md into a single call:
1. read active draft head
2. run session catchup
3. list registered skills
4. read registry summary

Output structured report with section headers to stdout.
"""

from __future__ import annotations

from pathlib import Path

# shared module from same directory
from shared import DRAFT_FILE, REGISTRY_FILE, SKILLS_DIR, load_registry
from skill_catchup import main as catchup_main

# default max lines
DEFAULT_DRAFT_LINES = 20


def load_draft_head(project_dir: Path, max_lines: int = DEFAULT_DRAFT_LINES) -> str:
    """Read first N lines of the active draft workspace file.

    File not found returns empty string.
    """
    draft = project_dir / DRAFT_FILE
    if not draft.is_file():
        return ""
    lines = draft.read_text().splitlines()[:max_lines]
    return "\n".join(lines)


def run_catchup(project_dir: Path) -> str:
    """Run session catchup scan directly (same process, no subprocess overhead).

    Returns report string (empty if nothing found).
    """
    return catchup_main(cwd=str(project_dir))


def load_skills_list(project_dir: Path) -> str:
    """List subdirectory names under .claude/skills/.

    SKILL.md presence is the skill anchor — filters out per-skill
    `-workspace/` helpers and stray dirs without a manifest (e.g. a
    `skill-forge/` left behind in plugin-mode where only `.workspace/`
    lives inside). Directory not found returns empty string.
    """
    skills_dir = project_dir / SKILLS_DIR
    if not skills_dir.is_dir():
        return ""
    names = sorted(p.parent.name for p in skills_dir.glob("*/SKILL.md"))
    if not names:
        return ""
    return "\n".join(names)


def load_registry_summary(project_dir: Path) -> str:
    """Read skill_registry.json and format summary.

    File missing/corrupted returns empty string. Empty skills list returns hint text.
    """
    data = load_registry(project_dir / REGISTRY_FILE)
    skills = data.get("skills", [])
    if not skills:
        return "No skills registered."

    lines = []
    for skill in skills:
        name = skill.get("name", "?")
        version = skill.get("version", "?")
        updated = skill.get("updated", "?")
        lines.append(f"  {name}  v{version}  updated {updated}")
    return "\n".join(lines)


def main(
    project_dir: Path | None = None,
) -> None:
    """Entry point. Output structured report to stdout.

    project_dir: project root (defaults to cwd).
    """
    if project_dir is None:
        project_dir = Path.cwd()

    sections: list[str] = []

    # 1. active draft
    draft = load_draft_head(project_dir)
    if draft:
        sections.append(f"=== Draft ===\n{draft}")

    # 2. Session catchup
    catchup = run_catchup(project_dir)
    if catchup:
        sections.append(f"=== Catchup ===\n{catchup}")

    # 3. skills directory
    skills = load_skills_list(project_dir)
    if skills:
        sections.append(f"=== Skills ===\n{skills}")

    # 4. registry summary
    registry = load_registry_summary(project_dir)
    if registry:
        sections.append(f"=== Registry ===\n{registry}")

    if sections:
        print("\n\n".join(sections))
    else:
        print("skill-forge: no active draft, no skills registered.")


if __name__ == "__main__":  # pragma: no cover — entry guard
    main()
