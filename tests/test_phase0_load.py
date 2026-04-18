"""Full test suite for phase0_load.py."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from phase0_load import (
    detect_install,
    load_draft_head,
    load_registry_summary,
    load_skills_list,
    main,
    run_catchup,
)
from shared import DRAFT_FILE

DRAFT_CONTENT = """\
# my-skill — IN PROGRESS
## Goal
Test skill
## Phase
Phase 1: codebase research
## Status
pending
extra line 1
extra line 2
extra line 3
extra line 4
extra line 5
extra line 6
extra line 7
extra line 8
extra line 9
extra line 10
extra line 11
extra line 12
extra line 13
"""


# ── TestLoadDraftHead ──────────────────────────────────


class TestLoadDraftHead:
    """Draft head reading."""

    def test_existing_draft(self, tmp_path: Path) -> None:
        """draft exists -> return first N lines."""
        draft = tmp_path / DRAFT_FILE
        draft.parent.mkdir(parents=True)
        draft.write_text(DRAFT_CONTENT)
        result = load_draft_head(tmp_path, max_lines=5)
        lines = result.strip().splitlines()
        assert len(lines) == 5
        assert lines[0] == "# my-skill — IN PROGRESS"

    def test_missing_draft(self, tmp_path: Path) -> None:
        """draft missing -> return empty string."""
        result = load_draft_head(tmp_path)
        assert result == ""

    def test_default_max_lines(self, tmp_path: Path) -> None:
        """default 20 lines."""
        draft = tmp_path / DRAFT_FILE
        draft.parent.mkdir(parents=True)
        draft.write_text(DRAFT_CONTENT)
        result = load_draft_head(tmp_path)
        lines = result.strip().splitlines()
        assert len(lines) <= 20


# ── TestRunCatchup ─────────────────────────────────────


class TestRunCatchup:
    """catchup direct invocation (no subprocess)."""

    def test_catchup_output(self, tmp_path: Path) -> None:
        """has output -> return as-is."""
        with patch("phase0_load.catchup_main", return_value="catchup report"):
            result = run_catchup(tmp_path)
        assert "catchup report" in result

    def test_catchup_empty(self, tmp_path: Path) -> None:
        """no uncaptured tasks -> return empty string."""
        with patch("phase0_load.catchup_main", return_value=""):
            result = run_catchup(tmp_path)
        assert result == ""


# ── TestLoadSkillsList ─────────────────────────────────


class TestLoadSkillsList:
    """Skills directory listing."""

    def test_project_skills(self, tmp_path: Path) -> None:
        """project-level skills dir exists -> list subdirectory names."""
        skills_dir = tmp_path / ".claude" / "skills"
        for name in ("my-skill", "other-skill"):
            (skills_dir / name).mkdir(parents=True)
            (skills_dir / name / "SKILL.md").write_text("# s\n")
        result = load_skills_list(tmp_path)
        assert "my-skill" in result
        assert "other-skill" in result

    def test_no_skills_dir(self, tmp_path: Path) -> None:
        """dir missing -> return empty string."""
        result = load_skills_list(tmp_path)
        assert result == ""

    def test_filters_non_skill_dirs(self, tmp_path: Path) -> None:
        """Only dirs containing SKILL.md count as skills.

        Filters out per-skill `-workspace/` helpers and stray dirs without a
        manifest — including a plugin-mode `skill-forge/` that only holds
        `.workspace/` without a SKILL.md.
        """
        skills_dir = tmp_path / ".claude" / "skills"
        (skills_dir / "real-skill").mkdir(parents=True)
        (skills_dir / "real-skill" / "SKILL.md").write_text("# s\n")
        (skills_dir / "skill-forge" / ".workspace").mkdir(parents=True)
        (skills_dir / "skill-forge" / ".workspace" / "draft.md").write_text("draft")
        (skills_dir / "real-skill-workspace").mkdir()
        (skills_dir / "empty-dir").mkdir()

        result = load_skills_list(tmp_path)
        assert "real-skill" in result
        assert "skill-forge" not in result
        assert "real-skill-workspace" not in result
        assert "empty-dir" not in result


# ── TestLoadRegistrySummary ────────────────────────────


class TestLoadRegistrySummary:
    """Registry summary."""

    def test_existing_registry(self, tmp_path: Path) -> None:
        """registry exists -> return formatted summary."""
        registry_file = tmp_path / ".claude" / "skills" / "skill_registry.json"
        registry_file.parent.mkdir(parents=True)
        registry = {
            "version": "1",
            "skills": [
                {"name": "my-skill", "version": "1.0.0", "updated": "2026-01-01"},
            ],
        }
        registry_file.write_text(json.dumps(registry))
        result = load_registry_summary(tmp_path)
        assert "my-skill" in result
        assert "1.0.0" in result

    def test_missing_registry(self, tmp_path: Path) -> None:
        """registry missing -> shared.load_registry falls back to empty list -> hint no skills."""
        result = load_registry_summary(tmp_path)
        assert "no skills" in result.lower()

    def test_corrupted_registry(self, tmp_path: Path) -> None:
        """registry corrupted -> shared.load_registry falls back to empty list -> hint no skills."""
        registry_file = tmp_path / ".claude" / "skills" / "skill_registry.json"
        registry_file.parent.mkdir(parents=True)
        registry_file.write_text("not json")
        result = load_registry_summary(tmp_path)
        assert "no skills" in result.lower()

    def test_empty_skills_list(self, tmp_path: Path) -> None:
        """registry has no skills -> return hint."""
        registry_file = tmp_path / ".claude" / "skills" / "skill_registry.json"
        registry_file.parent.mkdir(parents=True)
        registry_file.write_text(json.dumps({"version": "1", "skills": []}))
        result = load_registry_summary(tmp_path)
        assert "no skills" in result.lower() or result == ""


# ── TestDetectInstall ──────────────────────────────────


class TestDetectInstall:
    """Install-mode + version detection."""

    def test_plugin_mode_reads_manifest(self, tmp_path: Path) -> None:
        """CLAUDE_PLUGIN_ROOT set -> read plugin.json from that root."""
        plugin_root = tmp_path / "plugin"
        (plugin_root / ".claude-plugin").mkdir(parents=True)
        (plugin_root / ".claude-plugin" / "plugin.json").write_text(
            json.dumps({"name": "skill-forge", "version": "0.9.9"})
        )
        result = detect_install(tmp_path, plugin_root=str(plugin_root), cache_dir=tmp_path / "missing")
        assert "0.9.9" in result
        assert "[plugin]" in result

    def test_plugin_mode_missing_manifest(self, tmp_path: Path) -> None:
        """CLAUDE_PLUGIN_ROOT set but manifest gone -> 'unknown'."""
        plugin_root = tmp_path / "plugin"
        plugin_root.mkdir()
        result = detect_install(tmp_path, plugin_root=str(plugin_root), cache_dir=tmp_path / "missing")
        assert "unknown" in result
        assert "[plugin]" in result

    def test_embed_mode_reads_version_json(self, tmp_path: Path) -> None:
        """No plugin root, version.json present -> embed mode."""
        version_file = tmp_path / ".claude" / "hooks" / "skill-forge" / "version.json"
        version_file.parent.mkdir(parents=True)
        version_file.write_text(
            json.dumps({"version": "0.7.2", "installed": "2026-04-18T10:00:00Z"})
        )
        result = detect_install(tmp_path, plugin_root=None, cache_dir=tmp_path / "missing")
        assert "0.7.2" in result
        assert "[embed" in result

    def test_dev_mode_walks_up_for_manifest(self, tmp_path: Path) -> None:
        """No plugin root, no embed version — walk up to find plugin.json."""
        repo = tmp_path / "repo"
        (repo / ".claude-plugin").mkdir(parents=True)
        (repo / ".claude-plugin" / "plugin.json").write_text(
            json.dumps({"version": "1.0.0"})
        )
        nested = repo / "sub" / "deep"
        nested.mkdir(parents=True)
        result = detect_install(nested, plugin_root=None, cache_dir=tmp_path / "missing")
        assert "1.0.0" in result
        assert "[dev" in result

    def test_stale_cache_warning_on_multiple_versions(self, tmp_path: Path) -> None:
        """Multiple plugin cache version dirs -> emit warning."""
        cache = tmp_path / "cache"
        (cache / "0.2.0").mkdir(parents=True)
        (cache / "0.7.2").mkdir()
        plugin_root = tmp_path / "plugin"
        (plugin_root / ".claude-plugin").mkdir(parents=True)
        (plugin_root / ".claude-plugin" / "plugin.json").write_text(
            json.dumps({"version": "0.7.2"})
        )
        result = detect_install(tmp_path, plugin_root=str(plugin_root), cache_dir=cache)
        assert "WARNING" in result
        assert "0.2.0" in result
        assert "0.7.2" in result

    def test_no_warning_for_single_cache_version_in_plugin_mode(self, tmp_path: Path) -> None:
        """Plugin mode + one cache version dir -> no warning (that's the happy path)."""
        cache = tmp_path / "cache"
        (cache / "0.7.2").mkdir(parents=True)
        plugin_root = tmp_path / "plugin"
        (plugin_root / ".claude-plugin").mkdir(parents=True)
        (plugin_root / ".claude-plugin" / "plugin.json").write_text(
            json.dumps({"version": "0.7.2"})
        )
        result = detect_install(tmp_path, plugin_root=str(plugin_root), cache_dir=cache)
        assert "WARNING" not in result

    def test_embed_mode_warns_on_any_plugin_cache(self, tmp_path: Path) -> None:
        """Embed install + residual plugin cache -> warn, because Claude's
        bash-fallback skill lookup can still hit the cache and ghost-load."""
        cache = tmp_path / "cache"
        (cache / "0.2.0").mkdir(parents=True)
        version_file = tmp_path / ".claude" / "hooks" / "skill-forge" / "version.json"
        version_file.parent.mkdir(parents=True)
        version_file.write_text(json.dumps({"version": "0.7.2", "installed": "t"}))
        result = detect_install(tmp_path, plugin_root=None, cache_dir=cache)
        assert "WARNING" in result
        assert "marketplace plugin cache" in result

    def test_nothing_detected_returns_empty(self, tmp_path: Path) -> None:
        """No plugin root, no embed, no ancestor manifest -> empty string.

        tmp_path on macOS/Linux lives under /private/var/... or /tmp and its
        ancestors never contain .claude-plugin/, so the walk-up yields nothing.
        """
        isolated = tmp_path / "iso"
        isolated.mkdir()
        result = detect_install(isolated, plugin_root=None, cache_dir=tmp_path / "missing")
        assert result == ""


# ── TestMain ───────────────────────────────────────────


class TestMain:
    """Integration: main output contains section headers."""

    def test_full_output_with_draft(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """draft present -> output contains draft section."""
        draft = tmp_path / DRAFT_FILE
        draft.parent.mkdir(parents=True)
        draft.write_text("# test — IN PROGRESS\n## Status\npending\n")

        with patch("phase0_load.catchup_main", return_value=""):
            main(project_dir=tmp_path)

        output = capsys.readouterr().out
        assert "=== Draft ===" in output

    def test_full_output_without_draft(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """no draft -> output does not contain draft section."""
        with patch("phase0_load.catchup_main", return_value=""):
            main(project_dir=tmp_path)

        output = capsys.readouterr().out
        assert "=== Draft ===" not in output
