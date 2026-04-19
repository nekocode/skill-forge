"""Full test suite for quick_validate.py."""

from pathlib import Path

from quick_validate import (
    ALLOWED_KEYS,
    MAX_DESCRIPTION_CHARS,
    MAX_NAME_CHARS,
    validate_skill,
)


def _write_skill(tmp_path: Path, content: str) -> Path:
    """Write SKILL.md into tmp_path and return the skill directory path."""
    (tmp_path / "SKILL.md").write_text(content)
    return tmp_path


# ── Happy path ───────────────────────────────────────


class TestValidSkill:
    """Valid SKILL.md inputs produce empty error lists."""

    def test_minimal_valid(self, tmp_path: Path) -> None:
        """just name + description."""
        skill_dir = _write_skill(tmp_path, (
            "---\n"
            "name: my-skill\n"
            "description: Use when doing complex multi-step work\n"
            "---\n"
            "# Body\n"
        ))
        assert validate_skill(skill_dir) == []

    def test_accepts_skill_md_path_directly(self, tmp_path: Path) -> None:
        """passing SKILL.md path instead of directory works the same."""
        skill_dir = _write_skill(tmp_path, (
            "---\n"
            "name: my-skill\n"
            "description: Valid description here\n"
            "---\n"
        ))
        assert validate_skill(skill_dir / "SKILL.md") == []

    def test_accepts_all_allowed_keys(self, tmp_path: Path) -> None:
        """every key in ALLOWED_KEYS passes validation."""
        skill_dir = _write_skill(tmp_path, (
            "---\n"
            "name: my-skill\n"
            "description: test\n"
            "license: MIT\n"
            "allowed-tools: Read, Write\n"
            "user-invocable: true\n"
            "compatibility: claude-code >= 0.5\n"
            "---\n"
        ))
        assert validate_skill(skill_dir) == []


# ── File-level errors ────────────────────────────────


class TestFileErrors:
    """Missing files and unreadable paths."""

    def test_missing_skill_md(self, tmp_path: Path) -> None:
        """empty directory -> single error."""
        errors = validate_skill(tmp_path)
        assert errors == ["SKILL.md not found"]

    def test_no_frontmatter(self, tmp_path: Path) -> None:
        """plain markdown -> no-frontmatter error."""
        skill_dir = _write_skill(tmp_path, "# Just a header\nNo YAML here\n")
        errors = validate_skill(skill_dir)
        assert len(errors) == 1
        assert "No YAML frontmatter" in errors[0]

    def test_malformed_frontmatter(self, tmp_path: Path) -> None:
        """frontmatter opened but never closed -> format error."""
        skill_dir = _write_skill(tmp_path, "---\nname: x\n# no closing ---\n")
        errors = validate_skill(skill_dir)
        assert len(errors) == 1
        assert "Invalid frontmatter format" in errors[0]


# ── Name validation ──────────────────────────────────


class TestName:
    """Kebab-case, length, presence."""

    def test_missing_name(self, tmp_path: Path) -> None:
        skill_dir = _write_skill(tmp_path, "---\ndescription: hi\n---\n")
        errors = validate_skill(skill_dir)
        assert any("name" in e for e in errors)

    def test_uppercase_rejected(self, tmp_path: Path) -> None:
        skill_dir = _write_skill(tmp_path, (
            "---\nname: MySkill\ndescription: hi\n---\n"
        ))
        errors = validate_skill(skill_dir)
        assert any("kebab-case" in e for e in errors)

    def test_underscore_rejected(self, tmp_path: Path) -> None:
        skill_dir = _write_skill(tmp_path, (
            "---\nname: my_skill\ndescription: hi\n---\n"
        ))
        errors = validate_skill(skill_dir)
        assert any("kebab-case" in e for e in errors)

    def test_leading_hyphen_rejected(self, tmp_path: Path) -> None:
        skill_dir = _write_skill(tmp_path, (
            "---\nname: -bad\ndescription: hi\n---\n"
        ))
        errors = validate_skill(skill_dir)
        assert any("hyphen" in e for e in errors)

    def test_double_hyphen_rejected(self, tmp_path: Path) -> None:
        skill_dir = _write_skill(tmp_path, (
            "---\nname: my--skill\ndescription: hi\n---\n"
        ))
        errors = validate_skill(skill_dir)
        assert any("hyphen" in e for e in errors)

    def test_too_long_rejected(self, tmp_path: Path) -> None:
        long_name = "a" * (MAX_NAME_CHARS + 1)
        skill_dir = _write_skill(tmp_path, (
            f"---\nname: {long_name}\ndescription: hi\n---\n"
        ))
        errors = validate_skill(skill_dir)
        assert any("too long" in e for e in errors)

    def test_exactly_max_length_accepted(self, tmp_path: Path) -> None:
        """boundary: exactly MAX_NAME_CHARS letters — still valid."""
        name = "a" * MAX_NAME_CHARS
        skill_dir = _write_skill(tmp_path, (
            f"---\nname: {name}\ndescription: hi\n---\n"
        ))
        assert validate_skill(skill_dir) == []


# ── Description validation ───────────────────────────


class TestDescription:
    """Length and angle-bracket ban."""

    def test_missing_description(self, tmp_path: Path) -> None:
        skill_dir = _write_skill(tmp_path, "---\nname: x\n---\n")
        errors = validate_skill(skill_dir)
        assert any("description" in e.lower() for e in errors)

    def test_angle_brackets_rejected(self, tmp_path: Path) -> None:
        """angle brackets break downstream prompt interpolation."""
        skill_dir = _write_skill(tmp_path, (
            "---\nname: x\ndescription: use <when> X\n---\n"
        ))
        errors = validate_skill(skill_dir)
        assert any("angle brackets" in e for e in errors)

    def test_too_long_rejected(self, tmp_path: Path) -> None:
        long_desc = "X" * (MAX_DESCRIPTION_CHARS + 1)
        skill_dir = _write_skill(tmp_path, (
            f"---\nname: x\ndescription: {long_desc}\n---\n"
        ))
        errors = validate_skill(skill_dir)
        assert any("too long" in e for e in errors)


# ── Unknown keys ─────────────────────────────────────


class TestUnknownKeys:
    """Any key outside ALLOWED_KEYS surfaces as a warning."""

    def test_typo_key_surfaces(self, tmp_path: Path) -> None:
        """'descripton' typo (missing 'i') does NOT quietly fill description."""
        skill_dir = _write_skill(tmp_path, (
            "---\n"
            "name: x\n"
            "description: valid here\n"
            "descripton: typo\n"  # note the typo
            "---\n"
        ))
        errors = validate_skill(skill_dir)
        assert any("descripton" in e for e in errors)

    def test_allowed_keys_constant_is_frozenset(self) -> None:
        """immutable — prevents accidental runtime mutation of spec."""
        assert isinstance(ALLOWED_KEYS, frozenset)
