"""Self-evolution meta-optimizer for prompt templates (dev tool).

Applies the DSPy optimization pattern to ALL prompts in the project:
- Python constants in optimize_description.py (evaluate/improve templates)
- Markdown sections in SKILL.md (description rules, eval query guidance, evaluator criteria)

Developer workflow:
  1. Accumulate eval data (trigger_evals.json) from /improve sessions
  2. Run: python self_evolve.py --skills-dir .claude/skills [--apply]
  3. Review: git diff
  4. Test, commit, release

Usage:
  python self_evolve.py --skills-dir .claude/skills [--variants 3] [--apply] [--rpm 46]

API calls run concurrently, throttled by a shared RPM budget. Default 46 RPM fits
a Tier-1 Anthropic account (50 RPM cap). Raise `--rpm` on higher tiers for faster
runs.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, TypeVar

# Multi-sample mean fights Claude's stochastic scoring (same prompt, different score
# across runs — observed ±0.50 on guidance scorers). k=2 reduces variance by ~√2;
# higher k blows the ~1h API budget.
SAMPLE_RUNS = 2
# Minimum lift for a variant to beat baseline. Empirically, noise produces ±0.10-0.15
# swings; any lift smaller than this is indistinguishable from resampling noise.
SIGNIFICANCE_THRESHOLD = 0.15

# Default Tier-1 safe rate: 46 RPM → 1.304s between launches. Leaves 4 RPM headroom
# under the 50 RPM cap for retries and burst tolerance. Override via --rpm.
DEFAULT_RPM = 46

# PromptBreeder-lite: rotating directives to push the generator out of local paraphrase.
# One style is injected per variant so `n` variants explore `n` different axes.
_THINKING_STYLES: tuple[str, ...] = (
    "rewrite as if instructing a skeptical senior engineer who won't follow vague advice",
    "rewrite as a terse spec a compiler could parse — strip all hedging",
    "rewrite emphasizing the failure modes this prompt prevents, not the behavior it enables",
    "rewrite as a checklist a reviewer could mechanically apply",
    "rewrite by starting from the required output format and working backwards to the instruction",
    "rewrite as if the reader has never seen this task type before",
)

from optimize_description import (
    EVALUATE_TEMPLATE,
    IMPROVE_FN_GUIDANCE,
    IMPROVE_FP_GUIDANCE,
    _call_claude_once as _raw_call_claude,
)
from shared import log_stderr as _log


# ── rate limiter + parallel map ─────────────────────
# All API calls funnel through the `call_claude` wrapper below, which blocks
# until `_min_launch_interval` has elapsed since the previous launch across
# ALL threads — single source of truth for the RPM budget.

_T = TypeVar("_T")
_U = TypeVar("_U")

_rate_lock = threading.Lock()
_last_launch_time = 0.0
_min_launch_interval = 60.0 / DEFAULT_RPM


def _configure_rate_limit(rpm: int) -> None:
    """Set the inter-launch floor in seconds from the target RPM. Called once from main()."""
    global _min_launch_interval
    _min_launch_interval = 60.0 / max(rpm, 1)


def _throttle() -> None:
    """Block until the minimum inter-launch gap has elapsed.

    Only serializes call-start timestamps; the underlying subprocess work proceeds
    concurrently once launched. Uses `time.sleep` so tests can mock it out.
    """
    global _last_launch_time
    with _rate_lock:
        now = time.monotonic()
        wait = _min_launch_interval - (now - _last_launch_time)
        if wait > 0:
            time.sleep(wait)
        _last_launch_time = time.monotonic()


def call_claude(prompt: str) -> str:
    """Throttled claude --print, with one throttled retry on empty response.

    Owning the retry here (instead of inside `optimize_description.call_claude`)
    keeps every API launch — primary AND retry — inside the RPM budget. The
    module-level binding is the patch target for tests.
    """
    _throttle()
    result = _raw_call_claude(prompt)
    if result:
        return result
    _throttle()
    return _raw_call_claude(prompt)


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


def replace_markdown_section(content: str, heading: str, new_body: str) -> str:
    """Replace the body of a markdown section, keeping the heading intact."""
    pattern = re.compile(rf'^(#{{2,4}}\s+{re.escape(heading)}[ \t]*\n)', re.MULTILINE)
    match = pattern.search(content)
    if not match:
        return content

    level = len(re.match(r'^(#{2,4})', match.group(1)).group(1))
    heading_end = match.end()

    next_pattern = re.compile(rf'^#{{{1},{level}}}\s+', re.MULTILINE)
    next_match = next_pattern.search(content, heading_end)

    if next_match:
        return content[:heading_end] + "\n" + new_body + "\n\n" + content[next_match.start():]
    return content[:heading_end] + "\n" + new_body + "\n"


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


def score_evaluator_prompt(
    template: str,
    eval_data: list[dict],
) -> float:
    """Score an evaluate prompt template against labeled eval data.

    Returns accuracy 0.0-1.0. Single call per case (no majority vote) for speed.
    Cases are evaluated in parallel; the global rate limiter gates API invocation.
    """
    if not eval_data:
        return 0.0

    # cap to avoid unbounded API calls on large eval sets
    capped = eval_data[:20]

    def _judge(item: dict) -> bool:
        prompt = template.format(
            description="A multi-step workflow skill for complex tasks",
            query=item.get("query", ""),
        )
        response = call_claude(prompt)
        predicted = response.strip().upper() == "YES"
        return predicted == item.get("should_trigger", False)

    results = _run_parallel(_judge, capped)
    return sum(1 for r in results if r) / len(capped)


def score_guidance_prompt(guidance: str, guidance_type: str, eval_data: list[dict]) -> float:
    """Score a guidance prompt by checking structural quality of improvement output."""
    mock_desc = "Use when deploying code to production environments"
    is_fn = guidance_type == "improve_fn"
    # filter by type first, then slice — pre-slicing may exclude all matching cases
    cases = [item for item in eval_data if item.get("should_trigger", False) == is_fn][:3]
    failures = "\n".join(f"- {c['query']}" for c in cases)
    label = "False negatives — missed" if is_fn else "False positives — triggered incorrectly"

    result = call_claude(
        f"Improve this skill description.\n\nCurrent: {mock_desc}\n\n"
        f"{label}:\n{failures}\n{guidance}\n\n"
        "Write an improved description under 250 characters. Output ONLY the new description."
    )
    if not result:
        return 0.0

    # Scoring weights: 4 criteria at 0.25 each = 1.0 max
    #   0.25: produced non-empty output
    #   0.25: length within limit (300 chars)
    #   0.25: contains expected trigger/exclusion phrases
    #   0.25: for FN guidance: expanded description; for FP guidance: has "when" clause
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


def score_instruction_quality(instruction: str, eval_data: list[dict]) -> float:
    """Score a SKILL.md instruction section by testing if Claude follows it well.

    Gives Claude the instruction + a mock task, checks output against key criteria.
    """
    result = call_claude(
        "You are writing a skill trigger description following these rules:\n\n"
        f"{instruction}\n\n"
        "Task: write a trigger description for a skill that handles 'database migration "
        "with schema backup, migration script execution, data validation, and seed update'.\n\n"
        "Output ONLY the description text, nothing else."
    )
    if not result:
        return 0.0

    # Scoring weights: 6 criteria totaling 1.0 max
    #   0.15: produced output
    #   0.20: length within limit (250 chars)
    #   0.15: mentions domain keywords (schema/migration/backup/validation)
    #   0.15: has pushy coverage phrases (even if/even when)
    #   0.15: has exclusion phrases (do not/not use)
    #   0.10: avoids vague verbs (manage/handle/work with/deal with)
    #   0.10: domain keyword in first 50 chars (specificity bonus)
    lower = result.lower()
    score = 0.15
    if len(result) <= 250:
        score += 0.20
    if any(w in lower for w in ("schema", "migration", "backup", "validation")):
        score += 0.15
    if "even if" in lower or "even when" in lower:
        score += 0.15
    if "do not" in lower or "not use" in lower:
        score += 0.15
    if not any(w in lower for w in ("manage", "handle", "work with", "deal with")):
        score += 0.10
    if any(w in lower[:50] for w in ("migrat", "schema", "database", "deploy")):
        score += 0.10
    return score


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

    A variant replaces the baseline only if its score exceeds baseline by at least
    SIGNIFICANCE_THRESHOLD. This rejects pseudo-improvements caused by resampling noise.
    """
    _log(f"\n=== Evolving: {name} ===")
    current_score = score_prompt(name, current, metric_type, eval_data)
    _log(f"  Current score: {current_score:.2f} (mean of {SAMPLE_RUNS} samples)")
    best, best_score = current, current_score

    variants = generate_variants(current, name, n=n_variants)
    _log(f"  Generated {len(variants)} variants")
    # score all variants concurrently; rate limiter still serializes API launches
    variant_scores = _run_parallel(
        lambda v: score_prompt(name, v, metric_type, eval_data),
        variants,
    )
    for i, (variant, variant_score) in enumerate(zip(variants, variant_scores)):
        margin = variant_score - current_score
        _log(f"  Variant {i + 1}: {variant_score:.2f} (Δ={margin:+.2f})")
        # both clauses are essential: must beat the running best AND clear the
        # significance bar against the original baseline (stops drift via tiny steps).
        if variant_score > best_score and margin > SIGNIFICANCE_THRESHOLD:
            best_score, best = variant_score, variant

    improved = best != current
    _log(f"  {'Winner' if improved else 'No improvement'}: "
         f"{best_score:.2f} (min lift {SIGNIFICANCE_THRESHOLD:+.2f})")
    return {"name": name, "original": current, "best": best,
            "original_score": current_score, "best_score": best_score,
            "improved": improved, "variants_tested": len(variants)}


