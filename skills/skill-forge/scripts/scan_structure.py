"""Project structure scanner.

Recursively walk project directory, excluding common build/dependency dirs,
output depth-limited file tree to stdout. Replaces inline find commands in SKILL.md.
"""

from __future__ import annotations

import os
from pathlib import Path

# default excluded dirs (matching original find command + common additions)
DEFAULT_EXCLUDES: frozenset[str] = frozenset({
    "node_modules",
    ".git",
    "dist",
    "build",
    ".next",
    "__pycache__",
    ".venv",
    "venv",
    ".tox",
    "coverage",
    ".nyc_output",
})

DEFAULT_MAX_DEPTH = 3
DEFAULT_MAX_LINES = 120


def scan_tree(
    root: Path,
    max_depth: int = DEFAULT_MAX_DEPTH,
    max_lines: int = DEFAULT_MAX_LINES,
    excludes: frozenset[str] | None = None,
) -> str:
    """Scan directory tree, return relative path listing.

    Excludes dir names in excludes, depth capped at max_depth,
    output capped at max_lines lines. Empty directory returns empty string.
    """
    if excludes is None:
        excludes = DEFAULT_EXCLUDES

    lines: list[str] = []
    full = False

    for dirpath, dirnames, filenames in os.walk(root):
        # compute relative depth
        rel = os.path.relpath(dirpath, root)
        depth = 0 if rel == "." else rel.count(os.sep) + 1

        # depth pruning: stop recursion but still collect current level entries
        if depth >= max_depth:
            dirnames.clear()

        # exclude dirs (in-place modify dirnames to skip subtrees)
        dirnames[:] = sorted(
            d for d in dirnames if d not in excludes
        )

        # collect entries: dirs + files, unified truncation
        for name in dirnames:
            lines.append((os.path.join(rel, name) if rel != "." else name) + "/")
            if len(lines) >= max_lines:
                full = True
                break
        if not full:
            for name in sorted(filenames):
                lines.append(os.path.join(rel, name) if rel != "." else name)
                if len(lines) >= max_lines:
                    full = True
                    break
        if full:
            break

    return "\n".join(lines)


def main(
    project_dir: Path | None = None,
    max_depth: int = DEFAULT_MAX_DEPTH,
    max_lines: int = DEFAULT_MAX_LINES,
) -> None:
    """Entry point. Scan and output to stdout."""
    if project_dir is None:
        project_dir = Path.cwd()

    result = scan_tree(project_dir, max_depth=max_depth, max_lines=max_lines)
    if result:
        print(result)
    else:
        print("(empty directory)")


if __name__ == "__main__":  # pragma: no cover — entry guard
    main()
