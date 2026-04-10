"""Full test suite for skill_catchup.py."""

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from skill_catchup import (
    find_complex_tasks,
    format_report,
    get_sessions_sorted,
    main,
    resolve_project_dir,
    scan_session,
)


# ── helpers ──────────────────────────────────────────────


def _make_session(tmp_path: Path, lines: list[dict]) -> Path:
    """Write list of dicts as JSONL file, return path."""
    file = tmp_path / "session.jsonl"
    with open(file, "w") as f:
        for line in lines:
            f.write(json.dumps(line) + "\n")
    return file


# ── resolve_project_dir ───────────────────────────────


class TestResolveProjectDir:
    """Path -> Claude Code project storage dir conversion."""

    def test_absolute_path(self) -> None:
        result = resolve_project_dir("/Users/neo/my-project")
        expected = Path.home() / ".claude" / "projects" / "-Users-neo-my-project"
        assert result == expected

    def test_no_leading_slash(self) -> None:
        """path without leading / still gets - prefix."""
        result = resolve_project_dir("relative/path")
        expected = Path.home() / ".claude" / "projects" / "-relative-path"
        assert result == expected


# ── get_sessions_sorted ───────────────────────────────


class TestGetSessionsSorted:
    """JSONL file sorting and filtering."""

    def test_empty_dir(self, tmp_path: Path) -> None:
        assert get_sessions_sorted(tmp_path) == []

    def test_nonexistent_dir(self, tmp_path: Path) -> None:
        assert get_sessions_sorted(tmp_path / "nope") == []

    def test_sorts_by_mtime_descending(self, tmp_path: Path) -> None:
        """newest file first."""
        old = tmp_path / "old.jsonl"
        new = tmp_path / "new.jsonl"
        old.write_text("{}\n")
        new.write_text("{}\n")
        # set different mtime
        os.utime(old, (1000, 1000))
        os.utime(new, (2000, 2000))
        result = get_sessions_sorted(tmp_path)
        assert result == [new, old]

    def test_skips_agent_files(self, tmp_path: Path) -> None:
        """skip files prefixed with agent-."""
        normal = tmp_path / "session.jsonl"
        agent = tmp_path / "agent-abc.jsonl"
        normal.write_text("{}\n")
        agent.write_text("{}\n")
        result = get_sessions_sorted(tmp_path)
        assert result == [normal]


# ── scan_session ──────────────────────────────────────


