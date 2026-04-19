"""Full test suite for run_eval.py (real-execution trigger eval).

Everything here mocks subprocess — running a real `claude -p` in unit tests
would be slow and flaky. The protocol layer (stream-json parsing) is covered
by constructing synthetic event sequences that mirror what claude emits.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from run_eval import (
    _handle_event,
    _parse_stream_for_trigger,
    find_project_root,
    run_single_query,
)


# ── find_project_root ────────────────────────────────


class TestFindProjectRoot:
    """Walk-up discovery of .claude/."""

    def test_walks_up_to_claude_dir(self, tmp_path: Path) -> None:
        """start deep inside a .claude-owning tree -> return the root."""
        root = tmp_path / "proj"
        (root / ".claude").mkdir(parents=True)
        deep = root / "a" / "b" / "c"
        deep.mkdir(parents=True)
        assert find_project_root(deep) == root

    def test_no_claude_returns_start(self, tmp_path: Path) -> None:
        """no .claude/ anywhere -> caller's start dir is returned."""
        deep = tmp_path / "a" / "b"
        deep.mkdir(parents=True)
        assert find_project_root(deep) == deep.resolve()

    def test_start_itself_has_claude(self, tmp_path: Path) -> None:
        """start dir itself contains .claude/ -> start is the root."""
        (tmp_path / ".claude").mkdir()
        assert find_project_root(tmp_path) == tmp_path.resolve()


# ── _handle_event: stream_event classification ───────


class TestHandleEventStreamEvents:
    """Parse individual stream events into (state_update, final_verdict)."""

    def test_skill_tool_start_opens_accumulator(self) -> None:
        event = {
            "type": "stream_event",
            "event": {
                "type": "content_block_start",
                "content_block": {"type": "tool_use", "name": "Skill"},
            },
        }
        state, final = _handle_event(event, "my-skill-eval-abc", None, "")
        assert state == ("Skill", "")
        assert final is None

    def test_read_tool_start_opens_accumulator(self) -> None:
        """Read on a skill SKILL.md file also counts as trigger per official convention."""
        event = {
            "type": "stream_event",
            "event": {
                "type": "content_block_start",
                "content_block": {"type": "tool_use", "name": "Read"},
            },
        }
        state, final = _handle_event(event, "my-skill-eval-abc", None, "")
        assert state == ("Read", "")
        assert final is None

    def test_unrelated_tool_short_circuits_false(self) -> None:
        """Bash / Grep / Write -> definitive not-our-skill (no more to check)."""
        event = {
            "type": "stream_event",
            "event": {
                "type": "content_block_start",
                "content_block": {"type": "tool_use", "name": "Bash"},
            },
        }
        state, final = _handle_event(event, "my-skill-eval-abc", None, "")
        assert state is None
        assert final is False

    def test_partial_json_containing_slug_returns_true(self) -> None:
        """content_block_delta with our slug -> early exit True."""
        event = {
            "type": "stream_event",
            "event": {
                "type": "content_block_delta",
                "delta": {
                    "type": "input_json_delta",
                    "partial_json": '{"skill": "my-skill-eval-abc",',
                },
            },
        }
        state, final = _handle_event(event, "my-skill-eval-abc", "Skill", "")
        assert final is True

    def test_partial_json_accumulates_across_deltas(self) -> None:
        """slug may straddle two deltas; accumulation state carries."""
        event1 = {
            "type": "stream_event",
            "event": {
                "type": "content_block_delta",
                "delta": {"type": "input_json_delta", "partial_json": '{"skill": "my-'},
            },
        }
        state1, final1 = _handle_event(event1, "my-skill-eval-abc", "Skill", "")
        assert final1 is None
        assert state1 == ("Skill", '{"skill": "my-')

        event2 = {
            "type": "stream_event",
            "event": {
                "type": "content_block_delta",
                "delta": {"type": "input_json_delta", "partial_json": 'skill-eval-abc"}'},
            },
        }
        _, final2 = _handle_event(event2, "my-skill-eval-abc", "Skill", '{"skill": "my-')
        assert final2 is True

    def test_content_block_stop_without_slug_returns_false(self) -> None:
        """tool input fully streamed without our slug -> False."""
        event = {
            "type": "stream_event",
            "event": {"type": "content_block_stop"},
        }
        _, final = _handle_event(event, "my-skill-eval-abc", "Skill", '{"skill": "other"}')
        assert final is False

    def test_message_stop_without_pending_tool_returns_false(self) -> None:
        """no tool_use seen at all -> clearly not triggered."""
        event = {
            "type": "stream_event",
            "event": {"type": "message_stop"},
        }
        _, final = _handle_event(event, "my-skill-eval-abc", None, "")
        assert final is False

    def test_delta_without_pending_tool_ignored(self) -> None:
        """content_block_delta arriving before content_block_start: no-op."""
        event = {
            "type": "stream_event",
            "event": {
                "type": "content_block_delta",
                "delta": {"type": "input_json_delta", "partial_json": "anything"},
            },
        }
        state, final = _handle_event(event, "my-skill-eval-abc", None, "")
        assert state is None
        assert final is None


