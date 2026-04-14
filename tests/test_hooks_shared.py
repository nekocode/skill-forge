"""Full test suite for skills/skill-forge/scripts/shared.py."""

import json
from pathlib import Path

from shared import (
    DEFAULT_STATE,
    load_registry,
    load_state,
    parse_frontmatter,
    save_registry,
    save_state,
)


# ── load_state / save_state ──────────────────────────────


class TestLoadState:
    """State file loading."""

    def test_missing_file_returns_default(self, tmp_path: Path) -> None:
        """file missing -> return copy of default."""
        result = load_state(tmp_path / "nope.json")
        assert result == DEFAULT_STATE
        # must be a copy, not the same object
        assert result is not DEFAULT_STATE

    def test_corrupted_json_returns_default(self, tmp_path: Path) -> None:
        """corrupted JSON -> return default."""
        f = tmp_path / "state.json"
        f.write_text("{broken")
        result = load_state(f)
        assert result == DEFAULT_STATE

    def test_reads_valid_state(self, tmp_path: Path) -> None:
        """valid JSON -> return as-is."""
        f = tmp_path / "state.json"
        data = {"tool_calls": 7, "custom": True}
        f.write_text(json.dumps(data))
        result = load_state(f)
        assert result == data

    def test_permission_error_returns_default_with_warning(self, tmp_path: Path, capsys) -> None:
        """PermissionError -> return default + log to stderr."""
        f = tmp_path / "state.json"
        f.write_text("{}")
        f.chmod(0o000)
        result = load_state(f)
        assert result == DEFAULT_STATE
        assert "state file read error" in capsys.readouterr().err
        f.chmod(0o644)  # restore for cleanup


class TestSaveState:
    """State file writing."""

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        """auto-create missing parent dirs."""
        f = tmp_path / "deep" / "nested" / "state.json"
        save_state({"tool_calls": 3}, f)
        assert f.exists()
        assert json.loads(f.read_text())["tool_calls"] == 3

    def test_overwrites_existing(self, tmp_path: Path) -> None:
        """overwrite existing file."""
        f = tmp_path / "state.json"
        f.write_text('{"old": true}')
        save_state({"new": True}, f)
        assert json.loads(f.read_text()) == {"new": True}


# ── load_registry / save_registry ────────────────────────


class TestLoadRegistry:
    """Registry loading."""

    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        """file missing -> empty registry (with version field)."""
        result = load_registry(tmp_path / "nope.json")
        assert result == {"version": "1", "skills": []}

    def test_corrupted_json_returns_empty(self, tmp_path: Path) -> None:
        f = tmp_path / "reg.json"
        f.write_text("not json")
        result = load_registry(f)
        assert result == {"version": "1", "skills": []}

    def test_reads_valid_registry(self, tmp_path: Path) -> None:
        f = tmp_path / "reg.json"
        data = {"version": "1", "skills": [{"name": "x"}]}
        f.write_text(json.dumps(data))
        result = load_registry(f)
        assert result == data


class TestSaveRegistry:
    """Registry writing."""

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        f = tmp_path / "a" / "b" / "reg.json"
        save_registry({"version": "1", "skills": []}, f)
        assert f.exists()
        assert json.loads(f.read_text())["version"] == "1"


# ── parse_frontmatter ────────────────────────────────────


class TestParseFrontmatter:
    """YAML frontmatter parsing."""

    def test_no_frontmatter(self) -> None:
        """no --- block -> None."""
        assert parse_frontmatter("# Just markdown") is None

    def test_simple_fields(self) -> None:
        """single-line key: value parsed correctly."""
        content = "---\nname: my-skill\nversion: 1.0\n---\n# Body\n"
        result = parse_frontmatter(content)
        assert result is not None
        assert result["name"] == "my-skill"
        assert result["version"] == "1.0"

    def test_strips_quotes(self) -> None:
        """surrounding quotes stripped from value."""
        content = '---\nname: "quoted"\n---\n'
        result = parse_frontmatter(content)
        assert result is not None
        assert result["name"] == "quoted"

    def test_multiline_folded_description(self) -> None:
        """YAML folded multiline (description: >) joined correctly."""
        content = (
            "---\n"
            "name: deploy\n"
            "description: >\n"
            "  First line of desc.\n"
            "  Second line of desc.\n"
            "user-invocable: true\n"
            "---\n"
        )
        result = parse_frontmatter(content)
        assert result is not None
        assert result["description"] == "First line of desc. Second line of desc."
        # fields after multiline also parsed correctly
        assert result["user-invocable"] == "true"

    def test_multiline_at_end(self) -> None:
        """folded multiline at end of frontmatter (no trailing fields)."""
        content = (
            "---\n"
            "name: x\n"
            "description: >\n"
            "  Only line.\n"
            "---\n"
        )
        result = parse_frontmatter(content)
        assert result is not None
        assert result["description"] == "Only line."

    def test_empty_frontmatter(self) -> None:
        """empty frontmatter -> empty dict."""
        content = "---\n\n---\n"
        result = parse_frontmatter(content)
        assert result is not None
        assert result == {}

    def test_line_without_colon_skipped(self) -> None:
        """lines without colon are skipped."""
        content = "---\nname: x\njust a line\nversion: 2\n---\n"
        result = parse_frontmatter(content)
        assert result is not None
        assert result["name"] == "x"
        assert result["version"] == "2"

    def test_value_with_colon(self) -> None:
        """value containing colon -> split only on first colon."""
        content = "---\nurl: https://example.com\n---\n"
        result = parse_frontmatter(content)
        assert result is not None
        assert result["url"] == "https://example.com"

    def test_multiline_tabs_indent(self) -> None:
        """tab-indented multiline handled correctly."""
        content = "---\ndesc: >\n\tline one\n\tline two\n---\n"
        result = parse_frontmatter(content)
        assert result is not None
        assert result["desc"] == "line one line two"