class TestScanSession:
    """Single-pass JSONL scan: draft write detection + assistant tool sequence collection."""

    # draft write detection

    def test_no_draft_write(self, tmp_path: Path) -> None:
        session = _make_session(tmp_path, [
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "Read", "input": {"file_path": "/a/b.py"}},
            ]}},
        ])
        draft_line, _turns = scan_session(session)
        assert draft_line == -1

    def test_finds_write_tool(self, tmp_path: Path) -> None:
        session = _make_session(tmp_path, [
            {"type": "user", "message": "hello"},
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "Write", "input": {
                    "file_path": "/proj/.claude/skill_draft.md",
                }},
            ]}},
        ])
        draft_line, _turns = scan_session(session)
        assert draft_line == 1

    def test_finds_last_occurrence(self, tmp_path: Path) -> None:
        """Write first, Edit later -> return Edit line number."""
        session = _make_session(tmp_path, [
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "Write", "input": {
                    "file_path": "/x/skill_draft.md",
                }},
            ]}},
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "Edit", "input": {
                    "file_path": "/x/skill_draft.md",
                }},
            ]}},
        ])
        draft_line, _turns = scan_session(session)
        assert draft_line == 1

    def test_ignores_non_draft_writes(self, tmp_path: Path) -> None:
        """writing to other files does not count."""
        session = _make_session(tmp_path, [
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "Write", "input": {
                    "file_path": "/proj/other_file.md",
                }},
            ]}},
        ])
        draft_line, _turns = scan_session(session)
        assert draft_line == -1

    def test_malformed_json_with_write_keyword(self, tmp_path: Path) -> None:
        """line contains "Write" but JSON is corrupted -> skip."""
        file = tmp_path / "s.jsonl"
        file.write_text('{"name": "Write" broken json\n')
        draft_line, _turns = scan_session(file)
        assert draft_line == -1

    def test_message_not_dict(self, tmp_path: Path) -> None:
        """message is not dict but line contains "Write" keyword -> skip."""
        file = tmp_path / "s.jsonl"
        file.write_text('{"type": "assistant", "message": "Write"}\n')
        draft_line, _turns = scan_session(file)
        assert draft_line == -1

    def test_content_not_list(self, tmp_path: Path) -> None:
        """content is not list -> skip."""
        session = _make_session(tmp_path, [
            {"type": "assistant", "message": {"content": "Write"}},
        ])
        draft_line, _turns = scan_session(session)
        assert draft_line == -1

    def test_content_item_not_dict(self, tmp_path: Path) -> None:
        """content item is not dict -> skip."""
        session = _make_session(tmp_path, [
            {"type": "assistant", "message": {"content": ["Write"]}},
        ])
        draft_line, _turns = scan_session(session)
        assert draft_line == -1

    def test_tool_name_not_write_or_edit(self, tmp_path: Path) -> None:
        """tool name contains Write substring but not exact match -> skip."""
        session = _make_session(tmp_path, [
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "WriteAll", "input": {
                    "file_path": "/x/skill_draft.md",
                }},
            ]}},
        ])
        draft_line, _turns = scan_session(session)
        assert draft_line == -1

    def test_rejects_similar_filename(self, tmp_path: Path) -> None:
        """filename only suffix-matches (e.g. my_skill_draft.md) -> should not match."""
        session = _make_session(tmp_path, [
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "Write", "input": {
                    "file_path": "/x/my_skill_draft.md",
                }},
            ]}},
        ])
        draft_line, _turns = scan_session(session)
        assert draft_line == -1

    # assistant tool sequence collection + auto-filtering

    def test_filters_turns_after_draft(self, tmp_path: Path) -> None:
        """only assistant tool calls after draft write line are kept."""
        session = _make_session(tmp_path, [
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "Read", "input": {}},
            ]}},
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "Write", "input": {
                    "file_path": "/x/skill_draft.md",
                }},
            ]}},
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "Bash", "input": {}},
            ]}},
        ])
        draft_line, turns = scan_session(session)
        assert draft_line == 1
        assert len(turns) == 1
        assert turns[0]["tools"] == ["Bash"]

    def test_returns_all_when_no_draft(self, tmp_path: Path) -> None:
        """no draft write -> return all assistant tool calls."""
        session = _make_session(tmp_path, [
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "Read", "input": {}},
            ]}},
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "Write", "input": {}},
            ]}},
        ])
        draft_line, turns = scan_session(session)
        assert draft_line == -1
        assert len(turns) == 2

    def test_captures_text_summary(self, tmp_path: Path) -> None:
        """extract first 200 chars of text content as summary."""
        long_text = "A" * 300
        session = _make_session(tmp_path, [
            {"type": "assistant", "message": {"content": [
                {"type": "text", "text": long_text},
                {"type": "tool_use", "name": "Bash", "input": {}},
            ]}},
        ])
        _draft_line, turns = scan_session(session)
        assert len(turns) == 1
        assert turns[0]["summary"] == "A" * 200

    def test_skips_user_messages(self, tmp_path: Path) -> None:
        session = _make_session(tmp_path, [
            {"type": "user", "message": {"content": [
                {"type": "tool_use", "name": "Read", "input": {}},
            ]}},
        ])
        _draft_line, turns = scan_session(session)
        assert turns == []

    def test_skips_malformed_json(self, tmp_path: Path) -> None:
        """corrupted JSON lines silently skipped."""
        file = tmp_path / "bad.jsonl"
        file.write_text("not json\n")
        _draft_line, turns = scan_session(file)
        assert turns == []

    def test_assistant_message_not_dict(self, tmp_path: Path) -> None:
        """message is not dict -> skip."""
        session = _make_session(tmp_path, [
            {"type": "assistant", "message": "plain string"},
        ])
        _draft_line, turns = scan_session(session)
        assert turns == []

    def test_assistant_content_not_list(self, tmp_path: Path) -> None:
        """content is not list -> skip."""
        session = _make_session(tmp_path, [
            {"type": "assistant", "message": {"content": "not a list"}},
        ])
        _draft_line, turns = scan_session(session)
        assert turns == []

    def test_assistant_content_item_not_dict(self, tmp_path: Path) -> None:
        """content item is not dict -> skip."""
        session = _make_session(tmp_path, [
            {"type": "assistant", "message": {"content": [42, "str"]}},
        ])
        _draft_line, turns = scan_session(session)
        assert turns == []


# ── find_complex_tasks ────────────────────────────────


