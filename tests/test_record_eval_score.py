"""Full test suite for record_eval_score.py."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from record_eval_score import MAX_SCORE, main, record_score
from shared import state_file


# ── TestRecordScore ───────────────────────────────────────


class TestRecordScore:
    """Direct API: write pending_eval_score into state.json."""

    def test_writes_pending_score(self) -> None:
        """valid score -> state.pending_eval_score persisted."""
        record_score(6)
        state = json.loads(state_file().read_text())
        assert state["pending_eval_score"] == 6

    def test_overwrites_previous_pending(self) -> None:
        """second call -> overwrites previous pending value."""
        record_score(4)
        record_score(7)
        state = json.loads(state_file().read_text())
        assert state["pending_eval_score"] == 7

    def test_preserves_existing_state_keys(self) -> None:
        """existing tool_calls etc. kept intact when adding pending_eval_score."""
        path = state_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"tool_calls": 12, "compacted": True}))
        record_score(5)
        state = json.loads(path.read_text())
        assert state["tool_calls"] == 12
        assert state["compacted"] is True
        assert state["pending_eval_score"] == 5

    def test_zero_allowed(self) -> None:
        """0 is a valid score (skill failed evaluator) — still persisted."""
        record_score(0)
        state = json.loads(state_file().read_text())
        assert state["pending_eval_score"] == 0

    def test_max_allowed(self) -> None:
        """MAX_SCORE accepted (boundary)."""
        record_score(MAX_SCORE)
        state = json.loads(state_file().read_text())
        assert state["pending_eval_score"] == MAX_SCORE

    def test_negative_rejected(self) -> None:
        """negative -> ValueError, no state written."""
        with pytest.raises(ValueError, match="0..8"):
            record_score(-1)

    def test_above_max_rejected(self) -> None:
        """> MAX_SCORE -> ValueError."""
        with pytest.raises(ValueError, match="0..8"):
            record_score(MAX_SCORE + 1)


# ── TestMain ──────────────────────────────────────────────


class TestMain:
    """CLI entry: argv parsing, error paths, exit codes."""

    def test_valid_int_argv(self, capsys: pytest.CaptureFixture) -> None:
        """integer argv -> records and prints confirmation."""
        main(["7"])
        out = capsys.readouterr().out
        assert "7/8" in out
        state = json.loads(state_file().read_text())
        assert state["pending_eval_score"] == 7

    def test_no_args_exits(self, capsys: pytest.CaptureFixture) -> None:
        """missing argv -> usage message + exit 1."""
        with pytest.raises(SystemExit) as exc:
            main([])
        assert exc.value.code == 1
        assert "Usage" in capsys.readouterr().out

    def test_too_many_args_exits(self, capsys: pytest.CaptureFixture) -> None:
        """multiple argv -> usage message + exit 1."""
        with pytest.raises(SystemExit) as exc:
            main(["6", "extra"])
        assert exc.value.code == 1
        assert "Usage" in capsys.readouterr().out

    def test_non_integer_exits(self, capsys: pytest.CaptureFixture) -> None:
        """non-int argv -> error + exit 1."""
        with pytest.raises(SystemExit) as exc:
            main(["six"])
        assert exc.value.code == 1
        assert "integer" in capsys.readouterr().out

    def test_out_of_range_exits(self, capsys: pytest.CaptureFixture) -> None:
        """out-of-range int -> error + exit 1, state not written."""
        with pytest.raises(SystemExit) as exc:
            main(["99"])
        assert exc.value.code == 1
        assert "0..8" in capsys.readouterr().out
        assert not state_file().exists()
