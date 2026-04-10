"""Full test suite for skill_forge_stop.py."""

import json
from io import StringIO
from pathlib import Path

import pytest

from skill_forge_stop import build_message, main, should_trigger


# ── TestShouldTrigger ─────────────────────────────────


class TestShouldTrigger:
    """Threshold evaluation logic."""

    def test_compacted_skips_trigger(self) -> None:
        """compacted=True -> no trigger, reason marked compacted for main to reset."""
        state = {
            "compacted": True,
            "tool_calls": 99,
            "error_recovery": True,
            "user_correction": True,
        }
        trigger, reason = should_trigger(state)
        assert trigger is False
        assert reason == "compacted"

    def test_error_recovery(self) -> None:
        """error_recovery flag -> trigger, reason contains error recovery."""
        state = {"error_recovery": True, "tool_calls": 2}
        trigger, reason = should_trigger(state)
        assert trigger is True
        assert "error recovery" in reason
        assert "2 tool calls" in reason

    def test_user_correction(self) -> None:
        """user_correction flag -> trigger, reason contains user correction."""
        state = {"user_correction": True, "tool_calls": 1}
        trigger, reason = should_trigger(state)
        assert trigger is True
        assert "user correction" in reason
        assert "1 tool calls" in reason

    def test_error_recovery_takes_precedence_over_user_correction(self) -> None:
        """error_recovery takes precedence over user_correction check."""
        state = {"error_recovery": True, "user_correction": True, "tool_calls": 3}
        trigger, reason = should_trigger(state)
        assert trigger is True
        assert "error recovery" in reason

    def test_tool_count_at_threshold(self) -> None:
        """tool_calls == TOOL_CALL_THRESHOLD -> trigger."""
        state = {"tool_calls": 5}
        trigger, reason = should_trigger(state)
        assert trigger is True
        assert "5 tool calls" in reason
        assert "complex workflow" in reason

    def test_tool_count_above_threshold(self) -> None:
        """tool_calls > TOOL_CALL_THRESHOLD -> trigger."""
        state = {"tool_calls": 12}
        trigger, reason = should_trigger(state)
        assert trigger is True
        assert "12 tool calls" in reason

    def test_tool_count_below_threshold(self) -> None:
        """tool_calls < TOOL_CALL_THRESHOLD -> no trigger."""
        state = {"tool_calls": 4}
        trigger, reason = should_trigger(state)
        assert trigger is False
        assert reason == ""

    def test_all_false_empty_state(self) -> None:
        """empty state -> no trigger."""
        trigger, reason = should_trigger({})
        assert trigger is False
        assert reason == ""

    def test_all_flags_false_explicitly(self) -> None:
        """all flags explicitly False, count 0 -> no trigger."""
        state = {
            "compacted": False,
            "error_recovery": False,
            "user_correction": False,
            "tool_calls": 0,
        }
        trigger, reason = should_trigger(state)
        assert trigger is False
        assert reason == ""


# ── TestBuildMessage ──────────────────────────────────


class TestBuildMessage:
    """Message building logic."""

    def test_with_summary(self) -> None:
        """with summary -> message contains Task summary line."""
        msg = build_message("test reason", "did something cool")
        assert "[skill-forge]" in msg
        assert "test reason" in msg
        assert "Task summary: did something cool" in msg
        assert "Ask the user:" in msg
        assert "/skill-forge create" in msg

    def test_without_summary(self) -> None:
        """empty summary -> message does not contain Task summary line."""
        msg = build_message("another reason", "")
        assert "another reason" in msg
        assert "Task summary:" not in msg
        assert "Ask the user:" in msg

    def test_message_structure(self) -> None:
        """message contains full user interaction guidance."""
        msg = build_message("r", "s")
        assert "[y] Create skill" in msg
        assert "[n] Skip" in msg
        assert "[rename: ___]" in msg
        assert "If user says yes" in msg
        assert "If user says no" in msg


# ── TestMain ──────────────────────────────────────────


