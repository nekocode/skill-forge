"""Full test suite for self_evolve.py."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

import self_evolve


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skip time.sleep to keep tests fast.

    After the RateLimiter migration the actual sleep call lives in
    shared.time.sleep (RateLimiter.throttle), so both locations must be
    neutralized — patching only self_evolve.time.sleep would leak real
    sleeps through to the limiter at higher RPM caps.
    """
    import shared  # noqa: PLC0415 — test-only
    monkeypatch.setattr(self_evolve.time, "sleep", lambda _: None)
    monkeypatch.setattr(shared.time, "sleep", lambda _: None)

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
    _configure_rate_limit,
    _format_python_constant,
    _pick_thinking_styles,
    _run_parallel,
    _sanitize_variant,
    _THINKING_STYLES,
    DEFAULT_RPM,
    SAMPLE_RUNS,
    SIGNIFICANCE_THRESHOLD,
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
            "### Description writing rules\n\n"
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
        """all correct -> 1.0. Query-keyed side_effect is deterministic regardless
        of parallel worker ordering — pure index-based lists would be fragile."""
        def _answer(prompt: str) -> str:
            return "YES" if ("deploy" in prompt or "CI/CD" in prompt) else "NO"
        mock_claude.side_effect = _answer
        assert score_evaluator_prompt("t {description} {query}", _make_eval_data()) == 1.0

    @patch("self_evolve.call_claude")
    def test_empty_data(self, mock_claude: object) -> None:
        """no eval data -> 0.0."""
        assert score_evaluator_prompt("t {description} {query}", []) == 0.0

    @patch("self_evolve.call_claude")
    def test_per_case_description(self, mock_claude: object) -> None:
        """Each case's own `description` field is passed to the template, not a fixed mock."""
        seen_descriptions: list[str] = []

        def _answer(prompt: str) -> str:
            for line in prompt.splitlines():
                if "desc=" in line:
                    seen_descriptions.append(line.split("desc=", 1)[1])
            return "YES"

        mock_claude.side_effect = _answer
        data = [
            {"description": "Deploy skill", "query": "q1", "should_trigger": True},
            {"description": "Migration skill", "query": "q2", "should_trigger": True},
        ]
        score_evaluator_prompt("desc={description}\nquery={query}", data)
        assert "Deploy skill" in seen_descriptions
        assert "Migration skill" in seen_descriptions


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
    """SKILL.md instruction section scoring via LLM judge."""

    @patch("self_evolve.call_claude")
    def test_good_instruction_output(self, mock_claude: object) -> None:
        """LLM judge returns high score across tasks -> high final score."""
        def _answer(prompt: str) -> str:
            if prompt.startswith("Score a skill trigger description"):
                return "9"
            return "Generated multi-step skill description."
        mock_claude.side_effect = _answer
        assert score_instruction_quality("Rules here", _make_eval_data()) >= 0.7

    @patch("self_evolve.call_claude")
    def test_empty_output(self, mock_claude: object) -> None:
        """empty description from every task -> 0.0 (judge never runs)."""
        mock_claude.return_value = ""
        assert score_instruction_quality("Rules", _make_eval_data()) == 0.0

    @patch("self_evolve.call_claude")
    def test_low_judge_score(self, mock_claude: object) -> None:
        """LLM judge returns low score -> final score stays low."""
        def _answer(prompt: str) -> str:
            if prompt.startswith("Score a skill trigger description"):
                return "2"
            return "vague generated text"
        mock_claude.side_effect = _answer
        assert score_instruction_quality("Rules", _make_eval_data()) < 0.5

    @patch("self_evolve.call_claude")
    def test_unparseable_judge_output(self, mock_claude: object) -> None:
        """Judge verdict without digits -> that task scores 0 (no crash)."""
        def _answer(prompt: str) -> str:
            if prompt.startswith("Score a skill trigger description"):
                return "excellent but no number here"
            return "ok description"
        mock_claude.side_effect = _answer
        assert score_instruction_quality("Rules", _make_eval_data()) == 0.0


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

    @patch("self_evolve.score_evaluator_prompt")
    def test_multi_sample_averages(self, mock_score: object) -> None:
        """k=SAMPLE_RUNS samples → return arithmetic mean."""
        mock_score.side_effect = [0.6, 0.8]  # noisy samples, mean=0.7
        assert score_prompt("evaluate", "t", "evaluator_accuracy", []) == 0.7
        assert mock_score.call_count == SAMPLE_RUNS


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

    @patch("self_evolve.call_claude")
    def test_drops_meta_contaminated(self, mock_claude: object) -> None:
        """variants leaking conversational address or meta commentary are rejected."""
        mock_claude.side_effect = [
            # meta wrapper + middle also has Variant # marker → reject
            "哥，这是 variant #2：\n---\nVariant #2 rewrites the prompt from scratch\n---\n差异点：...",
            # starts with conversational lead → reject
            "Here's variant #1: use this prompt",
            # clean → accept
            "A clean prompt",
        ]
        result = generate_variants("original prompt text", "test", n=3)
        assert result == ["A clean prompt"]

    @patch("self_evolve.call_claude")
    def test_salvages_clean_middle_block(self, mock_claude: object) -> None:
        """--- wrapper with clean middle: extract the middle as a valid variant."""
        mock_claude.side_effect = [
            "Here's your variant:\n---\nactual clean prompt body content\n---\n(that's all)",
        ]
        result = generate_variants("original prompt text here", "test", n=1)
        assert result == ["actual clean prompt body content"]

    @patch("self_evolve.call_claude")
    def test_injects_thinking_style(self, mock_claude: object) -> None:
        """each generation prompt includes a directive from the thinking-style bank."""
        mock_claude.side_effect = ["VariantA", "VariantB", "VariantC"]
        generate_variants("original prompt text", "test", n=3)
        prompts = [c.args[0] for c in mock_claude.call_args_list]
        for p in prompts:
            assert any(style in p for style in _THINKING_STYLES), (
                f"no thinking-style found in generation prompt: {p[:200]}"
            )