# ── _handle_event: assistant fallback ────────────────


class TestHandleEventAssistantFallback:
    """Non-streaming mode (or missed stream): parse the full assistant message."""

    def test_skill_tool_with_slug_returns_true(self) -> None:
        event = {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "name": "Skill",
                        "input": {"skill": "my-skill-eval-abc"},
                    }
                ]
            },
        }
        _, final = _handle_event(event, "my-skill-eval-abc", None, "")
        assert final is True

    def test_read_tool_with_slug_path_returns_true(self) -> None:
        """Read on a file_path containing our slug also qualifies."""
        event = {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "name": "Read",
                        "input": {"file_path": "/x/.claude/commands/my-skill-eval-abc.md"},
                    }
                ]
            },
        }
        _, final = _handle_event(event, "my-skill-eval-abc", None, "")
        assert final is True

    def test_assistant_no_tool_use_returns_false(self) -> None:
        """plain text response -> no trigger."""
        event = {
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": "hello"}]},
        }
        _, final = _handle_event(event, "my-skill-eval-abc", None, "")
        assert final is False


# ── _parse_stream_for_trigger ────────────────────────


class TestParseStream:
    """Integration-ish test: feed a synthetic stream through the parser."""

    def _make_process(self, lines: list[str]) -> MagicMock:
        """Fake Popen whose stdout yields `lines` (one stream-json event each)."""
        proc = MagicMock()
        # readline-based approach would need a harder mock; since the parser
        # reads via os.read(fileno) + line-split, we stage one big chunk.
        payload = ("\n".join(lines) + "\n").encode()
        proc.stdout.fileno.return_value = 999

        # poll(): None until the payload has been drained once, then 0 (done)
        calls = {"n": 0}

        def _poll() -> int | None:
            calls["n"] += 1
            return None if calls["n"] <= 1 else 0

        proc.poll.side_effect = _poll
        return proc, payload

    def test_slug_in_partial_json_short_circuits_true(self) -> None:
        """confirm the parser returns True on first slug hit in a delta."""
        events = [
            json.dumps({"type": "stream_event", "event": {
                "type": "content_block_start",
                "content_block": {"type": "tool_use", "name": "Skill"},
            }}),
            json.dumps({"type": "stream_event", "event": {
                "type": "content_block_delta",
                "delta": {"type": "input_json_delta",
                          "partial_json": '{"skill": "my-skill-eval-abc"}'},
            }}),
        ]
        proc, payload = self._make_process(events)

        with patch("run_eval.select.select", return_value=([proc.stdout], [], [])), \
             patch("run_eval.os.read", side_effect=[payload, b""]):
            assert _parse_stream_for_trigger(proc, "my-skill-eval-abc", timeout=5) is True
        proc.kill.assert_not_called()  # early-exit via return, process still running is OK

    def test_kills_process_if_still_running_on_return(self) -> None:
        """on True-return the process should be killed if poll() is None."""
        events = [
            json.dumps({"type": "stream_event", "event": {
                "type": "content_block_start",
                "content_block": {"type": "tool_use", "name": "Skill"},
            }}),
            json.dumps({"type": "stream_event", "event": {
                "type": "content_block_delta",
                "delta": {"type": "input_json_delta",
                          "partial_json": '{"skill": "my-skill-eval-abc"}'},
            }}),
        ]
        proc = MagicMock()
        proc.stdout.fileno.return_value = 999
        proc.poll.return_value = None  # still running when we return True
        payload = ("\n".join(events) + "\n").encode()

        with patch("run_eval.select.select", return_value=([proc.stdout], [], [])), \
             patch("run_eval.os.read", side_effect=[payload, b""]):
            _parse_stream_for_trigger(proc, "my-skill-eval-abc", timeout=5)
        proc.kill.assert_called_once()


