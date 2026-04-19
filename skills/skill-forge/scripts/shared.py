"""Shared utilities for hooks directory.

Single source of truth for state file, registry, and frontmatter parsing.
Shared across hook scripts to prevent default value drift and parsing inconsistency.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
from datetime import date
from pathlib import Path

# ── path constants ───────────────────────────────────────

SKILLS_DIR = Path(".claude/skills")
USER_SKILLS_DIR = Path.home() / ".claude" / "skills"
REGISTRY_FILE = SKILLS_DIR / "skill_registry.json"

# Workspace lives at `<project_dir>/.skill-forge/` — project-local, outside
# `.claude/` entirely. The `.claude/` trust boundary only exempts real skill
# dirs (those with SKILL.md), `.claude/commands/`, and `.claude/agents/`,
# so any workspace nested under `.claude/` still prompts on Write in plugin
# installs where the local SKILL.md is absent. A sibling dir at project
# root has no such constraint. This also kills a whole class of Python /
# shell slug-algorithm drift bugs: both sides now resolve the same
# absolute path with no stringification step.
WORKSPACE_DIR_NAME = ".skill-forge"
_WORKSPACE_ROOT_ENV = "SKILL_FORGE_WORKSPACE_ROOT"


def workspace_dir(project_dir: Path | None = None) -> Path:
    """Per-project workspace dir at `<project_dir>/.skill-forge/`.

    Env override `SKILL_FORGE_WORKSPACE_ROOT` wins — tests point it at
    tmp_path to keep draft/insights/state out of the real project tree.
    When set, the override is THE workspace dir (not a root above it).
    None `project_dir` falls back to cwd.
    """
    override = os.environ.get(_WORKSPACE_ROOT_ENV)
    if override:
        return Path(override)
    if project_dir is None:
        project_dir = Path.cwd()
    return Path(project_dir) / WORKSPACE_DIR_NAME


def staging_dir(project_dir: Path | None = None) -> Path:
    """Staging root `<workspace>/staging/`.

    New skills and in-progress improve edits assemble here first, then
    `finalize_skill.py` copies them into `.claude/skills/<name>/` via a
    Python subprocess — bypassing Claude's tool permission layer, which
    would otherwise prompt on any Write into a not-yet-real skill dir.
    """
    return workspace_dir(project_dir) / "staging"


def draft_file(project_dir: Path | None = None) -> Path:
    return workspace_dir(project_dir) / "draft.md"


def insights_file(project_dir: Path | None = None) -> Path:
    return workspace_dir(project_dir) / "insights.md"


def state_file(project_dir: Path | None = None) -> Path:
    return workspace_dir(project_dir) / "state.json"

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

# Bridge key between `record_eval_score.py` (writer) and `skill_forge_post_tool.py` (consumer).
# Renaming in one module without the other silently breaks score propagation (stays 0/8).
PENDING_EVAL_SCORE_KEY = "pending_eval_score"


# ── State I/O ───────────────────────────────────────────


def load_state(path: Path | None = None) -> dict:
    """Read state file. Corrupted/missing returns default copy.

    path None uses the cwd-derived per-project state file. Pass explicit path in tests.
    Catches FileNotFoundError + JSON decode errors. Other OSError (e.g. PermissionError)
    is logged to stderr before returning default — silent corruption is dangerous.
    """
    if path is None:
        path = state_file()
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        return dict(DEFAULT_STATE)
    except OSError as e:
        log_stderr(f"skill-forge: state file read error ({e}), using defaults")
        return dict(DEFAULT_STATE)


def save_state(state: dict, path: Path | None = None) -> None:
    """Write state file. Auto-creates parent directory."""
    if path is None:
        path = state_file()
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


_BUMP_PARTS = ("major", "minor", "patch")


def bump_version(v: str, part: str = "patch") -> str:
    """Bump semantic version segment. Malformed input → '1.0.0'.

    part: 'patch' (default), 'minor', or 'major'. Minor/major zero the
    lower segments. Returns '1.0.0' on any parse error — better to
    overwrite garbage than crash a hook.
    """
    if part not in _BUMP_PARTS:
        raise ValueError(f"part must be one of {_BUMP_PARTS}, got {part!r}")
    try:
        major, minor, patch = (int(x) for x in v.split("."))
    except Exception:
        return "1.0.0"
    if part == "major":
        return f"{major + 1}.0.0"
    if part == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def upsert_skill(
    registry: dict,
    fm: dict,
    scope: str,
    eval_score: int | None = None,
    bump: str = "patch",
) -> str:
    """Register a new skill or update an existing entry.

    bump selects which segment to increment on update ('patch', 'minor',
    'major'). New entries always start at '1.0.0' regardless. Returns the
    resulting version string so callers can feed it into a CHANGELOG
    header without re-reading the registry.

    eval_score: session evaluator score (0..8). None preserves the
    existing value on update and defaults to 0 on insert.
    """
    name = fm["name"]
    desc_chars = len(fm.get("description", ""))
    today = date.today().isoformat()
    auto_trigger = str(fm.get("user-invocable", "true")).lower() != "false"

    for entry in registry["skills"]:
        if entry["name"] == name:
            new_version = bump_version(entry.get("version", "1.0.0"), bump)
            entry.update({
                "updated": today,
                "description_chars": desc_chars,
                "version": new_version,
                "auto_trigger": auto_trigger,
            })
            if eval_score is not None:
                entry["eval_score"] = eval_score
            return new_version

    registry["skills"].append({
        "name": name,
        "version": "1.0.0",
        "scope": scope,
        "created": today,
        "updated": today,
        "auto_trigger": auto_trigger,
        "description_chars": desc_chars,
        "eval_score": eval_score if eval_score is not None else 0,
        "usage_count": 0,
    })
    return "1.0.0"


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


# ── rate limiter ─────────────────────────────────────────

# Tier-1 Anthropic cap is 50 RPM — default leaves 4 RPM headroom for retries.
# Raise via constructor on higher tiers. Each optimizer gets its own instance
# so tests stay isolated; self_evolve and optimize_description do not share state.
DEFAULT_RPM = 46


class RateLimiter:
    """Token-bucket style inter-launch throttle for concurrent API callers.

    Only serializes call-start timestamps — the underlying subprocess work
    proceeds concurrently once launched. `sleep` is monkey-patchable by tests.
    Thread-safe; one instance shared across a pool of worker threads.
    """

    def __init__(self, rpm: int = DEFAULT_RPM) -> None:
        self._min_interval = 60.0 / max(rpm, 1)
        self._lock = threading.Lock()
        # Negative infinity makes the first call's gap check pass without sleep
        # regardless of the current monotonic clock reading.
        self._last_launch = float("-inf")

    def throttle(self) -> None:
        """Block until the minimum inter-launch gap has elapsed.

        Lock scopes only the slot reservation — sleep happens unlocked so
        concurrent callers can compute their own future slot in parallel.
        Holding the lock across sleep would collapse pool throughput to a
        single thread.
        """
        with self._lock:
            now = time.monotonic()
            wait = self._min_interval - (now - self._last_launch)
            self._last_launch = now + max(wait, 0.0)
        if wait > 0:
            time.sleep(wait)


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