# ── source patching (--apply) ───────────────────────


def apply_results(results: list[dict], catalog: list[PromptEntry],
                  py_source: Path, md_source: Path) -> int:
    """Apply winning prompts to their source files. Returns patch count."""
    patched = 0

    # group results by source type
    entry_map = {e.name: e for e in catalog}
    py_content = py_source.read_text() if py_source.is_file() else ""
    md_content = md_source.read_text() if md_source.is_file() else ""

    for result in results:
        if not result["improved"]:
            continue

        entry = entry_map.get(result["name"])
        if not entry:
            continue

        if entry.source_type == "python_constant":
            new_py = _patch_python_constant(py_content, entry.source_key, result["best"])
            if new_py != py_content:
                py_content = new_py
                patched += 1
                _log(f"  Patched Python: {entry.source_key}")

        elif entry.source_type == "markdown_section":
            new_md = replace_markdown_section(md_content, entry.source_key, result["best"])
            if new_md != md_content:
                md_content = new_md
                patched += 1
                _log(f"  Patched SKILL.md: {entry.source_key}")

    if patched > 0:
        if py_source.is_file():
            py_source.write_text(py_content)
        if md_source.is_file():
            md_source.write_text(md_content)
        _log(f"\n{patched} prompt(s) patched. Review: git diff")

    return patched


