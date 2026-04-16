"""Full test suite for self_evolve.py."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

import self_evolve


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skip time.sleep in self_evolve to keep tests fast."""
    monkeypatch.setattr(self_evolve.time, "sleep", lambda _: None)

from self_evolve import (
    PromptEntry,
    build_catalog,
    collect_eval_data,
    score_evaluator_prompt,
    score_guidance_prompt,
    score_instruction_quality,
    score_prompt,
    generate_variants,
    evolve_prompt,
    extract_markdown_section,
    replace_markdown_section,
    apply_results,
    _format_python_constant,
    main,
)


# ── helpers ─────────────────────────────────────────


def _write_eval_file(path: Path, evals: list[dict]) -> None:
    """Write a trigger_evals.json file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(evals))


def _make_eval_data() -> list[dict]:
    """Standard eval data for tests."""
    return [
        {"query": "deploy the app to staging", "should_trigger": True},
        {"query": "read this file", "should_trigger": False},
        {"query": "set up CI/CD pipeline with tests", "should_trigger": True},
        {"query": "what time is it", "should_trigger": False},
    ]


# ── TestCollectEvalData ─────────────────────────────


class TestCollectEvalData:
    """Eval data collection from skills directory."""

    def test_finds_eval_files(self, tmp_path: Path) -> None:
        """discovers trigger_evals.json in subdirectories."""
        _write_eval_file(tmp_path / "skill" / "trigger_evals.json",
                         [{"query": "q1", "should_trigger": True}])
        result = collect_eval_data(tmp_path)
        assert len(result) == 1

    def test_merges_multiple_files(self, tmp_path: Path) -> None:
        """merges eval data from multiple skills."""
        _write_eval_file(tmp_path / "a" / "trigger_evals.json",
                         [{"query": "a1", "should_trigger": True}])
        _write_eval_file(tmp_path / "b" / "trigger_evals.json",
                         [{"query": "b1", "should_trigger": False}])
        assert len(collect_eval_data(tmp_path)) == 2

    def test_skips_corrupt_files(self, tmp_path: Path) -> None:
        """corrupt JSON skipped silently."""
        (tmp_path / "bad").mkdir()
        (tmp_path / "bad" / "trigger_evals.json").write_text("{broken")
        _write_eval_file(tmp_path / "good" / "trigger_evals.json",
                         [{"query": "g1", "should_trigger": True}])
        assert len(collect_eval_data(tmp_path)) == 1

    def test_missing_dir(self, tmp_path: Path) -> None:
        """nonexistent directory -> empty list."""
        assert collect_eval_data(tmp_path / "nope") == []

    def test_empty_dir(self, tmp_path: Path) -> None:
        """directory with no eval files -> empty list."""
        assert collect_eval_data(tmp_path) == []


# ── TestExtractMarkdownSection ──────────────────────


class TestExtractMarkdownSection:
    """Markdown section extraction by heading."""

    def test_extracts_section(self) -> None:
        """extracts body between heading and next same-level heading."""
        content = "## Intro\n\nHello\n\n## Next\n\nWorld\n"
        assert extract_markdown_section(content, "Intro") == "Hello"

    def test_extracts_subsection(self) -> None:
        """### heading extracted until next ### or higher."""
        content = "### Sub\n\nBody here\n\n### Other\n\nOther body\n"
        assert extract_markdown_section(content, "Sub") == "Body here"

    def test_last_section(self) -> None:
        """last section (no following heading) extracts to end."""
        content = "## Only\n\nAll the rest\n"
        assert extract_markdown_section(content, "Only") == "All the rest"

    def test_heading_not_found(self) -> None:
        """missing heading -> empty string."""
        assert extract_markdown_section("## Other\n\nBody\n", "Missing") == ""

    def test_multiline_body(self) -> None:
        """multi-line section body preserved."""
        content = "### Rules\n\n1. First\n2. Second\n3. Third\n\n### Next\n"
        body = extract_markdown_section(content, "Rules")
        assert "1. First" in body
        assert "3. Third" in body


# ── TestReplaceMarkdownSection ──────────────────────


