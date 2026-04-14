"""Full test suite for optimize_description.py."""

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

import optimize_description

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
    RoundRecord,
    OptState,
    load_opt_state,
    save_opt_state,
    classify_failures,
    EVALUATE_TEMPLATE,
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

    @patch("optimize_description.call_claude")
    def test_prompt_includes_undertrigger_bias(self, mock_claude: object) -> None:
        """DSPy: prompt contains undertrigger bias instruction."""
        mock_claude.return_value = "YES"
        evaluate_single("desc", "query", runs=1)
        prompt_used = mock_claude.call_args[0][0]
        assert "Undertriggering is safer" in prompt_used

    @patch("optimize_description.call_claude")
    def test_prompt_includes_complex_task_context(self, mock_claude: object) -> None:
        """DSPy: prompt explains skills only trigger for multi-step workflows."""
        mock_claude.return_value = "NO"
        evaluate_single("desc", "query", runs=1)
        prompt_used = mock_claude.call_args[0][0]
        assert "multi-step workflows" in prompt_used


# ── TestCallClaude ──────────────────────────────────


class TestCallClaude:
    """claude CLI subprocess wrapper with single retry."""

    @pytest.fixture(autouse=True)
    def _no_sleep(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Skip retry delay in call_claude."""
        monkeypatch.setattr(optimize_description.time, "sleep", lambda _: None)

    @patch("shared.subprocess.run")
    def test_happy_path(self, mock_run: object) -> None:
        """normal return -> stdout stripped, no retry."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=["claude"], returncode=0, stdout="YES\n", stderr=""
        )
        result = call_claude("test prompt")
        assert result == "YES"
        assert mock_run.call_count == 1

    @patch("shared.subprocess.run")
    def test_retry_on_empty(self, mock_run: object) -> None:
        """first call fails, retry succeeds."""
        mock_run.side_effect = [
            subprocess.CompletedProcess(args=["claude"], returncode=1, stdout="", stderr=""),
            subprocess.CompletedProcess(args=["claude"], returncode=0, stdout="OK\n", stderr=""),
        ]
        result = call_claude("test prompt")
        assert result == "OK"
        assert mock_run.call_count == 2

    @patch("shared.subprocess.run")
    def test_nonzero_returncode_both_fail(self, mock_run: object) -> None:
        """both attempts fail -> ""."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=["claude"], returncode=1, stdout="error msg", stderr=""
        )
        result = call_claude("test prompt")
        assert result == ""
        assert mock_run.call_count == 2

    @patch("shared.subprocess.run")
    def test_timeout(self, mock_run: object) -> None:
        """timeout on both attempts -> ""."""
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="claude", timeout=60)
        result = call_claude("test prompt")
        assert result == ""

    @patch("shared.subprocess.run")
    def test_file_not_found(self, mock_run: object) -> None:
        """claude not installed -> ""."""
        mock_run.side_effect = FileNotFoundError("claude not found")
        result = call_claude("test prompt")
        assert result == ""


# ── TestClassifyFailures ────────────────────────────


class TestClassifyFailures:
    """FP/FN failure classification."""

    def test_empty_list(self) -> None:
        """no failures -> ([], [])."""
        fps, fns = classify_failures([])
        assert fps == []
        assert fns == []

    def test_all_false_positives(self) -> None:
        """should_trigger=False -> all FP."""
        failures = [
            {"query": "q1", "should_trigger": False, "got": True},
            {"query": "q2", "should_trigger": False, "got": True},
        ]
        fps, fns = classify_failures(failures)
        assert len(fps) == 2
        assert len(fns) == 0

    def test_all_false_negatives(self) -> None:
        """should_trigger=True -> all FN."""
        failures = [
            {"query": "q1", "should_trigger": True, "got": False},
        ]
        fps, fns = classify_failures(failures)
        assert len(fps) == 0
        assert len(fns) == 1

    def test_mixed(self) -> None:
        """mixed failures -> correct split."""
        failures = [
            {"query": "q1", "should_trigger": True, "got": False},
            {"query": "q2", "should_trigger": False, "got": True},
            {"query": "q3", "should_trigger": True, "got": False},
        ]
        fps, fns = classify_failures(failures)
        assert len(fps) == 1
        assert len(fns) == 2


# ── TestOptState ────────────────────────────────────


class TestOptState:
    """OptState persistence."""

    def test_save_creates_directory(self, tmp_path: Path) -> None:
        """auto-creates .opt/ directory."""
        state_path = tmp_path / "deep" / "nested" / "opt_state.json"
        state = OptState(
            skill_name="test",
            best_score=0.8,
            best_description="desc",
            current_round=1,
            converged=False,
            rounds=[],
        )
        save_opt_state(state, state_path)
        assert state_path.exists()

    def test_save_and_load_roundtrip(self, tmp_path: Path) -> None:
        """save then load -> identical state."""
        state_path = tmp_path / "opt_state.json"
        record = RoundRecord(
            round=1,
            description="test desc",
            train_score=0.75,
            test_score=0.8,
            false_positive_count=2,
            false_negative_count=1,
        )
        original = OptState(
            skill_name="my-skill",
            best_score=0.8,
            best_description="best desc",
            current_round=1,
            converged=False,
            rounds=[record],
        )
        save_opt_state(original, state_path)
        loaded = load_opt_state(state_path)
        assert loaded is not None
        assert loaded.skill_name == "my-skill"
        assert loaded.best_score == 0.8
        assert loaded.converged is False
        assert len(loaded.rounds) == 1
        assert loaded.rounds[0].false_positive_count == 2

    def test_load_missing_returns_none(self, tmp_path: Path) -> None:
        """missing file -> None."""
        result = load_opt_state(tmp_path / "nonexistent.json")
        assert result is None

    def test_load_corrupt_returns_none(self, tmp_path: Path) -> None:
        """corrupt JSON -> None."""
        state_path = tmp_path / "opt_state.json"
        state_path.write_text("{broken")
        result = load_opt_state(state_path)
        assert result is None

    def test_load_wrong_schema_returns_none(self, tmp_path: Path) -> None:
        """valid JSON but missing required keys -> None."""
        state_path = tmp_path / "opt_state.json"
        state_path.write_text('{"unrelated": true}')
        result = load_opt_state(state_path)
        assert result is None

    def test_load_partial_keys_returns_none(self, tmp_path: Path) -> None:
        """JSON with skill_name but missing other keys -> None."""
        state_path = tmp_path / "opt_state.json"
        state_path.write_text('{"skill_name": "x"}')
        result = load_opt_state(state_path)
        assert result is None


# ── TestPromptTemplates ─────────────────────────────


class TestPromptTemplates:
    """Prompt template constants used by evaluate/improve."""

    def test_evaluate_template_has_placeholders(self) -> None:
        """template contains {description} and {query} placeholders."""
        assert "{description}" in EVALUATE_TEMPLATE
        assert "{query}" in EVALUATE_TEMPLATE

    @patch("optimize_description.call_claude")
    def test_evaluate_formats_template(self, mock_claude: object) -> None:
        """evaluate_single formats template with description and query."""
        mock_claude.return_value = "YES"
        evaluate_single("my-desc", "my-query", runs=1)
        prompt_used = mock_claude.call_args[0][0]
        assert "my-desc" in prompt_used
        assert "my-query" in prompt_used


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

    @patch("optimize_description.call_claude")
    def test_fn_prompt_mentions_trigger_patterns(self, mock_claude: object) -> None:
        """DSPy: FN failures -> prompt contains trigger pattern guidance."""
        mock_claude.return_value = "Better desc"
        failures = [{"query": "q1", "should_trigger": True, "got": False}]
        improve_description("Old desc", failures)
        prompt_used = mock_claude.call_args[0][0]
        assert "trigger patterns" in prompt_used
        assert "False negatives" in prompt_used

    @patch("optimize_description.call_claude")
    def test_fp_prompt_mentions_do_not_use(self, mock_claude: object) -> None:
        """DSPy: FP failures -> prompt contains DO NOT use guidance."""
        mock_claude.return_value = "Better desc"
        failures = [{"query": "q1", "should_trigger": False, "got": True}]
        improve_description("Old desc", failures)
        prompt_used = mock_claude.call_args[0][0]
        assert "Do NOT use" in prompt_used or "false positives" in prompt_used.lower()
        assert "False positives" in prompt_used

    @patch("optimize_description.call_claude")
    def test_mixed_failures_both_directions(self, mock_claude: object) -> None:
        """DSPy: mixed FP+FN -> prompt contains both directions."""
        mock_claude.return_value = "Better desc"
        failures = [
            {"query": "q1", "should_trigger": True, "got": False},
            {"query": "q2", "should_trigger": False, "got": True},
        ]
        improve_description("Old desc", failures)
        prompt_used = mock_claude.call_args[0][0]
        assert "False negatives" in prompt_used
        assert "False positives" in prompt_used


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

    @patch("optimize_description.improve_description")
    @patch("optimize_description.evaluate_set")
    def test_result_includes_rounds_and_converged(
        self, mock_eval_set: object, mock_improve: object
    ) -> None:
        """DSPy: result dict has rounds list and converged bool."""
        mock_eval_set.side_effect = [
            (1.0, []),   # iter1 train
            (0.9, []),   # iter1 test
        ]
        train_set = [{"query": "t1", "should_trigger": True}]
        test_set = [{"query": "t2", "should_trigger": True}]

        result = run_optimization("desc", train_set, test_set, max_iterations=5)
        assert "rounds" in result
        assert "converged" in result
        assert isinstance(result["rounds"], list)
        assert len(result["rounds"]) == 1
        assert result["converged"] is True

    @patch("optimize_description.improve_description")
    @patch("optimize_description.evaluate_set")
    def test_rounds_track_fp_fn_counts(
        self, mock_eval_set: object, mock_improve: object
    ) -> None:
        """DSPy: round records contain FP/FN counts from train failures."""
        train_failures = [
            {"query": "fp1", "should_trigger": False, "got": True},
            {"query": "fn1", "should_trigger": True, "got": False},
            {"query": "fn2", "should_trigger": True, "got": False},
        ]
        mock_eval_set.side_effect = [
            (0.5, train_failures),   # iter1 train
            (0.6, []),               # iter1 test
            (1.0, []),               # iter2 train
            (0.8, []),               # iter2 test
        ]
        mock_improve.return_value = "improved"

        train_set = [{"query": "t1", "should_trigger": True}]
        test_set = [{"query": "t2", "should_trigger": True}]

        result = run_optimization("desc", train_set, test_set, max_iterations=5)
        assert len(result["rounds"]) == 2
        # first round has the failures
        assert result["rounds"][0]["false_positive_count"] == 1
        assert result["rounds"][0]["false_negative_count"] == 2
        # second round is perfect
        assert result["rounds"][1]["false_positive_count"] == 0
        assert result["rounds"][1]["false_negative_count"] == 0

    @patch("optimize_description.improve_description")
    @patch("optimize_description.evaluate_set")
    def test_saves_state_when_path_given(
        self, mock_eval_set: object, mock_improve: object, tmp_path: Path
    ) -> None:
        """DSPy: state_path provided -> opt_state.json written."""
        mock_eval_set.side_effect = [
            (1.0, []),   # iter1 train
            (0.9, []),   # iter1 test
        ]
        train_set = [{"query": "t1", "should_trigger": True}]
        test_set = [{"query": "t2", "should_trigger": True}]
        state_path = tmp_path / ".opt" / "opt_state.json"

        run_optimization(
            "desc", train_set, test_set,
            max_iterations=5, state_path=state_path, skill_name="test-skill",
        )
        assert state_path.exists()
        data = json.loads(state_path.read_text())
        assert data["skill_name"] == "test-skill"
        assert data["converged"] is True
        assert len(data["rounds"]) == 1

    @patch("optimize_description.improve_description")
    @patch("optimize_description.evaluate_set")
    def test_no_state_save_when_path_none(
        self, mock_eval_set: object, mock_improve: object, tmp_path: Path
    ) -> None:
        """DSPy: state_path=None -> no file side-effects."""
        mock_eval_set.side_effect = [
            (1.0, []),
            (0.9, []),
        ]
        train_set = [{"query": "t1", "should_trigger": True}]
        test_set = [{"query": "t2", "should_trigger": True}]

        run_optimization("desc", train_set, test_set, max_iterations=5)
        # no .opt directory should exist under tmp_path
        assert not (tmp_path / ".opt").exists()


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
            "rounds": [],
            "converged": False,
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