class TestFindComplexTasks:
    """Merge turns into task blocks, filter by threshold."""

    def test_empty_input(self) -> None:
        assert find_complex_tasks([]) == []

    def test_below_threshold(self) -> None:
        turns = [{"tools": ["Read"], "summary": "hi", "line": 0}]
        assert find_complex_tasks(turns) == []

    def test_above_threshold(self) -> None:
        """5+ tool calls -> merged into one task."""
        turns = [
            {"tools": ["Read", "Read"], "summary": "", "line": 0},
            {"tools": ["Write", "Bash", "Bash"], "summary": "deploying", "line": 5},
        ]
        result = find_complex_tasks(turns)
        assert len(result) == 1
        assert len(result[0]["tools"]) == 5
        assert result[0]["start_line"] == 0

    def test_uses_first_nonempty_summary(self) -> None:
        """summary takes first non-empty value."""
        turns = [
            {"tools": ["Read", "Read", "Read"], "summary": "", "line": 0},
            {"tools": ["Write", "Write"], "summary": "the real summary", "line": 5},
        ]
        result = find_complex_tasks(turns)
        assert result[0]["summary"] == "the real summary"


# ── format_report ─────────────────────────────────────


class TestFormatReport:
    """Report formatting."""

    def test_empty_tasks(self) -> None:
        assert format_report([]) == ""

    def test_includes_tool_counts(self) -> None:
        """includes tool counts and summary."""
        tasks = [{
            "tools": ["Read", "Read", "Write", "Bash", "Bash"],
            "summary": "doing stuff",
            "start_line": 10,
        }]
        report = format_report(tasks)
        assert "5 tool calls" in report
        assert "doing stuff" in report
        # verify aggregation format (Counter.most_common by freq desc)
        assert "Readx2" in report
        assert "Bashx2" in report
        assert "Writex1" in report
        # verify suggested command
        assert "/skill-forge create" in report

    def test_no_summary_skips_summary_line(self) -> None:
        """no summary -> Summary line omitted."""
        tasks = [{
            "tools": ["Read"] * 5,
            "summary": "",
            "start_line": 0,
        }]
        report = format_report(tasks)
        assert "Summary" not in report
        assert "5 tool calls" in report


# ── main ──────────────────────────────────────────────


class TestMain:
    """Integration tests for main()."""

    def test_no_args_exits(self, capsys: pytest.CaptureFixture[str]) -> None:
        """no args -> silent exit, no output, no exception."""
        with patch("skill_catchup.sys") as mock_sys:
            mock_sys.argv = ["skill_catchup.py"]
            main()
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == ""

    def test_no_sessions_silent(self, tmp_path: Path) -> None:
        """no session files -> silent exit."""
        with patch("skill_catchup.sys") as mock_sys:
            mock_sys.argv = ["skill_catchup.py", str(tmp_path / "nonexistent")]
            main()

    def test_single_session_silent(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """only 1 session (current) -> silent exit."""
        current = tmp_path / "current.jsonl"
        current.write_text("{}\n")
        with patch("skill_catchup.resolve_project_dir", return_value=tmp_path):
            with patch("skill_catchup.sys") as mock_sys:
                mock_sys.argv = ["skill_catchup.py", "/fake"]
                main()
        assert capsys.readouterr().out == ""

    def test_full_flow_with_complex_task(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """full flow: previous session has complex task -> output report."""
        # previous session (older mtime)
        lines = [
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "Read", "input": {}},
            ]}},
            {"type": "assistant", "message": {"content": [
                {"type": "text", "text": "working on migration"},
                {"type": "tool_use", "name": "Read", "input": {}},
                {"type": "tool_use", "name": "Write", "input": {}},
                {"type": "tool_use", "name": "Bash", "input": {}},
                {"type": "tool_use", "name": "Bash", "input": {}},
            ]}},
        ]
        previous_session = tmp_path / "previous.jsonl"
        with open(previous_session, "w") as f:
            for line in lines:
                f.write(json.dumps(line) + "\n")
        os.utime(previous_session, (1000, 1000))

        # current session (newer mtime -> sessions[0])
        current_session = tmp_path / "current.jsonl"
        current_session.write_text("{}\n")
        os.utime(current_session, (2000, 2000))

        with patch("skill_catchup.resolve_project_dir", return_value=tmp_path):
            with patch("skill_catchup.sys") as mock_sys:
                mock_sys.argv = ["skill_catchup.py", "/fake"]
                main()
        captured = capsys.readouterr()
        assert "tool calls" in captured.out
        assert "/skill-forge create" in captured.out