class TestMain:
    """stdin/stdout integration + state read/write."""

    def test_trigger_path_outputs_system_message(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
        tmp_path: Path,
    ) -> None:
        """trigger condition met -> output systemMessage + continue=True."""
        state_file = tmp_path / "state.json"
        state_file.write_text(json.dumps({
            "tool_calls": 10,
            "error_recovery": False,
            "user_correction": False,
            "pending_summary": "built a widget",
            "compacted": False,
        }))
        monkeypatch.setattr("skill_forge_stop.load_state", lambda: json.loads(state_file.read_text()))
        monkeypatch.setattr("skill_forge_stop.save_state", lambda s: state_file.write_text(json.dumps(s)))
        monkeypatch.setattr("sys.stdin", StringIO("{}"))

        main()

        output = json.loads(capsys.readouterr().out)
        assert "systemMessage" in output
        assert output["continue"] is True
        assert "built a widget" in output["systemMessage"]
        assert "[skill-forge]" in output["systemMessage"]

    def test_trigger_path_resets_state(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
        tmp_path: Path,
    ) -> None:
        """after trigger -> all state counters/flags reset."""
        state_file = tmp_path / "state.json"
        state_file.write_text(json.dumps({
            "tool_calls": 7,
            "error_recovery": True,
            "user_correction": True,
            "pending_summary": "some task",
            "compacted": False,
        }))
        monkeypatch.setattr("skill_forge_stop.load_state", lambda: json.loads(state_file.read_text()))
        monkeypatch.setattr("skill_forge_stop.save_state", lambda s: state_file.write_text(json.dumps(s)))
        monkeypatch.setattr("sys.stdin", StringIO("{}"))

        main()

        saved = json.loads(state_file.read_text())
        assert saved["tool_calls"] == 0
        assert saved["error_recovery"] is False
        assert saved["user_correction"] is False
        assert saved["pending_summary"] == ""
        assert saved["compacted"] is False

    def test_no_trigger_path_outputs_empty_json(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
        tmp_path: Path,
    ) -> None:
        """no trigger -> output empty JSON, state unchanged."""
        state_file = tmp_path / "state.json"
        original = {"tool_calls": 2, "error_recovery": False, "compacted": False}
        state_file.write_text(json.dumps(original))
        monkeypatch.setattr("skill_forge_stop.load_state", lambda: json.loads(state_file.read_text()))
        # save_state should not be called; writes if called for detection
        monkeypatch.setattr("skill_forge_stop.save_state", lambda s: state_file.write_text(json.dumps(s)))
        monkeypatch.setattr("sys.stdin", StringIO("{}"))

        main()

        output = json.loads(capsys.readouterr().out)
        assert output == {}
        # state file unchanged
        assert json.loads(state_file.read_text()) == original

    def test_compacted_state_resets_and_outputs_empty(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
        tmp_path: Path,
    ) -> None:
        """compacted=True -> no trigger, output empty JSON, full reset of all trigger flags."""
        state_file = tmp_path / "state.json"
        state_file.write_text(json.dumps({
            "tool_calls": 20,
            "error_recovery": True,
            "user_correction": True,
            "pending_summary": "leftover",
            "compacted": True,
        }))
        monkeypatch.setattr("skill_forge_stop.load_state", lambda: json.loads(state_file.read_text()))
        monkeypatch.setattr("skill_forge_stop.save_state", lambda s: state_file.write_text(json.dumps(s)))
        monkeypatch.setattr("sys.stdin", StringIO("{}"))

        main()

        output = json.loads(capsys.readouterr().out)
        assert output == {}
        # full reset of all trigger flags to prevent leftover causing false trigger next round
        saved = json.loads(state_file.read_text())
        assert saved["compacted"] is False
        assert saved["tool_calls"] == 0
        assert saved["error_recovery"] is False
        assert saved["user_correction"] is False
        assert saved["pending_summary"] == ""

    def test_stdin_consumed(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
        tmp_path: Path,
    ) -> None:
        """main consumes stdin content (hook protocol requirement)."""
        state_file = tmp_path / "state.json"
        state_file.write_text(json.dumps({"tool_calls": 0}))
        monkeypatch.setattr("skill_forge_stop.load_state", lambda: json.loads(state_file.read_text()))
        monkeypatch.setattr("skill_forge_stop.save_state", lambda s: None)
        stdin = StringIO('{"some": "payload"}')
        monkeypatch.setattr("sys.stdin", stdin)

        main()

        # stdin fully consumed
        assert stdin.read() == ""

    def test_trigger_with_error_recovery(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
        tmp_path: Path,
    ) -> None:
        """error_recovery trigger -> systemMessage contains error recovery info."""
        state_file = tmp_path / "state.json"
        state_file.write_text(json.dumps({
            "tool_calls": 2,
            "error_recovery": True,
            "user_correction": False,
            "pending_summary": "",
            "compacted": False,
        }))
        monkeypatch.setattr("skill_forge_stop.load_state", lambda: json.loads(state_file.read_text()))
        monkeypatch.setattr("skill_forge_stop.save_state", lambda s: state_file.write_text(json.dumps(s)))
        monkeypatch.setattr("sys.stdin", StringIO("{}"))

        main()

        output = json.loads(capsys.readouterr().out)
        assert "error recovery" in output["systemMessage"]
        assert output["continue"] is True