def _patch_python_constant(content: str, const_name: str, new_value: str) -> str:
    """Replace a Python string constant written as NAME = (\\n...\\n) with new value.

    Only matches parenthesized multiline format. Single-line or triple-quote formats
    are NOT supported — the function logs a warning and returns content unchanged.
    """
    pattern = re.compile(
        rf'^{const_name} = \(\n(.*?)\n\)',
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(content)
    if not match:
        _log(f"  WARNING: {const_name} not found in source")
        return content

    formatted = _format_python_constant(const_name, new_value)
    return content[:match.start()] + formatted + content[match.end():]


def _format_python_constant(name: str, value: str) -> str:
    """Format a string value as a Python parenthesized string constant.

    Escapes backslash/quote/CR/LF/TAB so literal control chars in the generated variant
    don't produce unterminated string literals when splicing into source.
    """
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    lines: list[str] = []
    remaining = escaped
    while remaining:
        if len(remaining) <= 85:
            lines.append(remaining)
            break
        split_at = remaining.rfind(" ", 0, 85)
        split_at = split_at + 1 if split_at != -1 else 85
        lines.append(remaining[:split_at])
        remaining = remaining[split_at:]

    if len(lines) == 1:
        return f'{name} = (\n    "{lines[0]}"\n)'
    parts = [f'{name} = ('] + [f'    "{ln}"' for ln in lines] + [")"]
    return "\n".join(parts)


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
    _log(f"Rate limit: {args.rpm} RPM ({_min_launch_interval:.2f}s between launches)")

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
        "results": [
            {
                "name": r["name"],
                "original_score": r["original_score"],
                "best_score": r["best_score"],
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
