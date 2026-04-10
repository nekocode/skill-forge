"""Full test suite for optimize_description.py."""

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from optimize_description import (
    load_skill,
    load_evals,
    split_train_test,
    call_claude,
    evaluate_single,
    evaluate_set,
    improve_description,
    run_optimization,
    main,
)


# ── helpers ──────────────────────────────────────────────


def _write_skill(tmp_path: Path, content: str) -> Path:
    """Write SKILL.md and return path."""
    skill_file = tmp_path / "SKILL.md"
    skill_file.write_text(content)
    return skill_file


def _write_evals(tmp_path: Path, evals: list[dict]) -> Path:
    """Write trigger_evals.json and return path."""
    eval_file = tmp_path / "trigger_evals.json"
    eval_file.write_text(json.dumps(evals))
    return eval_file


# ── TestLoadSkill ────────────────────────────────────


class TestLoadSkill:
    """SKILL.md parsing."""

    def test_parses_description(self, tmp_path: Path) -> None:
        """single-line description parsed correctly."""
        skill_file = _write_skill(tmp_path, (
            "---\n"
            "name: my-skill\n"
            "description: A short description here\n"
            "---\n"
            "# Content\n"
        ))
        name, description = load_skill(skill_file)
        assert name == "my-skill"
        assert description == "A short description here"

    def test_multiline_description(self, tmp_path: Path) -> None:
        """multiline folded description (> format) parsed correctly."""
        skill_file = _write_skill(tmp_path, (
            "---\n"
            "name: deploy-tool\n"
            "description: >\n"
            "  Line one of description.\n"
            "  Line two of description.\n"
            "---\n"
            "# Content\n"
        ))
        name, description = load_skill(skill_file)
        assert name == "deploy-tool"
        assert "Line one" in description
        assert "Line two" in description

    def test_missing_file(self, tmp_path: Path) -> None:
        """file missing -> ("", "")."""
        name, description = load_skill(tmp_path / "nonexistent.md")
        assert name == ""
        assert description == ""

    def test_no_frontmatter(self, tmp_path: Path) -> None:
        """no --- block -> ("", "")."""
        skill_file = _write_skill(tmp_path, "# Just markdown\nNo frontmatter here\n")
        name, description = load_skill(skill_file)
        assert name == ""
        assert description == ""

    def test_no_description_in_frontmatter(self, tmp_path: Path) -> None:
        """frontmatter has name but no description -> (name, "")."""
        skill_file = _write_skill(tmp_path, "---\nname: x\n---\n")
        name, description = load_skill(skill_file)
        assert name == "x"
        assert description == ""

    def test_directory_with_skill_md(self, tmp_path: Path) -> None:
        """directory passed -> auto-find SKILL.md inside."""
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\n"
            "name: dir-skill\n"
            "description: From directory\n"
            "---\n"
        )
        name, description = load_skill(skill_dir)
        assert name == "dir-skill"
        assert description == "From directory"


# ── TestLoadEvals ────────────────────────────────────


class TestLoadEvals:
    """Trigger eval data loading."""

    def test_loads_valid_json(self, tmp_path: Path) -> None:
        """valid JSON array loads normally."""
        evals = [
            {"query": "do something", "should_trigger": True},
            {"query": "skip this", "should_trigger": False},
        ]
        eval_file = _write_evals(tmp_path, evals)
        result = load_evals(eval_file)
        assert len(result) == 2
        assert result[0]["query"] == "do something"

    def test_missing_file(self, tmp_path: Path) -> None:
        """file missing -> []."""
        result = load_evals(tmp_path / "nonexistent.json")
        assert result == []

    def test_invalid_json(self, tmp_path: Path) -> None:
        """invalid JSON -> []."""
        eval_file = tmp_path / "broken.json"
        eval_file.write_text("{broken")
        result = load_evals(eval_file)
        assert result == []

    def test_json_not_array(self, tmp_path: Path) -> None:
        """JSON object not array -> []."""
        eval_file = tmp_path / "object.json"
        eval_file.write_text('{"key": "val"}')
        result = load_evals(eval_file)
        assert result == []


# ── TestSplitTrainTest ───────────────────────────────


class TestSplitTrainTest:
    """Train/test split."""

    def test_split_ratio(self) -> None:
        """20 items -> 12 train + 8 test."""
        evals = [{"query": f"q{i}", "should_trigger": i % 2 == 0} for i in range(20)]
        train, test = split_train_test(evals, ratio=0.6, seed=42)
        assert len(train) == 12
        assert len(test) == 8

    def test_deterministic(self) -> None:
        """same seed -> same split."""
        evals = [{"query": f"q{i}", "should_trigger": True} for i in range(20)]
        train1, test1 = split_train_test(evals, seed=42)
        train2, test2 = split_train_test(evals, seed=42)
        assert train1 == train2
        assert test1 == test2

    def test_empty_input(self) -> None:
        """empty list -> ([], [])."""
        train, test = split_train_test([])
        assert train == []
        assert test == []


# ── TestEvaluateSingle ───────────────────────────────


