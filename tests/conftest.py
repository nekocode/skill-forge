"""Shared test fixtures."""

import sys
from pathlib import Path

import pytest

_root = Path(__file__).parent.parent

# allow tests/ to import scripts (incl. shared) and hooks modules directly
sys.path.insert(0, str(_root / "skills" / "skill-forge" / "scripts"))
sys.path.insert(0, str(_root / "hooks"))


@pytest.fixture(autouse=True)
def _isolate_workspace_root(tmp_path, monkeypatch):
    """Point SKILL_FORGE_WORKSPACE_ROOT at a tmp dir for every test.

    workspace_dir() reads the env var first, so this keeps draft.md /
    insights.md / state.json out of the real ~/.skill-forge/ during tests.
    """
    monkeypatch.setenv("SKILL_FORGE_WORKSPACE_ROOT", str(tmp_path / "_ws_root"))