class TestReplaceMarkdownSection:
    """Markdown section replacement."""

    def test_replaces_body(self) -> None:
        """replaces section body, keeps heading and next section."""
        content = "## Intro\n\nOld body\n\n## Next\n\nKept\n"
        result = replace_markdown_section(content, "Intro", "New body")
        assert "New body" in result
        assert "Old body" not in result
        assert "## Next" in result
        assert "Kept" in result

    def test_heading_not_found(self) -> None:
        """missing heading -> content unchanged."""
        content = "## Other\n\nBody\n"
        assert replace_markdown_section(content, "Missing", "X") == content


# ── TestBuildCatalog ────────────────────────────────


class TestBuildCatalog:
    """Catalog construction from Python + SKILL.md."""

    def test_includes_python_constants(self, tmp_path: Path) -> None:
        """always includes 3 Python constant entries."""
        catalog = build_catalog(tmp_path / "nonexistent.md")
        py_entries = [e for e in catalog if e.source_type == "python_constant"]
        assert len(py_entries) == 3

    def test_includes_skill_md_sections(self, tmp_path: Path) -> None:
        """SKILL.md sections added when file exists with matching headings."""
        md = tmp_path / "SKILL.md"
        md.write_text(
            "### Description writing rules (directly affects triggering accuracy)\n\n"
            "Rule content here\n\n"
            "### Step 3b: triggering improvement (eval-driven)\n\n"
            "Step content here\n\n"
            "### Other\n"
        )
        catalog = build_catalog(md)
        md_entries = [e for e in catalog if e.source_type == "markdown_section"]
        assert len(md_entries) == 2


# ── TestScoreEvaluatorPrompt ────────────────────────


class TestScoreEvaluatorPrompt:
    """Evaluator prompt accuracy scoring."""

    @patch("self_evolve.call_claude")
    def test_perfect_accuracy(self, mock_claude: object) -> None:
        """all correct -> 1.0."""
        mock_claude.side_effect = ["YES", "NO", "YES", "NO"]
        assert score_evaluator_prompt("t {description} {query}", _make_eval_data()) == 1.0

    @patch("self_evolve.call_claude")
    def test_empty_data(self, mock_claude: object) -> None:
        """no eval data -> 0.0."""
        assert score_evaluator_prompt("t {description} {query}", []) == 0.0


# ── TestScoreGuidancePrompt ─────────────────────────


class TestScoreGuidancePrompt:
    """Guidance prompt quality scoring."""

    @patch("self_evolve.call_claude")
    def test_fn_good_output(self, mock_claude: object) -> None:
        """FN guidance produces broadened description -> high score."""
        mock_claude.return_value = (
            "Use when deploying code to production or staging, "
            "even if user just says 'push to prod'"
        )
        assert score_guidance_prompt("guidance", "improve_fn", _make_eval_data()) >= 0.75

    @patch("self_evolve.call_claude")
    def test_fp_good_output(self, mock_claude: object) -> None:
        """FP guidance produces narrowed description -> high score."""
        mock_claude.return_value = "Use when deploying multi-step builds. Do not use for reads."
        assert score_guidance_prompt("guidance", "improve_fp", _make_eval_data()) >= 0.75

    @patch("self_evolve.call_claude")
    def test_empty_output(self, mock_claude: object) -> None:
        """empty response -> 0.0."""
        mock_claude.return_value = ""
        assert score_guidance_prompt("guidance", "improve_fn", _make_eval_data()) == 0.0

    @patch("self_evolve.call_claude")
    def test_all_opposite_type_still_finds_cases(self, mock_claude: object) -> None:
        """eval_data with mixed types -> filter-first-then-slice finds matching cases."""
        # All first 3 are should_trigger=True, but we score FP (is_fn=False)
        data = [
            {"query": "deploy app", "should_trigger": True},
            {"query": "build pipeline", "should_trigger": True},
            {"query": "run migration", "should_trigger": True},
            {"query": "read file", "should_trigger": False},
            {"query": "what time", "should_trigger": False},
        ]
        mock_claude.return_value = "Use when deploying builds. Do not use for reads."
        score = score_guidance_prompt("guidance", "improve_fp", data)
        # should find the False cases (indices 3,4) and produce a real score
        assert score > 0.0


# ── TestScoreInstructionQuality ─────────────────────


