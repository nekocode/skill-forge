"""Meta-optimizer for prompt templates (dev tool).

Evolves Python constants in optimize_description.py and markdown sections
in SKILL.md. Workflow: accumulate trigger_evals.json → run this script →
git diff → commit. Concurrent API calls gated by a shared RPM budget;
default 46 fits Tier-1 (50 RPM cap).
Usage: `python self_evolve.py --skills-dir .claude/skills [--variants 3] [--apply] [--rpm 46]`
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time  # noqa: F401 — kept so tests can monkeypatch self_evolve.time.sleep
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, TypeVar

# k=2: stochastic scoring has ±0.50 swing per run; √2 noise reduction. Higher k
# blows the API budget. Lifts under SIGNIFICANCE_THRESHOLD are resampling noise.
SAMPLE_RUNS = 2
SIGNIFICANCE_THRESHOLD = 0.15

# PromptBreeder-lite: one style per variant pushes the generator off local paraphrase.
_THINKING_STYLES: tuple[str, ...] = (
    "rewrite as if instructing a skeptical senior engineer who won't follow vague advice",
    "rewrite as a terse spec a compiler could parse — strip all hedging",
    "rewrite emphasizing the failure modes this prompt prevents, not the behavior it enables",
    "rewrite as a checklist a reviewer could mechanically apply",
    "rewrite by starting from the required output format and working backwards to the instruction",
    "rewrite as if the reader has never seen this task type before",
)

from optimize_description import (  # noqa: E402
    EVALUATE_TEMPLATE,
    IMPROVE_FN_GUIDANCE,
    IMPROVE_FP_GUIDANCE,
    _call_claude_once as _raw_call_claude,
    split_train_test,
)
from shared import DEFAULT_RPM, RateLimiter, log_stderr as _log  # noqa: E402

# Holdout ratio matches optimize_description's primary-path split (60/40 seed 42)
# so both optimizers are calibrated to the same evaluation convention.
HOLDOUT_RATIO = 0.6
HOLDOUT_SEED = 42
# Train-test gap above this flags overfit. <0.15 is resampling noise, >0.30 is
# almost always overfit; 0.30 preserves signal-to-noise.
OVERFIT_GAP_THRESHOLD = 0.30


# ── rate limiter + parallel map ─────────────────────
# All API calls funnel through the `call_claude` wrapper below, which delegates
# to the module-level `_limiter` — a single shared.RateLimiter instance that
# serializes launch timestamps across all worker threads. Tests inspect the
# interval via `_limiter._min_interval`.

_T = TypeVar("_T")
_U = TypeVar("_U")

_limiter = RateLimiter(rpm=DEFAULT_RPM)


def _configure_rate_limit(rpm: int) -> None:
    """Rebind the module limiter for the given RPM. Called once from main()."""
    global _limiter
    _limiter = RateLimiter(rpm=rpm)


def _throttle() -> None:
    """Delegate to the shared rate limiter. Kept as module-level alias so
    `patch("self_evolve._throttle")` call sites in tests keep working.
    """
    _limiter.throttle()


# 3 attempts absorbs transient empty responses under parallel claude-CLI load.
_CALL_CLAUDE_MAX_ATTEMPTS = 3


def call_claude(prompt: str) -> str:
    """Throttled claude --print with bounded retries on empty response.

    Owning the retry here (instead of in `optimize_description.call_claude`)
    keeps every API launch — primary AND retry — inside the RPM budget. The
    module-level binding is the patch target for tests.
    """
    for _ in range(_CALL_CLAUDE_MAX_ATTEMPTS):
        _throttle()
        result = _raw_call_claude(prompt)
        if result:
            return result
    _log(f"  [call_claude] empty after {_CALL_CLAUDE_MAX_ATTEMPTS} attempts; "
         f"prompt prefix: {prompt[:80]!r}")
    return ""


def _run_parallel(fn: Callable[[_T], _U], items: Iterable[_T]) -> list[_U]:
    """Execute `fn` over `items` concurrently; results in submission order.

    A fresh executor per call avoids the nested-submission deadlock that a shared
    pool risks (parent thread holding a worker while waiting for child work that
    has nowhere to run). Concurrency is still bounded by the global rate limiter,
    so pool width has no effect on API cost — only thread count.
    """
    items = list(items)
    if not items:
        return []
    workers = min(len(items), 16)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        return list(executor.map(fn, items))


# ── prompt catalog ──────────────────────────────────


@dataclass
class PromptEntry:
    """A single optimizable prompt in the project."""

    name: str
    default: str
    metric_type: str
    # source location: either a Python constant or a SKILL.md section
    source_type: str       # "python_constant" or "markdown_section"
    source_key: str        # constant name (e.g. "EVALUATE_TEMPLATE") or markdown heading


def build_catalog(skill_md_path: Path) -> list[PromptEntry]:
    """Build the full prompt catalog from Python constants + SKILL.md sections."""
    entries = [
        PromptEntry("evaluate", EVALUATE_TEMPLATE, "evaluator_accuracy",
                     "python_constant", "EVALUATE_TEMPLATE"),
        PromptEntry("improve_fn", IMPROVE_FN_GUIDANCE, "guidance_quality",
                     "python_constant", "IMPROVE_FN_GUIDANCE"),
        PromptEntry("improve_fp", IMPROVE_FP_GUIDANCE, "guidance_quality",
                     "python_constant", "IMPROVE_FP_GUIDANCE"),
    ]

    # extract SKILL.md sections as prompt entries
    if skill_md_path.is_file():
        content = skill_md_path.read_text()
        for heading, metric in SKILL_MD_SECTIONS:
            section = extract_markdown_section(content, heading)
            if section:
                entries.append(PromptEntry(
                    name=f"skillmd:{heading}",
                    default=section,
                    metric_type=metric,
                    source_type="markdown_section",
                    source_key=heading,
                ))

    return entries


# SKILL.md sections to optimize: (heading_text, metric_type)
SKILL_MD_SECTIONS: list[tuple[str, str]] = [
    ("Description writing rules", "instruction_quality"),
    ("Step 3b: triggering improvement (eval-driven)", "instruction_quality"),
]


# ── markdown section extraction ─────────────────────


def extract_markdown_section(content: str, heading: str) -> str:
    """Extract content between a heading and the next same-or-higher-level heading.

    Returns empty string if heading not found.
    """
    # find the heading line (## or ### or ####); {{ }} escapes braces in f-string
    pattern = re.compile(rf'^(#{{2,4}})\s+{re.escape(heading)}[ \t]*\n', re.MULTILINE)
    match = pattern.search(content)
    if not match:
        return ""

    level = len(match.group(1))
    start = match.end()

    # find next heading at same or higher level (fewer or equal #)
    next_pattern = re.compile(rf'^#{{{1},{level}}}\s+', re.MULTILINE)
    next_match = next_pattern.search(content, start)

    section = content[start:next_match.start()] if next_match else content[start:]
    return section.strip()


# replace_markdown_section / apply_results / patch_python_constant / format_python_constant
# live in self_evolve_apply.py (split out to stay under the file-size cap).
# Re-exported here for back-compat with existing `from self_evolve import ...` call sites
# (including tests that patch these symbols on this module).
from self_evolve_apply import (  # noqa: E402
    apply_results,
    format_python_constant as _format_python_constant,
    patch_python_constant as _patch_python_constant,
    replace_markdown_section,
)


# ── eval data collection ────────────────────────────


def collect_eval_data(skills_dir: Path) -> list[dict]:
    """Find all trigger_evals.json under skills_dir, merge into one dataset.

    Skips malformed files. Returns empty list if none found.
    """
    all_evals: list[dict] = []

    if not skills_dir.is_dir():
        return all_evals

    for eval_file in skills_dir.rglob("trigger_evals.json"):
        try:
            data = json.loads(eval_file.read_text())
            if isinstance(data, list):
                all_evals.extend(data)
        except (json.JSONDecodeError, OSError):
            continue

    return all_evals


# ── scoring functions ───────────────────────────────


_DEFAULT_MOCK_DESC = "A multi-step workflow skill for complex tasks"


def score_evaluator_prompt(template: str, eval_data: list[dict]) -> float:
    """Score an evaluate template by LLM-judge accuracy on labeled eval data.

    Per-case description falls back to `_DEFAULT_MOCK_DESC` so the template
    is judged on matching vs. non-matching pairs, not a single fixed desc.
    Single call per case (no majority vote) for speed; parallelized with the
    global rate limiter gating API invocation. Cap 30 balances variance
    reduction against API budget.
    """
    if not eval_data:
        return 0.0
    capped = eval_data[:30]

    def _judge(item: dict) -> bool:
        prompt = template.format(
            description=item.get("description") or _DEFAULT_MOCK_DESC,
            query=item.get("query", ""),
        )
        response = call_claude(prompt)
        predicted = response.strip().upper() == "YES"
        return predicted == item.get("should_trigger", False)

    results = _run_parallel(_judge, capped)
    return sum(1 for r in results if r) / len(capped)


# One case per theme: guidance prompts must generalize across domains, not
# overfit whichever cases sort first. "api " trailing space avoids substring
# hits inside `apiary` / `graphiql`; switch to word-boundary regex if themes grow.
_THEME_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("deploy", ("deploy", "release", "production", "staging", "rollback")),
    ("migration", ("migrat", "schema", "seed", "backfill")),
    ("ci", ("ci/cd", "pipeline", "github actions", "jenkins", "workflow")),
    ("test", ("test", "coverage", "fixture", "integration test")),
    ("api", ("endpoint", "route", "api ")),
)


def _sample_by_theme(cases: list[dict], limit: int = 3) -> list[dict]:
    """Pick up to one case per theme for diversity, then top up to `limit` from the rest."""
    picked: list[dict] = []
    used_idx: set[int] = set()
    for _, keywords in _THEME_KEYWORDS:
        if len(picked) >= limit:
            break
        for i, item in enumerate(cases):
            if i in used_idx:
                continue
            query = item.get("query", "").lower()
            if any(k in query for k in keywords):
                picked.append(item)
                used_idx.add(i)
                break
    for i, item in enumerate(cases):
        if len(picked) >= limit:
            break
        if i not in used_idx:
            picked.append(item)
            used_idx.add(i)
    return picked


def score_guidance_prompt(guidance: str, guidance_type: str, eval_data: list[dict]) -> float:
    """Score a guidance prompt by checking structural quality of improvement output."""
    mock_desc = "Use when deploying code to production environments"
    is_fn = guidance_type == "improve_fn"
    filtered = [item for item in eval_data if item.get("should_trigger", False) == is_fn]
    cases = _sample_by_theme(filtered, limit=3)
    failures = "\n".join(f"- {c['query']}" for c in cases)
    label = "False negatives — missed" if is_fn else "False positives — triggered incorrectly"

    result = call_claude(
        f"Improve this skill description.\n\nCurrent: {mock_desc}\n\n"
        f"{label}:\n{failures}\n{guidance}\n\n"
        "Write an improved description under 250 characters. Output ONLY the new description."
    )
    if not result:
        return 0.0

    # 4 criteria × 0.25 each: non-empty / length ≤ 300 / expected phrases /
    # expansion (FN) or "when" clause (FP).
    score, lower = 0.25, result.lower()
    if len(result) <= 300:
        score += 0.25
    if is_fn:
        if any(w in lower for w in ("use when", "even if", "use this")):
            score += 0.25
        if len(result) > len(mock_desc):
            score += 0.25
    else:
        if any(w in lower for w in ("do not", "not use", "don't")):
            score += 0.25
        if "when" in lower:
            score += 0.25
    return score


_INSTRUCTION_MOCK_TASKS: tuple[str, ...] = (
    "database migration with schema backup, migration script execution, "
    "data validation, and seed update",
    "deploy to production: build artifacts, bump version, push container image, "
    "update k8s manifest, run smoke tests, and rollback on health check failure",
    "CI pipeline setup: configure secrets, write workflow file, add matrix tests, "
    "cache dependencies, and enforce branch protection",
    "integration test run: seed fixtures, spin up test containers, execute test "
    "suite, collect coverage, tear down environment",
)

_JUDGE_PROMPT = (
    "Score a skill trigger description 0-10 on how well it would activate "
    "correctly in Claude Code.\n\nCriteria (1-2 points each):\n"
    "1. Names SPECIFIC multi-step actions (not vague 'manage'/'handle'/'work with')\n"
    "2. Clear POSITIVE trigger signal — user phrases that should activate it\n"
    "3. Clear NEGATIVE exclusion — 'do NOT use when X' for near-miss cases\n"
    "4. Concise: under ~250 chars, no fluff\n"
    "5. Domain keywords front-loaded (first 50 chars hint at what it does)\n\n"
    "Description to score:\n---\n{description}\n---\n\n"
    "Output ONLY a single integer 0-10. No explanation."
)


def score_instruction_quality(instruction: str, eval_data: list[dict]) -> float:
    """Score a SKILL.md instruction by the quality of descriptions written under it.

    For each mock task: generate a description using the instruction, then have
    Claude judge that description 0-10. Final score = mean across tasks, in [0, 1].
    LLM judge over hardcoded keywords: optimizes for general description quality,
    not for a fixed keyword checklist. `eval_data` unused (signature parity with
    other scorers for `_score_once` routing).
    """
    del eval_data

    def _score_task(task: str) -> float:
        description = call_claude(
            "You are writing a skill trigger description following these rules:\n\n"
            f"{instruction}\n\n"
            f"Task: write a trigger description for a skill that handles '{task}'.\n\n"
            "Output ONLY the description text, nothing else."
        )
        if not description:
            return 0.0
        verdict = call_claude(_JUDGE_PROMPT.format(description=description))
        match = re.search(r"\d+", verdict)
        if not match:
            return 0.0
        raw = int(match.group())
        return max(0.0, min(raw, 10)) / 10.0

    results = _run_parallel(_score_task, _INSTRUCTION_MOCK_TASKS)
    return sum(results) / len(results) if results else 0.0


def _score_once(name: str, value: str, metric_type: str, eval_data: list[dict]) -> float:
    """Single-sample scoring: route to the scorer matching metric_type."""
    if metric_type == "evaluator_accuracy":
        return score_evaluator_prompt(value, eval_data)
    if metric_type == "guidance_quality":
        guidance_type = name  # "improve_fn" or "improve_fp"
        return score_guidance_prompt(value, guidance_type, eval_data)
    if metric_type == "instruction_quality":
        return score_instruction_quality(value, eval_data)
    return 0.0


def score_prompt(
    name: str,
    value: str,
    metric_type: str,
    eval_data: list[dict],
) -> float:
    """Multi-sample mean of `_score_once` over `SAMPLE_RUNS` trials.

    Scorers are stochastic at temperature > 0, so one sample is noisy. Averaging k
    samples reduces std by √k. k is fixed at module level — no per-call override.
    Samples run in parallel; the rate limiter throttles actual API invocation.
    """
    scores = _run_parallel(
        lambda _idx: _score_once(name, value, metric_type, eval_data),
        range(SAMPLE_RUNS),
    )
    return sum(scores) / len(scores)


# ── variant generation ──────────────────────────────


_META_LEAD_MARKERS = (
    "哥", "Here's", "Here is", "Sure,", "Sure!", "Certainly", "Okay,",
    "好的", "变体", "Variant #", "Variant:",
)
_META_BODY_MARKERS = (
    "variant #", "variant:", "差异点", "原版是", "原版的", "差异：", "差异:",
    "## difference", "## 差异", "**差异", "the difference between",
    "here's the improved", "here is the improved",
)


def _sanitize_variant(text: str) -> str | None:
    """Strip meta-leak markers from a generated variant. Return None if unrecoverable.

    Two common failure modes this catches:
    - Conversational lead: "Here's variant #2: ..." or CLAUDE.md style leak ("哥, ...")
    - Meta blocks delimited by --- with explanation of differences from the baseline
    """
    if not text:
        return None
    t = text.strip()
    # --- separators: take the longest block (real prompt), drop commentary wrappers
    if "---" in t:
        blocks = [b.strip() for b in t.split("---") if b.strip()]
        if blocks:
            t = max(blocks, key=len)
    if any(t.startswith(lead) for lead in _META_LEAD_MARKERS):
        return None
    low = t.lower()
    if any(marker.lower() in low for marker in _META_BODY_MARKERS):
        return None
    return t or None


def _pick_thinking_styles(n: int) -> list[str]:
    """Without-replacement sampling so variants explore distinct axes."""
    return random.sample(_THINKING_STYLES, min(n, len(_THINKING_STYLES)))


def generate_variants(
    current: str,
    prompt_name: str,
    n: int = 3,
) -> list[str]:
    """Generate N prompt variants via Claude, each guided by a distinct thinking-style.

    Returns list of variant strings (may be < n if Claude returns empty/too-long/contaminated).
    Generation runs in parallel; the rate limiter throttles actual API invocation.
    """
    styles = _pick_thinking_styles(n)
    # floor so empty `current` doesn't reject every variant via the length check
    length_cap = max(len(current) * 2, 500)

    def _generate(indexed: tuple[int, str]) -> str | None:
        i, style = indexed
        generation_prompt = (
            f"You are optimizing a prompt template used in an AI skill trigger system.\n\n"
            f"Prompt name: {prompt_name}\n"
            f"Current prompt:\n{current}\n\n"
            f"Generate variant #{i + 1} of this prompt that might perform better.\n"
            f"Variant direction: {style}.\n"
            "Rules:\n"
            "- Keep the same placeholders (e.g., {{description}}, {{query}}) if present\n"
            "- Maintain the same output format requirement (YES/NO, or description text)\n"
            "- Apply the variant direction — don't just paraphrase the current prompt\n"
            "- Keep similar length (within 50% of original)\n\n"
            "CRITICAL: output is fed verbatim into the system. No preamble, no commentary, "
            "no markdown fences, no '---' separators, no 'Variant #' labels, no "
            "'differences from the original' notes. Just the prompt text itself."
        )
        result = call_claude(generation_prompt)
        clean = _sanitize_variant(result)
        if clean and len(clean) < length_cap:
            return clean
        return None

    results = _run_parallel(_generate, list(enumerate(styles)))
    return [v for v in results if v is not None]


# ── evolution loop ──────────────────────────────────


def evolve_prompt(name: str, current: str, metric_type: str,
                  eval_data: list[dict], n_variants: int = 3) -> dict:
    """Meta-optimize a single prompt. Returns result dict with winner.

    Train/test holdout: eval_data is split 60/40. Variants are scored on
    train only; the winner is selected by train score (constrained by
    SIGNIFICANCE_THRESHOLD). The winner is then re-scored on the held-out
    test set — this number is never used to select, only to flag overfit.

    A variant replaces the baseline only if its train score exceeds baseline
    by at least SIGNIFICANCE_THRESHOLD. If the winner's train-test gap exceeds
    OVERFIT_GAP_THRESHOLD, `overfit_risk=True` in the result so a reviewer
    can decide manually.

    The instruction_quality scorer ignores eval_data (it uses hardcoded mock
    tasks), so its train and test scores are identical by construction — the
    gap flag is inert for that metric.
    """
    _log(f"\n=== Evolving: {name} ===")
    train_set, test_set = split_train_test(eval_data, ratio=HOLDOUT_RATIO, seed=HOLDOUT_SEED)
    _log(f"  Split: {len(train_set)} train / {len(test_set)} test")

    current_train = score_prompt(name, current, metric_type, train_set)
    _log(f"  Current train: {current_train:.2f} (mean of {SAMPLE_RUNS} samples)")
    best, best_train = current, current_train

    variants = generate_variants(current, name, n=n_variants)
    _log(f"  Generated {len(variants)} variants")
    # score all variants concurrently on train; rate limiter still serializes launches
    variant_trains = _run_parallel(
        lambda v: score_prompt(name, v, metric_type, train_set),
        variants,
    )
    for i, (variant, variant_train) in enumerate(zip(variants, variant_trains)):
        margin = variant_train - current_train
        _log(f"  Variant {i + 1} train: {variant_train:.2f} (Δ={margin:+.2f})")
        # both clauses are essential: must beat the running best AND clear the
        # significance bar against the original baseline (stops drift via tiny steps).
        if variant_train > best_train and margin > SIGNIFICANCE_THRESHOLD:
            best_train, best = variant_train, variant

    improved = best != current
    # Test-set rescore happens only when a variant won AND there's a test split —
    # the whole point of a holdout is no optimization pressure on test, so we
    # never score losers on it. When unchanged, train-only scores are reused.
    if improved and test_set:
        current_test = score_prompt(name, current, metric_type, test_set)
        best_test = score_prompt(name, best, metric_type, test_set)
    else:
        current_test = current_train
        best_test = best_train

    overfit_risk = (best_train - best_test) > OVERFIT_GAP_THRESHOLD
    _log(f"  {'Winner' if improved else 'No improvement'}: "
         f"train={best_train:.2f} test={best_test:.2f} "
         f"(min lift {SIGNIFICANCE_THRESHOLD:+.2f}"
         f"{', OVERFIT' if overfit_risk else ''})")

    return {
        "name": name, "original": current, "best": best,
        "original_train_score": current_train, "original_test_score": current_test,
        "best_train_score": best_train, "best_test_score": best_test,
        "overfit_risk": overfit_risk,
        "improved": improved, "variants_tested": len(variants),
    }


# ── entry point ─────────────────────────────────────


def main() -> None:
    """CLI entry point. Evolve all prompts (Python + SKILL.md) and report results.

    --apply: patch source files directly, then review with git diff.
    """
    parser = argparse.ArgumentParser(
        description="Dev tool: evolve ALL prompt templates (Python constants + SKILL.md sections)"
    )
    parser.add_argument("--skills-dir", default=".claude/skills", help="Skills directory path")
    parser.add_argument("--variants", type=int, default=3, help="Number of variants per prompt")
    parser.add_argument("--apply", action="store_true", help="Patch source files with winners")
    parser.add_argument(
        "--rpm", type=int, default=DEFAULT_RPM,
        help=f"API requests-per-minute cap (default {DEFAULT_RPM}; raise on higher API tiers)",
    )
    args = parser.parse_args()

    _configure_rate_limit(args.rpm)
    _log(f"Rate limit: {args.rpm} RPM ({_limiter._min_interval:.2f}s between launches)")

    skills_dir = Path(args.skills_dir)
    scripts_dir = Path(__file__).parent
    skill_md_path = scripts_dir.parent / "SKILL.md"

    # collect eval data
    eval_data = collect_eval_data(skills_dir)
    if not eval_data:
        _log("ERROR: No eval data found (trigger_evals.json files)")
        sys.exit(1)
    _log(f"Collected {len(eval_data)} eval cases from {skills_dir}")

    # build catalog from both sources
    catalog = build_catalog(skill_md_path)
    _log(f"Catalog: {len(catalog)} prompts ({sum(1 for e in catalog if e.source_type == 'python_constant')} Python, "
         f"{sum(1 for e in catalog if e.source_type == 'markdown_section')} SKILL.md)")

    # evolve all prompts concurrently; rate limiter still governs API launches
    # across the nested executors, so cost is unchanged but wall-clock drops.
    results = _run_parallel(
        lambda e: evolve_prompt(e.name, e.default, e.metric_type,
                                eval_data, n_variants=args.variants),
        catalog,
    )

    # apply if requested
    if args.apply:
        py_source = scripts_dir / "optimize_description.py"
        apply_results(results, catalog, py_source, skill_md_path)

    # output summary
    summary = {
        "total_prompts": len(results),
        "improved": sum(1 for r in results if r["improved"]),
        "overfit_flagged": sum(1 for r in results if r.get("overfit_risk")),
        "results": [
            {
                "name": r["name"],
                "original_train_score": r["original_train_score"],
                "original_test_score": r["original_test_score"],
                "best_train_score": r["best_train_score"],
                "best_test_score": r["best_test_score"],
                "overfit_risk": r["overfit_risk"],
                "improved": r["improved"],
                "variants_tested": r["variants_tested"],
                "winning_prompt": r["best"] if r["improved"] else None,
            }
            for r in results
        ],
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":  # pragma: no cover — entry guard
    main()