class TestPickThinkingStyles:
    """Thinking-style sampling."""

    def test_unique_when_n_within_bank(self) -> None:
        """n ≤ bank size → all picks distinct (explores different axes)."""
        picks = _pick_thinking_styles(len(_THINKING_STYLES))
        assert len(set(picks)) == len(_THINKING_STYLES)

    def test_capped_at_bank_size(self) -> None:
        """n > bank size → returns bank-size many distinct styles (no duplicates)."""
        picks = _pick_thinking_styles(len(_THINKING_STYLES) + 5)
        assert len(picks) == len(_THINKING_STYLES)
        assert set(picks) == set(_THINKING_STYLES)


class TestSanitizeVariant:
    """Meta-leak detection on generated variants."""

    def test_clean_passes(self) -> None:
        assert _sanitize_variant("Rewrite the description by ...") == "Rewrite the description by ..."

    def test_chinese_lead_rejected(self) -> None:
        """CLAUDE.md-style conversational address leaks → reject."""
        assert _sanitize_variant("哥，这里是 variant：\n\nreal content") is None

    def test_here_is_lead_rejected(self) -> None:
        assert _sanitize_variant("Here's the improved prompt: use X") is None

    def test_meta_marker_rejected(self) -> None:
        """Variant #N, 差异点, etc. anywhere → reject."""
        assert _sanitize_variant("Use when X.\n\nVariant #3 notes: ...") is None
        assert _sanitize_variant("The fix: do Y.\n\n差异点：与原版区别") is None

    def test_separator_extracts_longest_block(self) -> None:
        """--- delimiters: pick the largest block (the actual prompt)."""
        input_text = "short preamble\n---\nthis is the actual meaningful prompt text that is longer\n---\npostamble"
        result = _sanitize_variant(input_text)
        assert result is not None
        assert "meaningful prompt" in result

    def test_empty_returns_none(self) -> None:
        assert _sanitize_variant("") is None
        assert _sanitize_variant("   \n  ") is None


# ── TestEvolvePrompt ────────────────────────────────


