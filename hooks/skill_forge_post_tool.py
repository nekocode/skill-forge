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
    load_registry,
    load_state,
    parse_frontmatter,
    save_registry,
    save_state,
)

REQUIRED_FRONTMATTER = {"name", "description"}


# ── Registry helpers ─────────────────────────────────────────────────────────


def upsert_skill(registry: dict, fm: dict, scope: str):
    """Register or update a skill. name/description derived from fm to reduce param redundancy."""
    name = fm["name"]
    desc_chars = len(fm.get("description", ""))
    today = date.today().isoformat()
    for entry in registry["skills"]:
        if entry["name"] == name:
            entry.update({"updated": today, "description_chars": desc_chars,
                          "version": bump_version(entry.get("version", "1.0.0"))})
            return
    registry["skills"].append({
        "name": name, "version": "1.0.0", "scope": scope,
        "created": today, "updated": today,
        "auto_trigger": fm.get("user-invocable", "true").lower() != "false",
        "description_chars": desc_chars, "eval_score": 0, "usage_count": 0,
    })


def bump_version(v: str) -> str:
    parts = v.split(".")
    try:
        parts[-1] = str(int(parts[-1]) + 1)
    except Exception:
        parts = ["1", "0", "0"]
    return ".".join(parts)


# ── Validation ───────────────────────────────────────────────────────────────


def validate_skill(content: str, fm: dict | None = None) -> list[str]:
    """Return list of warning strings (not errors — we don't block).

    fm: pre-parsed frontmatter to avoid redundant parsing. None triggers internal parsing.
    """
    warnings = []
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
    save_state(state)

    # file_path compat: Write/Edit use file_path, fall back to path
    file_path = tool_input.get("file_path", "") or tool_input.get("path", "")
    if Path(file_path).name == "SKILL.md" and tool_name in FILE_WRITE_TOOLS:
        skill_path = Path(file_path)
        try:
            content = skill_path.read_text()
        except OSError:
            print(json.dumps({}))
            return

        fm = parse_frontmatter(content)
        warnings = validate_skill(content, fm=fm)

        if fm and fm.get("name"):
            scope = "project" if ".claude" in skill_path.parts else "personal"
            registry = load_registry()
            upsert_skill(registry, fm, scope)
            save_registry(registry)

        if warnings:
            warn_text = "skill-forge registry updated. Validation notes:\n" + \
                        "\n".join(f"  - {w}" for w in warnings)
            print(json.dumps({"systemMessage": warn_text}))
            return

    print(json.dumps({}))


if __name__ == "__main__":
    main()
