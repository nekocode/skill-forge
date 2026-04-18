"""Phase 0 context loader.

Merge Phase 0 commands from SKILL.md into a single call:
1. report installed version + stale-cache warning
2. read active draft head
3. run session catchup
4. list registered skills
5. read registry summary

Output structured report with section headers to stdout.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

# shared module from same directory
from shared import REGISTRY_FILE, SKILLS_DIR, draft_file, load_registry
from skill_catchup import main as catchup_main

# default max lines
DEFAULT_DRAFT_LINES = 20

EMBED_VERSION_FILE = Path(".claude/hooks/skill-forge/version.json")
PLUGIN_MANIFEST_REL = Path(".claude-plugin/plugin.json")
PLUGIN_CACHE_DIR = Path.home() / ".claude" / "plugins" / "cache" / "skill-forge" / "skill-forge"


def load_draft_head(project_dir: Path, max_lines: int = DEFAULT_DRAFT_LINES) -> str:
    """Read first N lines of the active draft workspace file.

    File not found returns empty string.
    """
    draft = draft_file(project_dir)
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
    `-workspace/` helpers and stray dirs without a manifest.
    Directory not found returns empty string.
    """
    skills_dir = project_dir / SKILLS_DIR
    if not skills_dir.is_dir():
        return ""
    names = sorted(p.parent.name for p in skills_dir.glob("*/SKILL.md"))
    if not names:
        return ""
    return "\n".join(names)


def _read_json(path: Path) -> dict:
    """Read and parse JSON file. Missing or malformed returns empty dict."""
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError, ValueError, OSError):
        return {}


def detect_install(
    project_dir: Path,
    plugin_root: str | None = None,
    cache_dir: Path | None = None,
) -> str:
    """Identify install mode + version + stale cache warning.

    Order: plugin env (CLAUDE_PLUGIN_ROOT set) -> embed version.json -> dev
    repo manifest. Stale-cache warning covers the case where Claude's skill
    lookup can fall back to an older cached plugin version instead of the
    one registered in SKILL.md.
    """
    if plugin_root is None:
        plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if cache_dir is None:
        cache_dir = PLUGIN_CACHE_DIR

    cached_versions = (
        sorted(p.name for p in cache_dir.iterdir() if p.is_dir())
        if cache_dir.is_dir()
        else []
    )
    lines: list[str] = []

    if plugin_root:
        manifest = _read_json(Path(plugin_root) / PLUGIN_MANIFEST_REL)
        version = manifest.get("version", "unknown")
        lines.append(f"skill-forge {version} [plugin]")
        if len(cached_versions) > 1:
            lines.append(
                f"WARNING: multiple plugin cache versions present ({', '.join(cached_versions)}). "
                f"Run `/plugin update skill-forge` or `rm -rf {cache_dir}` then reinstall."
            )
        return "\n".join(lines)

    version_data = _read_json(project_dir / EMBED_VERSION_FILE)
    if version_data:
        version = version_data.get("version", "unknown")
        installed = version_data.get("installed", "?")
        lines.append(f"skill-forge {version} [embed, installed {installed}]")
        if cached_versions:
            lines.append(
                f"WARNING: marketplace plugin cache still present at {cache_dir} "
                f"(versions: {', '.join(cached_versions)}). Embed install is authoritative; "
                f"delete the cache to stop Claude's skill lookup from falling back to it."
            )
        return "\n".join(lines)

    for ancestor in [project_dir, *project_dir.parents]:
        manifest_path = ancestor / PLUGIN_MANIFEST_REL
        if manifest_path.is_file():
            manifest = _read_json(manifest_path)
            version = manifest.get("version", "unknown")
            lines.append(f"skill-forge {version} [dev @ {ancestor}]")
            break

    return "\n".join(lines)


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

    # 1. install version — first so warnings show at the top
    version = detect_install(project_dir)
    if version:
        sections.append(f"=== Version ===\n{version}")

    # 2. active draft
    draft = load_draft_head(project_dir)
    if draft:
        sections.append(f"=== Draft ===\n{draft}")

    # 3. Session catchup
    catchup = run_catchup(project_dir)
    if catchup:
        sections.append(f"=== Catchup ===\n{catchup}")

    # 4. skills directory
    skills = load_skills_list(project_dir)
    if skills:
        sections.append(f"=== Skills ===\n{skills}")

    # 5. registry summary
    registry = load_registry_summary(project_dir)
    if registry:
        sections.append(f"=== Registry ===\n{registry}")

    if sections:
        print("\n\n".join(sections))
    else:
        print("skill-forge: no active draft, no skills registered.")


if __name__ == "__main__":  # pragma: no cover — entry guard
    main()