class TestScoreInstructionQuality:
    """SKILL.md instruction section scoring."""

    @patch("self_evolve.call_claude")
    def test_good_instruction_output(self, mock_claude: object) -> None:
        """instruction produces compliant description -> high score."""
        mock_claude.return_value = (
            "Use when running database migration with schema backup, script execution, "
            "and data validation. Even if user says 'update the DB'. "
            "Do not use for simple queries."
        )
        assert score_instruction_quality("Rules here", _make_eval_data()) >= 0.7

    @patch("self_evolve.call_claude")
    def test_empty_output(self, mock_claude: object) -> None:
        """empty response -> 0.0."""
        mock_claude.return_value = ""
        assert score_instruction_quality("Rules", _make_eval_data()) == 0.0

    @patch("self_evolve.call_claude")
    def test_vague_output_penalized(self, mock_claude: object) -> None:
        """output with vague verbs scores lower."""
        mock_claude.return_value = "Handle database management tasks"
        score = score_instruction_quality("Rules", _make_eval_data())
        assert score < 0.5


# ── TestScorePrompt ─────────────────────────────────


class TestScorePrompt:
    """Routing to correct scoring function."""

    @patch("self_evolve.score_evaluator_prompt")
    def test_routes_evaluator(self, mock_score: object) -> None:
        """evaluator_accuracy -> score_evaluator_prompt."""
        mock_score.return_value = 0.9
        assert score_prompt("evaluate", "t", "evaluator_accuracy", []) == 0.9

    @patch("self_evolve.score_guidance_prompt")
    def test_routes_guidance(self, mock_score: object) -> None:
        """guidance_quality -> score_guidance_prompt."""
        mock_score.return_value = 0.8
        assert score_prompt("improve_fn", "g", "guidance_quality", []) == 0.8

    @patch("self_evolve.score_instruction_quality")
    def test_routes_instruction(self, mock_score: object) -> None:
        """instruction_quality -> score_instruction_quality."""
        mock_score.return_value = 0.7
        assert score_prompt("x", "text", "instruction_quality", []) == 0.7

    def test_unknown_metric(self) -> None:
        """unknown metric -> 0.0."""
        assert score_prompt("x", "t", "nonexistent", []) == 0.0


# ── TestGenerateVariants ────────────────────────────


class TestGenerateVariants:
    """Prompt variant generation."""

    @patch("self_evolve.call_claude")
    def test_generates_n_variants(self, mock_claude: object) -> None:
        """returns n variants when all succeed."""
        mock_claude.side_effect = ["V1", "V2", "V3"]
        assert len(generate_variants("original prompt text", "test", n=3)) == 3

    @patch("self_evolve.call_claude")
    def test_skips_empty(self, mock_claude: object) -> None:
        """empty response -> skipped."""
        mock_claude.side_effect = ["Good", "", "Also good"]
        assert len(generate_variants("original prompt text here", "test", n=3)) == 2

    @patch("self_evolve.call_claude")
    def test_all_fail(self, mock_claude: object) -> None:
        """all empty -> empty list."""
        mock_claude.side_effect = ["", "", ""]
        assert generate_variants("original", "test", n=3) == []

    @patch("self_evolve.call_claude")
    def test_empty_current_still_accepts_variants(self, mock_claude: object) -> None:
        """empty current text -> floor prevents rejecting all variants."""
        mock_claude.side_effect = ["A short variant", "Another one"]
        result = generate_variants("", "test", n=2)
        assert len(result) == 2


# ── TestEvolvePrompt ────────────────────────────────


class TestEvolvePrompt:
    """Single prompt evolution loop."""

    @patch("self_evolve.generate_variants")
    @patch("self_evolve.score_prompt")
    def test_finds_improvement(self, mock_score: object, mock_gen: object) -> None:
        """variant scores higher -> improved=True."""
        mock_score.side_effect = [0.6, 0.8, 0.7, 0.5]
        mock_gen.return_value = ["v1", "v2", "v3"]
        result = evolve_prompt("test", "current", "evaluator_accuracy", [{"query": "q"}])
        assert result["improved"] is True
        assert result["best"] == "v1"

    @patch("self_evolve.generate_variants")
    @patch("self_evolve.score_prompt")
    def test_no_improvement(self, mock_score: object, mock_gen: object) -> None:
        """no variant beats current -> improved=False."""
        mock_score.side_effect = [0.9, 0.7, 0.6, 0.5]
        mock_gen.return_value = ["v1", "v2", "v3"]
        result = evolve_prompt("test", "current", "evaluator_accuracy", [{"query": "q"}])
        assert result["improved"] is False


