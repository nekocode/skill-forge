"""Structural YAML frontmatter validator for SKILL.md.

Ported from Anthropic's skill-creator quick_validate.py. Runs before registry
upsert in PostToolUse hook so field typos / schema violations never land
silently. Non-blocking — returns a list of error strings the hook surfaces as
systemMessage warnings. CLI entry exits 0 on empty list, 1 otherwise.

Enforced by Claude Code spec:
- name: kebab-case, ≤ 64 chars
- description: ≤ 1024 chars, no angle brackets (breaks YAML parsing downstream)
- only these top-level keys: name, description, license, allowed-tools,
  user-invocable, metadata, compatibility, hooks
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Claude Code SKILL.md spec — any other top-level key indicates a typo or
# non-standard extension we don't want silently accepted into the registry.
ALLOWED_KEYS = frozenset({
    "name",
    "description",
    "license",
    "allowed-tools",
    "user-invocable",
    "metadata",
    "compatibility",
    "hooks",
})

MAX_NAME_CHARS = 64
MAX_DESCRIPTION_CHARS = 1024
MAX_COMPATIBILITY_CHARS = 500
NAME_PATTERN = re.compile(r"^[a-z0-9-]+$")


def _extract_frontmatter(content: str) -> tuple[dict | None, str | None]:
    """Extract raw frontmatter dict plus a parse error on failure.

    Prefers PyYAML (dicts-of-dicts, quoted strings, list values all work). Falls
    back to shared.parse_frontmatter which handles flat key/value only — enough
    for the required-field checks even when PyYAML is absent.
    """
    if not content.startswith("---"):
        return None, "No YAML frontmatter found"

    match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
    if not match:
        return None, "Invalid frontmatter format"

    raw = match.group(1)
    try:
        import yaml  # type: ignore
        data = yaml.safe_load(raw)
    except ImportError:
        from shared import parse_frontmatter
        data = parse_frontmatter(content)
    except Exception as exc:  # noqa: BLE001 — yaml.YAMLError subclasses vary
        return None, f"Invalid YAML in frontmatter: {exc}"

    if not isinstance(data, dict):
        return None, "Frontmatter must be a YAML dictionary"

    return data, None


def validate_skill(skill_path: Path | str, content: str | None = None) -> list[str]:
    """Validate a skill directory's SKILL.md. Empty list = valid.

    Accepts either the directory or SKILL.md path directly so callers don't
    have to normalize. Pass `content` to skip the file read when the caller
    already has the bytes in hand (e.g. the PostToolUse hook).
    """
    path = Path(skill_path)
    skill_md = path / "SKILL.md" if path.is_dir() else path

    if content is None:
        if not skill_md.is_file():
            return ["SKILL.md not found"]
        try:
            content = skill_md.read_text()
        except OSError as exc:
            return [f"Cannot read SKILL.md: {exc}"]

    frontmatter, err = _extract_frontmatter(content)
    if err is not None:
        return [err]
    assert frontmatter is not None  # err-None invariant

    errors: list[str] = []

    unexpected = set(frontmatter.keys()) - ALLOWED_KEYS
    if unexpected:
        errors.append(
            f"Unexpected frontmatter key(s): {', '.join(sorted(unexpected))}. "
            f"Allowed: {', '.join(sorted(ALLOWED_KEYS))}"
        )

    if "name" not in frontmatter:
        errors.append("Missing required field: name")
    else:
        errors.extend(_validate_name(frontmatter["name"]))

    if "description" not in frontmatter:
        errors.append("Missing required field: description")
    else:
        errors.extend(_validate_description(frontmatter["description"]))

    if "compatibility" in frontmatter:
        errors.extend(_validate_compatibility(frontmatter["compatibility"]))

    return errors


def _validate_name(name: object) -> list[str]:
    """Kebab-case + length. Non-string type is a hard error."""
    if not isinstance(name, str):
        return [f"name must be a string, got {type(name).__name__}"]
    stripped = name.strip()
    if not stripped:
        return ["name cannot be empty"]
    if not NAME_PATTERN.match(stripped):
        return [f"name '{stripped}' must be kebab-case (lowercase letters, digits, hyphens only)"]
    if stripped.startswith("-") or stripped.endswith("-") or "--" in stripped:
        return [f"name '{stripped}' cannot start/end with hyphen or contain consecutive hyphens"]
    if len(stripped) > MAX_NAME_CHARS:
        return [f"name too long ({len(stripped)} chars, max {MAX_NAME_CHARS})"]
    return []


def _validate_description(desc: object) -> list[str]:
    """Length + angle-bracket ban (description is interpolated into prompts)."""
    if not isinstance(desc, str):
        return [f"description must be a string, got {type(desc).__name__}"]
    stripped = desc.strip()
    if not stripped:
        return ["description cannot be empty"]
    errors: list[str] = []
    if "<" in stripped or ">" in stripped:
        errors.append("description cannot contain angle brackets (< or >)")
    if len(stripped) > MAX_DESCRIPTION_CHARS:
        errors.append(f"description too long ({len(stripped)} chars, max {MAX_DESCRIPTION_CHARS})")
    return errors


def _validate_compatibility(compat: object) -> list[str]:
    """Optional free-form string capped at 500 chars."""
    if not isinstance(compat, str):
        return [f"compatibility must be a string, got {type(compat).__name__}"]
    if len(compat) > MAX_COMPATIBILITY_CHARS:
        return [f"compatibility too long ({len(compat)} chars, max {MAX_COMPATIBILITY_CHARS})"]
    return []


def main() -> None:  # pragma: no cover — CLI entry guard
    if len(sys.argv) != 2:
        print("Usage: python quick_validate.py <skill_directory_or_SKILL.md>", file=sys.stderr)
        sys.exit(2)

    errors = validate_skill(sys.argv[1])
    if not errors:
        print("Skill is valid!")
        sys.exit(0)
    for err in errors:
        print(f"ERROR: {err}", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":  # pragma: no cover
    main()