class TestEvaluateSingle:
    """Single query trigger evaluation (majority vote)."""

    @patch("optimize_description.call_claude")
    def test_majority_yes(self, mock_claude: object) -> None:
        """2/3 YES -> True."""
        mock_claude.side_effect = ["YES", "YES", "NO"]
        result = evaluate_single("desc", "query", runs=3)
        assert result is True

    @patch("optimize_description.call_claude")
    def test_majority_no(self, mock_claude: object) -> None:
        """2/3 NO -> False."""
        mock_claude.side_effect = ["NO", "NO", "YES"]
        result = evaluate_single("desc", "query", runs=3)
        assert result is False

    @patch("optimize_description.call_claude")
    def test_all_yes(self, mock_claude: object) -> None:
        """all YES -> True."""
        mock_claude.side_effect = ["YES", "YES", "YES"]
        result = evaluate_single("desc", "query", runs=3)
        assert result is True

    @patch("optimize_description.call_claude")
    def test_handles_unexpected_output(self, mock_claude: object) -> None:
        """non-YES output (maybe/empty) -> counted as NO."""
        mock_claude.side_effect = ["maybe", "", "NO"]
        result = evaluate_single("desc", "query", runs=3)
        assert result is False


# ── TestCallClaude ──────────────────────────────────


class TestCallClaude:
    """claude CLI subprocess wrapper."""

    @patch("shared.subprocess.run")
    def test_happy_path(self, mock_run: object) -> None:
        """normal return -> stdout stripped."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=["claude"], returncode=0, stdout="YES\n", stderr=""
        )
        result = call_claude("test prompt")
        assert result == "YES"

    @patch("shared.subprocess.run")
    def test_nonzero_returncode(self, mock_run: object) -> None:
        """returncode != 0 -> ""."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=["claude"], returncode=1, stdout="error msg", stderr=""
        )
        result = call_claude("test prompt")
        assert result == ""

    @patch("shared.subprocess.run")
    def test_timeout(self, mock_run: object) -> None:
        """timeout -> ""."""
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="claude", timeout=30)
        result = call_claude("test prompt")
        assert result == ""

    @patch("shared.subprocess.run")
    def test_file_not_found(self, mock_run: object) -> None:
        """claude not installed -> ""."""
        mock_run.side_effect = FileNotFoundError("claude not found")
        result = call_claude("test prompt")
        assert result == ""


# ── TestEvaluateSet ──────────────────────────────────


class TestEvaluateSet:
    """Eval set overall scoring."""

    def test_empty_set(self) -> None:
        """empty eval set -> (1.0, [])."""
        score, failures = evaluate_set("desc", [])
        assert score == 1.0
        assert failures == []

    @patch("optimize_description.evaluate_single")
    def test_false_positive(self, mock_eval: object) -> None:
        """should_trigger=False but triggered -> failure contains should_trigger=False."""
        mock_eval.return_value = True
        eval_set = [{"query": "unrelated query", "should_trigger": False}]
        score, failures = evaluate_set("desc", eval_set)
        assert score == 0.0
        assert len(failures) == 1
        assert failures[0]["should_trigger"] is False
        assert failures[0]["got"] is True

    @patch("optimize_description.evaluate_single")
    def test_perfect_score(self, mock_eval: object) -> None:
        """all correct -> (1.0, [])."""
        # should_trigger=True → triggered=True, should_trigger=False → triggered=False
        mock_eval.side_effect = [True, False]
        eval_set = [
            {"query": "q1", "should_trigger": True},
            {"query": "q2", "should_trigger": False},
        ]
        score, failures = evaluate_set("desc", eval_set)
        assert score == 1.0
        assert failures == []

    @patch("optimize_description.evaluate_single")
    def test_all_wrong(self, mock_eval: object) -> None:
        """all wrong -> (0.0, 2 failures)."""
        mock_eval.side_effect = [False, True]
        eval_set = [
            {"query": "q1", "should_trigger": True},
            {"query": "q2", "should_trigger": False},
        ]
        score, failures = evaluate_set("desc", eval_set)
        assert score == 0.0
        assert len(failures) == 2

    @patch("optimize_description.evaluate_single")
    def test_mixed_results(self, mock_eval: object) -> None:
        """should_trigger=True correct + should_trigger=False wrong -> (0.5, 1 failure)."""
        mock_eval.side_effect = [True, True]
        eval_set = [
            {"query": "q1", "should_trigger": True},
            {"query": "q2", "should_trigger": False},
        ]
        score, failures = evaluate_set("desc", eval_set)
        assert score == 0.5
        assert len(failures) == 1
        assert failures[0]["query"] == "q2"


# ── TestImproveDescription ───────────────────────────