# ── TestApplyResults ────────────────────────────────


class TestApplyResults:
    """Source file patching (--apply)."""

    def test_patches_python_constant(self, tmp_path: Path) -> None:
        """improved Python prompt patches optimize_description.py."""
        py = tmp_path / "opt.py"
        py.write_text('EVALUATE_TEMPLATE = (\n    "old"\n)\n\nOTHER = True\n')
        md = tmp_path / "SKILL.md"
        md.write_text("# Empty\n")
        catalog = [PromptEntry("evaluate", "old", "evaluator_accuracy",
                               "python_constant", "EVALUATE_TEMPLATE")]
        results = [{"name": "evaluate", "improved": True, "best": "new"}]
        count = apply_results(results, catalog, py, md)
        assert count == 1
        assert "new" in py.read_text()
        assert "old" not in py.read_text()

    def test_patches_markdown_section(self, tmp_path: Path) -> None:
        """improved SKILL.md section patches the file."""
        py = tmp_path / "opt.py"
        py.write_text("")
        md = tmp_path / "SKILL.md"
        md.write_text("### My Section\n\nOld body\n\n### Next\n\nKept\n")
        catalog = [PromptEntry("skillmd:My Section", "Old body", "instruction_quality",
                               "markdown_section", "My Section")]
        results = [{"name": "skillmd:My Section", "improved": True, "best": "New body"}]
        count = apply_results(results, catalog, py, md)
        assert count == 1
        content = md.read_text()
        assert "New body" in content
        assert "Old body" not in content
        assert "Kept" in content

    def test_skips_not_improved(self, tmp_path: Path) -> None:
        """improved=False -> no patching."""
        py = tmp_path / "opt.py"
        py.write_text('X = (\n    "v"\n)\n')
        md = tmp_path / "SKILL.md"
        md.write_text("")
        catalog = [PromptEntry("x", "v", "evaluator_accuracy", "python_constant", "X")]
        results = [{"name": "x", "improved": False, "best": "v"}]
        assert apply_results(results, catalog, py, md) == 0


class TestFormatPythonConstant:
    """Python constant formatting."""

    def test_short_value(self) -> None:
        """short text -> single line."""
        result = _format_python_constant("MY_CONST", "short text")
        assert 'MY_CONST = (' in result
        assert '"short text"' in result

    def test_wraps_in_parentheses(self) -> None:
        """output has opening and closing parens."""
        result = _format_python_constant("X", "value")
        assert result.startswith("X = (")
        assert result.endswith(")")


# ── TestMain ────────────────────────────────────────


class TestMain:
    """Entry point."""

    @patch("self_evolve.evolve_prompt")
    @patch("self_evolve.build_catalog")
    @patch("self_evolve.collect_eval_data")
    def test_full_flow(self, mock_collect: object, mock_catalog: object,
                       mock_evolve: object, capsys: pytest.CaptureFixture[str]) -> None:
        """normal flow -> stdout JSON with summary."""
        mock_collect.return_value = [{"query": "q1", "should_trigger": True}]
        mock_catalog.return_value = [
            PromptEntry("test", "val", "evaluator_accuracy", "python_constant", "X"),
        ]
        mock_evolve.return_value = {
            "name": "test", "original": "old", "best": "new",
            "original_score": 0.5, "best_score": 0.8,
            "improved": True, "variants_tested": 3,
        }
        with patch("sys.argv", ["self_evolve.py", "--skills-dir", "/fake"]):
            main()
        output = json.loads(capsys.readouterr().out)
        assert output["total_prompts"] == 1
        assert output["improved"] == 1
        assert output["results"][0]["winning_prompt"] == "new"

    @patch("self_evolve.collect_eval_data")
    def test_exits_on_no_data(self, mock_collect: object) -> None:
        """no eval data -> exit(1)."""
        mock_collect.return_value = []
        with patch("sys.argv", ["self_evolve.py", "--skills-dir", "/fake"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1