# ── run_single_query lifecycle ───────────────────────


class TestRunSingleQuery:
    """Temp command file management + process launch wiring."""

    def test_writes_and_removes_command_file(self, tmp_path: Path) -> None:
        """temp command file exists during run, gone after."""
        (tmp_path / ".claude").mkdir()

        popen_mock = MagicMock()
        popen_mock.poll.return_value = 0
        popen_mock.stdout.read.return_value = b""

        with patch("run_eval.subprocess.Popen", return_value=popen_mock) as mock_popen, \
             patch("run_eval._parse_stream_for_trigger", return_value=False):
            run_single_query(
                "test query", "my-skill", "test description",
                project_root=tmp_path, timeout=5,
            )

        # Popen got --output-format stream-json
        cmd = mock_popen.call_args[0][0]
        assert "stream-json" in cmd
        assert "--include-partial-messages" in cmd
        # No leftover command files
        leftover = list((tmp_path / ".claude" / "commands").glob("my-skill-eval-*.md"))
        assert leftover == []

    def test_cwd_is_project_root_not_tmp(self, tmp_path: Path) -> None:
        """claude -p must run in project_root so it discovers .claude/commands/.

        Intentional divergence from the LEARNED.local.md 'cwd=/tmp' rule —
        that rule targets generation calls where CLAUDE.md would pollute output;
        here we only observe tool_use events, so project env is required.
        """
        (tmp_path / ".claude").mkdir()
        popen_mock = MagicMock()

        with patch("run_eval.subprocess.Popen", return_value=popen_mock) as mock_popen, \
             patch("run_eval._parse_stream_for_trigger", return_value=False):
            run_single_query(
                "q", "my-skill", "d",
                project_root=tmp_path, timeout=5,
            )
        assert mock_popen.call_args.kwargs["cwd"] == str(tmp_path)

    def test_normalizes_crlf_in_description(self, tmp_path: Path) -> None:
        """CRLF line endings are normalized before writing the command file.

        Preserving \\r would corrupt the YAML block-literal on strict parsers.
        """
        (tmp_path / ".claude").mkdir()
        popen_mock = MagicMock()

        # Intercept Path.write_text to capture the rendered file body.
        captured: dict[str, str] = {}
        real_write_text = Path.write_text

        def _capture_write(self_p: Path, data: str, *a, **kw) -> int:
            if self_p.name.startswith("my-skill-eval-"):
                captured["body"] = data
            return real_write_text(self_p, data, *a, **kw)

        with patch("run_eval.subprocess.Popen", return_value=popen_mock), \
             patch("run_eval._parse_stream_for_trigger", return_value=False), \
             patch.object(Path, "write_text", _capture_write):
            run_single_query(
                "q", "my-skill", "line one\r\nline two",
                project_root=tmp_path, timeout=5,
            )
        assert "\r" not in captured["body"]
        assert "line one\n  line two" in captured["body"]

    def test_drops_claudecode_env(self, tmp_path: Path) -> None:
        """CLAUDECODE env is stripped before spawning child (avoids nesting guard)."""
        (tmp_path / ".claude").mkdir()
        popen_mock = MagicMock()

        with patch.dict("os.environ", {"CLAUDECODE": "1", "OTHER": "keep"}, clear=False), \
             patch("run_eval.subprocess.Popen", return_value=popen_mock) as mock_popen, \
             patch("run_eval._parse_stream_for_trigger", return_value=False):
            run_single_query(
                "q", "my-skill", "d",
                project_root=tmp_path, timeout=5,
            )

        env = mock_popen.call_args.kwargs["env"]
        assert "CLAUDECODE" not in env
        assert env.get("OTHER") == "keep"

    def test_returns_false_on_popen_error(self, tmp_path: Path) -> None:
        """claude binary missing -> False, never crash."""
        (tmp_path / ".claude").mkdir()
        with patch("run_eval.subprocess.Popen", side_effect=FileNotFoundError):
            result = run_single_query(
                "q", "my-skill", "d",
                project_root=tmp_path, timeout=5,
            )
        assert result is False