class TestEvolvePrompt:
    """Single prompt evolution loop."""

    @patch("self_evolve.generate_variants")
    @patch("self_evolve.score_prompt")
    def test_finds_improvement(self, mock_score: object, mock_gen: object) -> None:
        """variant scores higher -> improved=True. Value-keyed side_effect is
        parallel-safe: threading can reorder side_effect-list consumption."""
        scores = {"current": 0.6, "v1": 0.8, "v2": 0.7, "v3": 0.5}
        mock_score.side_effect = lambda name, v, mt, ed: scores[v]
        mock_gen.return_value = ["v1", "v2", "v3"]
        result = evolve_prompt("test", "current", "evaluator_accuracy", [{"query": "q"}])
        assert result["improved"] is True
        assert result["best"] == "v1"

    @patch("self_evolve.generate_variants")
    @patch("self_evolve.score_prompt")
    def test_no_improvement(self, mock_score: object, mock_gen: object) -> None:
        """no variant beats current -> improved=False. Value-keyed mock
        absorbs the extra train/test-rescore calls the holdout path adds."""
        scores = {"current": 0.9, "v1": 0.7, "v2": 0.6, "v3": 0.5}
        mock_score.side_effect = lambda name, v, mt, ed: scores[v]
        mock_gen.return_value = ["v1", "v2", "v3"]
        result = evolve_prompt("test", "current", "evaluator_accuracy", [{"query": "q"}])
        assert result["improved"] is False

    @patch("self_evolve.generate_variants")
    @patch("self_evolve.score_prompt")
    def test_rejects_below_threshold(self, mock_score: object, mock_gen: object) -> None:
        """variant score above baseline but lift < SIGNIFICANCE_THRESHOLD → rejected."""
        # baseline 0.65, variants 0.70 / 0.75 / 0.60 — all lifts < 0.15
        scores = {"current": 0.65, "v1": 0.70, "v2": 0.75, "v3": 0.60}
        mock_score.side_effect = lambda name, v, mt, ed: scores[v]
        mock_gen.return_value = ["v1", "v2", "v3"]
        result = evolve_prompt("test", "current", "evaluator_accuracy", [{"query": "q"}])
        assert result["improved"] is False
        assert result["best"] == "current"

    @patch("self_evolve.generate_variants")
    @patch("self_evolve.score_prompt")
    def test_overfit_risk_flag(self, mock_score: object, mock_gen: object) -> None:
        """Large train-test gap on the selected winner -> overfit_risk=True."""
        eval_data = [{"query": f"q{i}", "should_trigger": i % 2 == 0} for i in range(10)]
        # score_prompt signature: (name, value, metric_type, eval_data_subset)
        # eval_data_subset is a list; train subset is larger than test subset.
        # v1 scores great on train (0.95) but tanks on test (0.40) -> overfit.
        train_scores = {"current": 0.50, "v1": 0.95, "v2": 0.55, "v3": 0.50}
        test_scores = {"current": 0.50, "v1": 0.40, "v2": 0.55, "v3": 0.50}

        def _score(name, value, mt, ed_subset):
            # train has 6 items at ratio=0.6, test has 4 items
            return train_scores[value] if len(ed_subset) >= 6 else test_scores[value]

        mock_score.side_effect = _score
        mock_gen.return_value = ["v1", "v2", "v3"]
        result = evolve_prompt("test", "current", "evaluator_accuracy", eval_data)
        assert result["improved"] is True
        assert result["best"] == "v1"
        assert result["best_train_score"] == 0.95
        assert result["best_test_score"] == 0.40
        assert result["overfit_risk"] is True

    @patch("self_evolve.generate_variants")
    @patch("self_evolve.score_prompt")
    def test_accepts_above_threshold(self, mock_score: object, mock_gen: object) -> None:
        """variant with lift ≥ SIGNIFICANCE_THRESHOLD replaces baseline."""
        # baseline 0.65; v1 +0.10 (below), v2 +0.20 (above), v3 +0.05 (below)
        scores = {"current": 0.65, "v1": 0.75, "v2": 0.85, "v3": 0.70}
        mock_score.side_effect = lambda name, v, mt, ed: scores[v]
        mock_gen.return_value = ["v1", "v2", "v3"]
        result = evolve_prompt("test", "current", "evaluator_accuracy", [{"query": "q"}])
        assert result["improved"] is True
        assert result["best"] == "v2"


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

    def test_escapes_control_chars(self) -> None:
        """literal newlines/tabs in value become escape sequences so source parses."""
        import ast
        value = "line one\nline two\twith tab\n\nblank line"
        result = _format_python_constant("Y", value)
        # resulting source must parse and round-trip to the original value
        parsed = ast.parse(result, mode="exec")
        assert "\n" not in result.split("\n", 1)[1].rsplit("\n", 1)[0][5:]  # no literal \n inside any "..." line
        ns: dict = {}
        exec(compile(parsed, "<test>", "exec"), ns)
        assert ns["Y"] == value


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
            "original_train_score": 0.5, "original_test_score": 0.55,
            "best_train_score": 0.8, "best_test_score": 0.75,
            "overfit_risk": False,
            "improved": True, "variants_tested": 3,
        }
        with patch("sys.argv", ["self_evolve.py", "--skills-dir", "/fake"]):
            main()
        output = json.loads(capsys.readouterr().out)
        assert output["total_prompts"] == 1
        assert output["improved"] == 1
        assert output["overfit_flagged"] == 0
        assert output["results"][0]["winning_prompt"] == "new"
        assert output["results"][0]["best_test_score"] == 0.75

    @patch("self_evolve.collect_eval_data")
    def test_exits_on_no_data(self, mock_collect: object) -> None:
        """no eval data -> exit(1)."""
        mock_collect.return_value = []
        with patch("sys.argv", ["self_evolve.py", "--skills-dir", "/fake"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1


# ── TestRunParallel ─────────────────────────────────


class TestRunParallel:
    """Parallel map helper."""

    def test_preserves_submission_order(self) -> None:
        """results returned in input order even when workers complete out of order."""
        import threading
        import time as real_time
        barrier = threading.Barrier(4)

        def _delayed(i: int) -> int:
            # all workers wait at barrier, then return — forces out-of-order completion
            barrier.wait()
            real_time.sleep(0.001 * (4 - i))  # later-submitted returns sooner
            return i * 10

        assert _run_parallel(_delayed, [0, 1, 2, 3]) == [0, 10, 20, 30]

    def test_empty_input(self) -> None:
        """no items -> empty list, no executor spawned."""
        assert _run_parallel(lambda x: x, []) == []

    def test_single_item(self) -> None:
        """single item works (workers clamped to len(items))."""
        assert _run_parallel(lambda x: x + 1, [5]) == [6]


# ── TestRateLimiter ─────────────────────────────────


class TestRateLimiter:
    """Rate-limit configuration."""

    def test_configure_sets_interval(self) -> None:
        """--rpm arg converts cleanly to seconds-between-launches."""
        _configure_rate_limit(60)
        assert self_evolve._limiter._min_interval == pytest.approx(1.0)
        _configure_rate_limit(30)
        assert self_evolve._limiter._min_interval == pytest.approx(2.0)
        _configure_rate_limit(DEFAULT_RPM)  # restore default

    def test_configure_rejects_zero(self) -> None:
        """rpm=0 clamps to 1 to avoid division by zero."""
        _configure_rate_limit(0)
        assert self_evolve._limiter._min_interval == pytest.approx(60.0)
        _configure_rate_limit(DEFAULT_RPM)

    @patch("self_evolve._raw_call_claude")
    def test_call_claude_invokes_throttle(self, mock_raw: object) -> None:
        """wrapper calls _throttle before the raw subprocess."""
        mock_raw.return_value = "OK"
        with patch("self_evolve._throttle") as mock_throttle:
            result = self_evolve.call_claude("hello")
        assert result == "OK"
        mock_throttle.assert_called_once()
        mock_raw.assert_called_once_with("hello")

    @patch("self_evolve._raw_call_claude")
    def test_call_claude_retries_on_empty(self, mock_raw: object) -> None:
        """Empty primary response triggers a throttled retry before giving up."""
        mock_raw.side_effect = ["", "recovered"]
        with patch("self_evolve._throttle") as mock_throttle:
            result = self_evolve.call_claude("hello")
        assert result == "recovered"
        assert mock_throttle.call_count == 2
        assert mock_raw.call_count == 2

    @patch("self_evolve._raw_call_claude")
    def test_call_claude_exhausts_retries(self, mock_raw: object) -> None:
        """After all attempts return empty, wrapper returns '' — does not raise."""
        mock_raw.return_value = ""
        with patch("self_evolve._throttle") as mock_throttle:
            result = self_evolve.call_claude("hello")
        assert result == ""
        assert mock_throttle.call_count == self_evolve._CALL_CLAUDE_MAX_ATTEMPTS
        assert mock_raw.call_count == self_evolve._CALL_CLAUDE_MAX_ATTEMPTS
