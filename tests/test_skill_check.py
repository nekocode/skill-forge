"""Full test suite for skill_check.py."""

import json
from pathlib import Path

import pytest

from skill_check import (
    TOOL_CALL_THRESHOLD,
    check_draft_status,
    check_tool_calls,
    main,
)


# ── TestCheckDraftStatus ─────────────────────────────


class TestCheckDraftStatus:
    """Draft status check."""

    def test_no_draft(self, tmp_path: Path) -> None:
        """draft file missing -> None."""
        result = check_draft_status(tmp_path / "nonexistent.md")
        assert result is None

    def test_draft_in_progress(self, tmp_path: Path) -> None:
        """draft incomplete -> contains 'in progress'."""
        draft = tmp_path / "draft.md"
        draft.write_text(
            "# my-skill — IN PROGRESS\n"
            "## Phase 2: writing SKILL.md\n"
            "## Status\n"
            "pending\n"
        )
        result = check_draft_status(draft)
        assert result is not None
        assert "in progress" in result.lower()

    def test_draft_in_progress_shows_phase(self, tmp_path: Path) -> None:
        """incomplete draft (single-line) -> output contains current Phase line."""
        draft = tmp_path / "draft.md"
        draft.write_text(
            "# my-skill\n"
            "## Phase 1: codebase research\n"
            "## Status\n"
            "working\n"
        )
        result = check_draft_status(draft)
        assert result is not None
        assert "Phase 1" in result

    def test_draft_in_progress_two_line_phase(self, tmp_path: Path) -> None:
        """incomplete draft (two-line, DRAFT_TEMPLATE default format) -> output contains current Phase."""
        draft = tmp_path / "draft.md"
        draft.write_text(
            "# my-skill — IN PROGRESS\n"
            "## Phase\n"
            "Phase 1: codebase research\n"
            "## Status\n"
            "pending\n"
        )
        result = check_draft_status(draft)
        assert result is not None
        assert "Phase 1: codebase research" in result

    def test_draft_in_progress_no_phase(self, tmp_path: Path) -> None:
        """incomplete draft without Phase line -> no crash, still returns hint."""
        draft = tmp_path / "draft.md"
        draft.write_text("# my-skill\n## Status\nworking\n")
        result = check_draft_status(draft)
        assert result is not None
        assert "in progress" in result.lower()

    def test_draft_complete(self, tmp_path: Path) -> None:
        """draft complete -> contains 'complete' and 'evaluator'."""
        draft = tmp_path / "draft.md"
        draft.write_text(
            "# my-skill\n"
            "## Status\n"
            "complete\n"
        )
        result = check_draft_status(draft)
        assert result is not None
        assert "complete" in result.lower()
        assert "evaluator" in result.lower()

    def test_draft_done(self, tmp_path: Path) -> None:
        """draft done -> also triggers completion hint."""
        draft = tmp_path / "draft.md"
        draft.write_text("# my-skill\n## Status\nDone\n")
        result = check_draft_status(draft)
        assert result is not None
        assert "evaluator" in result.lower()

    def test_draft_complete_case_insensitive(self, tmp_path: Path) -> None:
        """case insensitive: COMPLETE also recognized."""
        draft = tmp_path / "draft.md"
        draft.write_text("# my-skill\n## Status\nCOMPLETE\n")
        result = check_draft_status(draft)
        assert result is not None
        assert "evaluator" in result.lower()

    def test_draft_false_positive_done_in_body(self, tmp_path: Path) -> None:
        """'done' appears outside Status section -> not falsely judged as complete."""
        draft = tmp_path / "draft.md"
        draft.write_text(
            "# my-skill\n"
            "## Phase 1: done with research\n"
            "## Status\n"
            "pending\n"
        )
        result = check_draft_status(draft)
        assert result is not None
        assert "in progress" in result.lower()


# ── TestCheckToolCalls ───────────────────────────────


class TestCheckToolCalls:
    """Tool call count check."""

    def test_no_state_file(self, tmp_path: Path) -> None:
        """state file missing -> None."""
        result = check_tool_calls(tmp_path / "nonexistent.json")
        assert result is None

    def test_below_threshold(self, tmp_path: Path) -> None:
        """tool calls below threshold -> None."""
        state = tmp_path / "state.json"
        state.write_text(json.dumps({"tool_calls": TOOL_CALL_THRESHOLD - 1}))
        result = check_tool_calls(state)
        assert result is None

    def test_above_threshold(self, tmp_path: Path) -> None:
        """tool calls reach threshold -> contains count."""
        state = tmp_path / "state.json"
        state.write_text(json.dumps({"tool_calls": 7}))
        result = check_tool_calls(state)
        assert result is not None
        assert "7 tool calls" in result

    def test_exact_threshold(self, tmp_path: Path) -> None:
        """exactly at threshold -> also triggers."""
        state = tmp_path / "state.json"
        state.write_text(json.dumps({"tool_calls": TOOL_CALL_THRESHOLD}))
        result = check_tool_calls(state)
        assert result is not None

    def test_malformed_json(self, tmp_path: Path) -> None:
        """corrupted JSON -> None."""
        state = tmp_path / "state.json"
        state.write_text("{broken json")
        result = check_tool_calls(state)
        assert result is None

    def test_missing_tool_calls_key(self, tmp_path: Path) -> None:
        """valid JSON but missing tool_calls key -> None (default 0 < threshold)."""
        state = tmp_path / "state.json"
        state.write_text(json.dumps({"other": "data"}))
        result = check_tool_calls(state)
        assert result is None

    def test_non_numeric_tool_calls(self, tmp_path: Path) -> None:
        """tool_calls not numeric -> None."""
        state = tmp_path / "state.json"
        state.write_text(json.dumps({"tool_calls": "not_a_number"}))
        result = check_tool_calls(state)
        assert result is None


# ── TestMain ─────────────────────────────────────────


class TestMain:
    """Integration tests for main()."""

    def test_draft_takes_priority(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """draft present -> prioritize draft status, ignore tool_calls."""
        draft = tmp_path / "draft.md"
        draft.write_text("# skill\n## Status\npending\n")
        state = tmp_path / "state.json"
        state.write_text(json.dumps({"tool_calls": 99}))
        main(draft_path=draft, state_path=state)
        captured = capsys.readouterr()
        assert "in progress" in captured.out.lower()
        # tool calls hint should not appear
        assert "tool calls" not in captured.out.lower()

    def test_falls_through_to_tool_calls(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """no draft -> check tool_calls."""
        state = tmp_path / "state.json"
        state.write_text(json.dumps({"tool_calls": 10}))
        main(draft_path=tmp_path / "no.md", state_path=state)
        captured = capsys.readouterr()
        assert "10 tool calls" in captured.out

    def test_nothing_to_report(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """no draft, no state -> no output."""
        main(
            draft_path=tmp_path / "no.md",
            state_path=tmp_path / "no.json",
        )
        captured = capsys.readouterr()
        assert captured.out == ""
