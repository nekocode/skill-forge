"""Shared utilities for hooks directory.

Single source of truth for state file, registry, and frontmatter parsing.
Shared across hook scripts to prevent default value drift and parsing inconsistency.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

# ── path constants ───────────────────────────────────────

STATE_FILE = Path(".claude/skill_forge_state.json")
SKILLS_DIR = Path(".claude/skills")
REGISTRY_FILE = SKILLS_DIR / "skill_registry.json"

# Workspace nests INSIDE the skill-forge skill dir so Claude Code's .claude/
# trust-boundary exemption applies — sibling dot-dirs like `.claude/skills/.workspace/`
# are still prompted because the exemption only recurses into real skill dirs
# (same rule that makes `<skill>/.opt/` prompt-free). Write/Edit under this
# path are silent even in bypassPermissions.
WORKSPACE_DIR = SKILLS_DIR / "skill-forge" / ".workspace"
DRAFT_FILE = WORKSPACE_DIR / "draft.md"

# ── threshold constants ──────────────────────────────────

TOOL_CALL_THRESHOLD = 5

# ── tool classification ──────────────────────────────────

# tools that write/modify files, used for SKILL.md change detection and draft write matching
FILE_WRITE_TOOLS = frozenset({"Write", "Edit", "MultiEdit"})

# ── state defaults (shared across all hooks) ─────────────

DEFAULT_STATE: dict = {
    "tool_calls": 0,
    "compacted": False,
}


# ── State I/O ───────────────────────────────────────────


def load_state(path: Path = STATE_FILE) -> dict:
    """Read state file. Corrupted/missing returns default copy.

    Catches FileNotFoundError + JSON decode errors. Other OSError (e.g. PermissionError)
    is logged to stderr before returning default — silent corruption is dangerous.
    """
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        return dict(DEFAULT_STATE)
    except OSError as e:
        log_stderr(f"skill-forge: state file read error ({e}), using defaults")
        return dict(DEFAULT_STATE)


def save_state(state: dict, path: Path = STATE_FILE) -> None:
    """Write state file. Auto-creates parent directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2))


# ── Registry I/O ────────────────────────────────────────


def load_registry(path: Path = REGISTRY_FILE) -> dict:
    """Read skill registry. Corrupted/missing returns empty registry."""
    try:
        return json.loads(path.read_text())
    except Exception:
        return {"version": "1", "skills": []}


def save_registry(registry: dict, path: Path = REGISTRY_FILE) -> None:
    """Write skill registry. Auto-creates parent directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(registry, indent=2))


# ── Subprocess ─────────────────────────────────────────


def run_subprocess(cmd: list[str], timeout: int = 30, cwd: str | None = None) -> str:
    """Run subprocess, return stdout. Failure/timeout returns empty string.

    cwd: working directory. Pass `"/tmp"` for `claude -p` calls — the CLI otherwise
    walks up the tree and loads any CLAUDE.md it finds, contaminating prompts.
    """
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd,
        )
        if result.returncode != 0:
            return ""
        return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return ""


# ── logging ─────────────────────────────────────────────


def log_stderr(message: str) -> None:
    """Progress log output to stderr."""
    print(message, file=sys.stderr)


# ── frontmatter parsing ──────────────────────────────────


def parse_frontmatter(content: str) -> dict | None:
    """Parse YAML frontmatter into flat dict.

    Supports single-line `key: value` and YAML folded multiline `key: >\\n  line1\\n  line2`.
    No frontmatter returns None.
    """
    match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
    if not match:
        return None

    raw = match.group(1)
    result: dict = {}
    lines = raw.splitlines()
    index = 0

    while index < len(lines):
        line = lines[index]
        if ":" not in line:
            index += 1
            continue

        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()

        # YAML folded multiline: `key: >`
        if value == ">":
            continuation: list[str] = []
            index += 1
            while index < len(lines) and lines[index].startswith((" ", "\t")):
                continuation.append(lines[index].strip())
                index += 1
            result[key] = " ".join(continuation)
            continue

        result[key] = value.strip('"').strip("'")
        index += 1

    return result
