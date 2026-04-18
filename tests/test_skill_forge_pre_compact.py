"""Full test suite for skill_forge_pre_compact.py."""

import json
from io import StringIO
from pathlib import Path

import pytest

from shared import state_file
from skill_forge_pre_compact import main, mark_compacted


# ── TestMarkCompacted ──────────────────────────────────


class TestMarkCompacted:
    """compacted flag logic."""

    def test_existing_state(self, tmp_path: Path) -> None:
        """existing state file -> preserve original fields, add compacted=True."""
        state_file = tmp_path / "state.json"
        state_file.write_text(json.dumps({"tool_calls": 3}))
        mark_compacted(state_file)
        result = json.loads(state_file.read_text())
        assert result["compacted"] is True
        assert result["tool_calls"] == 3

    def test_missing_file(self, tmp_path: Path) -> None:
        """file missing -> create with only compacted=True."""
        state_file = tmp_path / "state.json"
        mark_compacted(state_file)
        result = json.loads(state_file.read_text())
        assert result["compacted"] is True

    def test_corrupted_json(self, tmp_path: Path) -> None:
        """corrupted JSON -> overwrite with only compacted=True."""
        state_file = tmp_path / "state.json"
        state_file.write_text("not json")
        mark_compacted(state_file)
        result = json.loads(state_file.read_text())
        assert result["compacted"] is True

    def test_creates_parent_dir(self, tmp_path: Path) -> None:
        """parent dir missing -> auto-create."""
        state_file = tmp_path / "sub" / "state.json"
        mark_compacted(state_file)
        assert state_file.exists()
        result = json.loads(state_file.read_text())
        assert result["compacted"] is True


# ── TestMain ───────────────────────────────────────────


class TestMain:
    """stdin/stdout integration."""

    def test_main_reads_stdin_outputs_empty(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture,
    ) -> None:
        """main consumes stdin, marks state, outputs empty JSON."""
        monkeypatch.setattr("sys.stdin", StringIO("{}"))
        main()
        # stdout: empty JSON
        output = json.loads(capsys.readouterr().out)
        assert output == {}
        # state file under isolated workspace root marked
        result = json.loads(state_file().read_text())
        assert result["compacted"] is True
