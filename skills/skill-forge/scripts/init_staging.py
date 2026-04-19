"""Staging directory initializer.

Creates `<project>/.skill-forge/staging/<name>/` so Claude can assemble a
skill there instead of writing directly into `.claude/skills/<name>/`.
Direct writes into a fresh `.claude/skills/<name>/` trigger permission
prompts even under bypassPermissions — the dir doesn't yet contain a
SKILL.md, so Claude Code's trust-boundary exemption doesn't cover it.

Two usage shapes:

  init_staging.py <name>
      Create mode: empty staging dir ready to be written into.

  init_staging.py <name> --source .claude/skills/<name>
      Improve mode: copy the existing skill dir into staging as the
      starting point for edits. Claude then Edit()s files in staging,
      and finalize_skill.py --mode update copies the result back.

Both shapes are safe to re-run — they blow away any existing contents at
the staging path first so a half-finished previous attempt can't leak in.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

from shared import staging_dir


# Stricter than quick_validate's NAME_PATTERN (which accepts "123"): staging
# additionally requires a leading letter so directory names match what
# developers actually type. A digit-only name passes the Claude Code schema
# but is almost certainly a typo.
_NAME_RE = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")


def validate_name(name: str) -> None:
    """Raise ValueError if name isn't kebab-case. Matches frontmatter schema."""
    if not _NAME_RE.match(name):
        raise ValueError(
            f"skill name {name!r} must be lowercase kebab-case "
            "(e.g. 'generate-endpoint')"
        )


def prepare(
    name: str,
    source: Path | None = None,
    project_dir: Path | None = None,
) -> Path:
    """Create empty staging dir, or seed from `source` when provided.

    Idempotent: any existing content at the staging path is removed first.
    This matters for improve mode — a re-invocation after an aborted run
    must not merge old and new files under the same name.
    """
    validate_name(name)
    target = staging_dir(project_dir) / name
    if target.exists():
        shutil.rmtree(target)

    if source is not None:
        if not source.is_dir():
            raise FileNotFoundError(f"source skill dir not found: {source}")
        shutil.copytree(source, target)
    else:
        target.mkdir(parents=True, exist_ok=True)
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Initialize a skill staging dir.")
    parser.add_argument("name")
    parser.add_argument(
        "--source",
        type=Path,
        default=None,
        help="Existing skill dir to seed staging from (improve mode).",
    )
    parser.add_argument(
        "--project-dir",
        type=Path,
        default=None,
        help="Override project root (for tests).",
    )
    args = parser.parse_args(argv)

    try:
        target = prepare(args.name, source=args.source, project_dir=args.project_dir)
    except (ValueError, FileNotFoundError) as e:
        print(f"[skill-forge] init_staging failed: {e}", file=sys.stderr)
        return 1

    print(f"[skill-forge] Staging ready at {target}")
    return 0


if __name__ == "__main__":  # pragma: no cover — entry guard
    sys.exit(main())
