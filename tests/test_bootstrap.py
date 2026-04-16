"""Tests for hooks/_bootstrap.py — resolve_scripts_path()."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from _bootstrap import resolve_scripts_path


_HOOKS_DIR = Path(__file__).parent.parent / "hooks"


class TestResolveScriptsPath:
    """Covers all 3 resolution branches: plugin, embed, dev fallback."""

    def test_plugin_mode_uses_claude_plugin_root(self, tmp_path: Path) -> None:
        plugin_root = str(tmp_path / "plugin")
        expected = str(Path(plugin_root) / "skills" / "skill-forge" / "scripts")

        with patch.dict(os.environ, {"CLAUDE_PLUGIN_ROOT": plugin_root}, clear=False):
            result = resolve_scripts_path()

        assert result == expected

    def test_embed_mode_uses_claude_project_dir(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "project"
        scripts_dir = project_dir / ".claude" / "skills" / "skill-forge" / "scripts"
        scripts_dir.mkdir(parents=True)

        env = {"CLAUDE_PROJECT_DIR": str(project_dir)}
        with patch.dict(os.environ, env, clear=False):
            # Remove CLAUDE_PLUGIN_ROOT to force embed path
            os.environ.pop("CLAUDE_PLUGIN_ROOT", None)
            result = resolve_scripts_path()

        assert result == str(scripts_dir)

    def test_embed_mode_skips_when_dir_missing(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        # .claude/skills/skill-forge/scripts/ does NOT exist

        env = {"CLAUDE_PROJECT_DIR": str(project_dir)}
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("CLAUDE_PLUGIN_ROOT", None)
            result = resolve_scripts_path()

        # Falls through to dev fallback
        assert "skills" in result
        assert "scripts" in result

    def test_plugin_root_takes_priority_over_project_dir(self, tmp_path: Path) -> None:
        plugin_root = str(tmp_path / "plugin")
        project_dir = tmp_path / "project"
        scripts_dir = project_dir / ".claude" / "skills" / "skill-forge" / "scripts"
        scripts_dir.mkdir(parents=True)

        env = {
            "CLAUDE_PLUGIN_ROOT": plugin_root,
            "CLAUDE_PROJECT_DIR": str(project_dir),
        }
        with patch.dict(os.environ, env, clear=False):
            result = resolve_scripts_path()

        # Plugin root wins
        expected = str(Path(plugin_root) / "skills" / "skill-forge" / "scripts")
        assert result == expected

    def test_dev_fallback_without_env_vars(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CLAUDE_PLUGIN_ROOT", None)
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
            result = resolve_scripts_path()

        # Fallback: hooks/ parent → skills/skill-forge/scripts/
        assert result.endswith(str(Path("skills") / "skill-forge" / "scripts"))
