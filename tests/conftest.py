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

    When the env var is set, workspace_dir() returns it verbatim (THE
    workspace dir, not a root above it). This keeps draft.md / insights.md /
    state.json / staging/ out of the real project tree during tests —
    without it, workspace_dir() would resolve to `<cwd>/.skill-forge/`
    and write into wherever pytest happened to be invoked from.
    """
    monkeypatch.setenv("SKILL_FORGE_WORKSPACE_ROOT", str(tmp_path / ".skill-forge"))