class TestImproveDescription:
    """Improve description based on failure cases."""

    @patch("optimize_description.call_claude")
    def test_returns_improved_text(self, mock_claude: object) -> None:
        """failures present -> call claude, return improved version."""
        mock_claude.return_value = "Better description text"
        failures = [{"query": "q1", "should_trigger": True, "got": False}]
        result = improve_description("Old desc", failures)
        assert result == "Better description text"
        mock_claude.assert_called_once()

    @patch("optimize_description.call_claude")
    def test_empty_failures(self, mock_claude: object) -> None:
        """no failures -> return original description, skip claude call."""
        result = improve_description("Original desc", [])
        assert result == "Original desc"
        mock_claude.assert_not_called()

    @patch("optimize_description.call_claude")
    def test_too_long_result_returns_original(self, mock_claude: object) -> None:
        """claude returns >300 chars -> fall back to original."""
        mock_claude.return_value = "X" * 301
        failures = [{"query": "q1", "should_trigger": True, "got": False}]
        result = improve_description("Original", failures)
        assert result == "Original"

    @patch("optimize_description.call_claude")
    def test_empty_result_returns_original(self, mock_claude: object) -> None:
        """claude returns empty -> fall back to original."""
        mock_claude.return_value = ""
        failures = [{"query": "q1", "should_trigger": True, "got": False}]
        result = improve_description("Original", failures)
        assert result == "Original"


# ── TestRunOptimization ──────────────────────────────


class TestRunOptimization:
    """Optimization loop."""

    @patch("optimize_description.improve_description")
    @patch("optimize_description.evaluate_set")
    def test_returns_best_by_test_score(
        self, mock_eval_set: object, mock_improve: object
    ) -> None:
        """iter1 test=0.7 > iter2 test=0.6 -> best is iter1's description."""
        # iter1: train eval -> (0.8, [failure]), test eval -> (0.7, [])
        # iter2: train eval -> (0.9, []),         test eval -> (0.6, [])
        mock_eval_set.side_effect = [
            # iter1 train
            (0.8, [{"query": "q", "should_trigger": True, "got": False}]),
            # iter1 test
            (0.7, []),
            # iter2 train
            (0.9, [{"query": "q", "should_trigger": True, "got": False}]),
            # iter2 test
            (0.6, []),
            # iter3 train
            (1.0, []),
            # iter3 test (perfect train -> early stop but still eval test)
            (0.5, []),
        ]
        mock_improve.side_effect = ["improved-v1", "improved-v2"]

        train_set = [{"query": "t1", "should_trigger": True}]
        test_set = [{"query": "t2", "should_trigger": True}]

        result = run_optimization("original", train_set, test_set, max_iterations=5)
        assert result["best_description"] == "original"
        assert result["best_test_score"] == 0.7

    @patch("optimize_description.improve_description")
    @patch("optimize_description.evaluate_set")
    def test_early_stop_on_perfect_train(
        self, mock_eval_set: object, mock_improve: object
    ) -> None:
        """train=1.0 -> 1 iteration, improve not called."""
        mock_eval_set.side_effect = [
            (1.0, []),   # iter1 train (perfect)
            (0.9, []),   # iter1 test
        ]

        train_set = [{"query": "t1", "should_trigger": True}]
        test_set = [{"query": "t2", "should_trigger": True}]

        result = run_optimization("desc", train_set, test_set, max_iterations=5)
        assert result["iterations"] == 1
        mock_improve.assert_not_called()
        assert result["best_test_score"] == 0.9


# ── TestMain ─────────────────────────────────────────


class TestMain:
    """Entry point."""

    @patch("optimize_description.run_optimization")
    @patch("optimize_description.load_evals")
    @patch("optimize_description.load_skill")
    def test_full_flow(
        self,
        mock_load_skill: object,
        mock_load_evals: object,
        mock_run: object,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """normal flow -> stdout outputs JSON."""
        mock_load_skill.return_value = ("my-skill", "Original desc")
        mock_load_evals.return_value = [
            {"query": f"q{i}", "should_trigger": i % 2 == 0}
            for i in range(20)
        ]
        mock_run.return_value = {
            "best_description": "Better desc",
            "best_test_score": 0.85,
            "iterations": 3,
        }
        with patch("sys.argv", [
            "optimize_description.py",
            "--skill-path", "/fake/skill",
            "--eval-set", "/fake/evals.json",
            "--max-iterations", "5",
        ]):
            main()
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["skill_name"] == "my-skill"
        assert output["original_description"] == "Original desc"
        assert output["best_description"] == "Better desc"
        assert output["best_test_score"] == 0.85

    @patch("optimize_description.load_skill")
    def test_exits_on_bad_skill(
        self,
        mock_load_skill: object,
    ) -> None:
        """skill load failure -> exit(1)."""
        mock_load_skill.return_value = ("", "")
        with patch("sys.argv", [
            "optimize_description.py",
            "--skill-path", "/fake/skill",
            "--eval-set", "/fake/evals.json",
        ]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1

    @patch("optimize_description.load_evals")
    @patch("optimize_description.load_skill")
    def test_exits_on_bad_evals(
        self,
        mock_load_skill: object,
        mock_load_evals: object,
    ) -> None:
        """evals load failure -> exit(1)."""
        mock_load_skill.return_value = ("my-skill", "desc")
        mock_load_evals.return_value = []
        with patch("sys.argv", [
            "optimize_description.py",
            "--skill-path", "/fake/skill",
            "--eval-set", "/fake/evals.json",
        ]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1
