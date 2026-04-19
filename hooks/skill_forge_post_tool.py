#!/usr/bin/env python3
"""
PostToolUse hook for skill-forge.

Two jobs:
  1. Count tool calls → written to state file for Stop hook
  2. When a SKILL.md is written/edited → validate frontmatter and
     update skill_registry.json deterministically

This hook never blocks (no exit 2). It's a side-effect hook.
"""

import json
import sys
from datetime import date
from pathlib import Path

# Bootstrap: resolve scripts path from shared _bootstrap.py (avoids duplication)
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bootstrap import resolve_scripts_path  # noqa: E402
sys.path.insert(0, resolve_scripts_path())
from shared import (  # noqa: E402
    FILE_WRITE_TOOLS,
    PENDING_EVAL_SCORE_KEY,
    load_registry,
    load_state,
    parse_frontmatter,
    save_registry,
    save_state,
)
from quick_validate import validate_skill as structural_validate  # noqa: E402

REQUIRED_FRONTMATTER = {"name", "description"}


# ── Registry helpers ─────────────────────────────────────────────────────────


def upsert_skill(registry: dict, fm: dict, scope: str, eval_score: int | None = None):
    """Register or update a skill. name/description derived from fm to reduce param redundancy.

    eval_score: session evaluator score (0..8). None preserves existing on update,
    defaults to 0 on insert. Hook passes the consumed pending_eval_score from state.json.
    """
    name = fm["name"]
    desc_chars = len(fm.get("description", ""))
    today = date.today().isoformat()
    # user-invocable defaults true; auto_trigger mirrors it
    auto_trigger = str(fm.get("user-invocable", "true")).lower() != "false"
    for entry in registry["skills"]:
        if entry["name"] == name:
            entry.update({"updated": today, "description_chars": desc_chars,
                          "version": bump_version(entry.get("version", "1.0.0")),
                          "auto_trigger": auto_trigger})
            if eval_score is not None:
                entry["eval_score"] = eval_score
            return
    registry["skills"].append({
        "name": name, "version": "1.0.0", "scope": scope,
        "created": today, "updated": today,
        "auto_trigger": auto_trigger,
        "description_chars": desc_chars,
        "eval_score": eval_score if eval_score is not None else 0,
        "usage_count": 0,
    })


def bump_version(v: str) -> str:
    parts = v.split(".")
    try:
        parts[-1] = str(int(parts[-1]) + 1)
    except Exception:
        parts = ["1", "0", "0"]
    return ".".join(parts)


# ── Validation ───────────────────────────────────────────────────────────────


def validate_skill(content: str, fm: dict | None = None, skill_path: Path | None = None) -> list[str]:
    """Return list of warning strings (not errors — we don't block).

    fm: pre-parsed frontmatter to avoid redundant parsing. None triggers internal parsing.
    skill_path: when provided, runs structural schema validation (kebab-case name,
    description ≤ 1024, allowed-key whitelist) — the first line of defense
    against typos silently landing in the registry.
    """
    warnings: list[str] = []

    # Structural schema first — surfaces field-type / key-whitelist issues
    # that the soft checks below would never catch (e.g. 'descripton' typo
    # means no-op on the soft checks but structural flags it as unexpected key).
    if skill_path is not None:
        warnings.extend(structural_validate(skill_path, content=content))

    if fm is None:
        fm = parse_frontmatter(content)

    if fm is None:
        warnings.append("Missing YAML frontmatter (--- block)")
        return warnings

    missing = REQUIRED_FRONTMATTER - set(fm.keys())
    if missing:
        warnings.append(f"Frontmatter missing fields: {', '.join(missing)}")

    desc = fm.get("description", "")
    if len(desc) > 250:
        warnings.append(f"Description is {len(desc)} chars — Claude Code truncates at 250")
    # multilingual trigger phrase check (mirrors user_prompt.py keyword detection)
    trigger_phrases = ("use when", "use this", "使用时", "使用场景", "使う場合", "사용")
    if not any(phrase in desc.lower() for phrase in trigger_phrases):
        warnings.append("Description lacks a trigger phrase (e.g. 'Use when ...') — may under-trigger")

    return warnings


# ── Main ─────────────────────────────────────────────────────────────────────


def main():
    hook_input = json.loads(sys.stdin.read())
    tool_name = hook_input.get("tool_name", "")
    tool_input = hook_input.get("tool_input", {})

    state = load_state()
    state["tool_calls"] = state.get("tool_calls", 0) + 1

    response: dict = {}

    # file_path compat: Write/Edit use file_path, fall back to path
    file_path = tool_input.get("file_path", "") or tool_input.get("path", "")
    if Path(file_path).name == "SKILL.md" and tool_name in FILE_WRITE_TOOLS:
        skill_path = Path(file_path)
        try:
            content: str | None = skill_path.read_text()
        except OSError:
            content = None

        if content is not None:
            fm = parse_frontmatter(content)
            warnings = validate_skill(content, fm=fm, skill_path=skill_path.parent)

            if fm and fm.get("name"):
                scope = "project" if ".claude" in skill_path.parts else "personal"
                registry = load_registry()
                # Pop so the next unrelated SKILL.md write doesn't inherit a stale score.
                pending_score = state.pop(PENDING_EVAL_SCORE_KEY, None)
                upsert_skill(registry, fm, scope, eval_score=pending_score)
                save_registry(registry)

            if warnings:
                response["systemMessage"] = "skill-forge registry updated. Validation notes:\n" + \
                    "\n".join(f"  - {w}" for w in warnings)

    save_state(state)
    print(json.dumps(response))


if __name__ == "__main__":
    main()
