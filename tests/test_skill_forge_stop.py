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
        state = {"compacted": True, "tool_calls": 99}
        trigger, reason = should_trigger(state)
        assert trigger is False
        assert reason == "compacted"

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
        state = {"compacted": False, "tool_calls": 0}
        trigger, reason = should_trigger(state)
        assert trigger is False
        assert reason == ""


# ── TestBuildMessage ──────────────────────────────────


class TestBuildMessage:
    """Message building logic."""

    def test_basic_message(self) -> None:
        """message contains reason, instructions, and options."""
        msg = build_message("test reason")
        assert "[skill-forge]" in msg
        assert "test reason" in msg
        assert "AskUserQuestion" in msg
        assert "/skill-forge create" in msg

    def test_message_structure(self) -> None:
        """message contains full user interaction guidance."""
        msg = build_message("r")
        assert "Create" in msg
        assert "Skip" in msg
        assert "reset silently" in msg


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
        state_file.write_text(json.dumps({"tool_calls": 10, "compacted": False}))
        monkeypatch.setattr("skill_forge_stop.load_state", lambda: json.loads(state_file.read_text()))
        monkeypatch.setattr("skill_forge_stop.save_state", lambda s: state_file.write_text(json.dumps(s)))
        monkeypatch.setattr("sys.stdin", StringIO("{}"))

        main()

        output = json.loads(capsys.readouterr().out)
        assert "systemMessage" in output
        assert output["continue"] is True
        assert "[skill-forge]" in output["systemMessage"]

    def test_trigger_path_resets_state(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
        tmp_path: Path,
    ) -> None:
        """after trigger -> tool_calls and compacted reset."""
        state_file = tmp_path / "state.json"
        state_file.write_text(json.dumps({"tool_calls": 7, "compacted": False}))
        monkeypatch.setattr("skill_forge_stop.load_state", lambda: json.loads(state_file.read_text()))
        monkeypatch.setattr("skill_forge_stop.save_state", lambda s: state_file.write_text(json.dumps(s)))
        monkeypatch.setattr("sys.stdin", StringIO("{}"))

        main()

        saved = json.loads(state_file.read_text())
        assert saved["tool_calls"] == 0
        assert saved["compacted"] is False

    def test_no_trigger_path_outputs_empty_json(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
        tmp_path: Path,
    ) -> None:
        """no trigger -> output empty JSON, state unchanged."""
        state_file = tmp_path / "state.json"
        original = {"tool_calls": 2, "compacted": False}
        state_file.write_text(json.dumps(original))
        monkeypatch.setattr("skill_forge_stop.load_state", lambda: json.loads(state_file.read_text()))
        monkeypatch.setattr("skill_forge_stop.save_state", lambda s: state_file.write_text(json.dumps(s)))
        monkeypatch.setattr("sys.stdin", StringIO("{}"))

        main()

        output = json.loads(capsys.readouterr().out)
        assert output == {}
        assert json.loads(state_file.read_text()) == original

    def test_compacted_state_resets_and_outputs_empty(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
        tmp_path: Path,
    ) -> None:
        """compacted=True -> no trigger, output empty JSON, full reset."""
        state_file = tmp_path / "state.json"
        state_file.write_text(json.dumps({"tool_calls": 20, "compacted": True}))
        monkeypatch.setattr("skill_forge_stop.load_state", lambda: json.loads(state_file.read_text()))
        monkeypatch.setattr("skill_forge_stop.save_state", lambda s: state_file.write_text(json.dumps(s)))
        monkeypatch.setattr("sys.stdin", StringIO("{}"))

        main()

        output = json.loads(capsys.readouterr().out)
        assert output == {}
        saved = json.loads(state_file.read_text())
        assert saved["compacted"] is False
        assert saved["tool_calls"] == 0

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

        assert stdin.read() == ""
