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
  python self_evolve.py --skills-dir .claude/skills [--variants 3] [--apply]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from optimize_description import (
    EVALUATE_TEMPLATE,
    IMPROVE_FN_GUIDANCE,
    IMPROVE_FP_GUIDANCE,
    call_claude,
)
from shared import log_stderr as _log


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
    ("Description writing rules (directly affects triggering accuracy)", "instruction_quality"),
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
    """
    if not eval_data:
        return 0.0

    # cap to avoid unbounded API calls on large eval sets
    capped = eval_data[:20]
    correct = 0
    for item in capped:
        query = item.get("query", "")
        expected = item.get("should_trigger", False)

        prompt = template.format(
            description="A multi-step workflow skill for complex tasks",
            query=query,
        )
        response = call_claude(prompt)
        predicted = response.strip().upper() == "YES"

        if predicted == expected:
            correct += 1

        time.sleep(1)  # rate-limit API calls

    return correct / len(capped)


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
    time.sleep(1)  # rate-limit API calls
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
    time.sleep(1)  # rate-limit API calls
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


def score_prompt(name: str, value: str, metric_type: str, eval_data: list[dict]) -> float:
    """Route to the appropriate scoring function based on metric_type."""
    if metric_type == "evaluator_accuracy":
        return score_evaluator_prompt(value, eval_data)
    if metric_type == "guidance_quality":
        guidance_type = name  # "improve_fn" or "improve_fp"
        return score_guidance_prompt(value, guidance_type, eval_data)
    if metric_type == "instruction_quality":
        return score_instruction_quality(value, eval_data)
    return 0.0


# ── variant generation ──────────────────────────────


def generate_variants(
    current: str,
    prompt_name: str,
    n: int = 3,
) -> list[str]:
    """Generate N prompt variants via Claude.

    Returns list of variant strings (may be < n if Claude returns empty/too-long).
    """
    variants: list[str] = []

    for i in range(n):
        generation_prompt = (
            f"You are optimizing a prompt template used in an AI skill trigger system.\n\n"
            f"Prompt name: {prompt_name}\n"
            f"Current prompt:\n{current}\n\n"
            f"Generate variant #{i + 1} of this prompt that might perform better.\n"
            "Rules:\n"
            "- Keep the same placeholders (e.g., {{description}}, {{query}}) if present\n"
            "- Maintain the same output format requirement (YES/NO, or description text)\n"
            "- Try a different angle: different framing, emphasis, or reasoning cues\n"
            "- Keep similar length (within 50% of original)\n\n"
            "Output ONLY the new prompt text, nothing else."
        )
        result = call_claude(generation_prompt)
        # floor prevents empty `current` from rejecting all variants (0*2=0)
        if result and len(result) < max(len(current) * 2, 500):
            variants.append(result)
        time.sleep(1)  # rate-limit API calls

    return variants


# ── evolution loop ──────────────────────────────────


def evolve_prompt(name: str, current: str, metric_type: str,
                  eval_data: list[dict], n_variants: int = 3) -> dict:
    """Meta-optimize a single prompt. Returns result dict with winner."""
    _log(f"\n=== Evolving: {name} ===")
    current_score = score_prompt(name, current, metric_type, eval_data)
    _log(f"  Current score: {current_score:.2f}")
    best, best_score = current, current_score

    variants = generate_variants(current, name, n=n_variants)
    _log(f"  Generated {len(variants)} variants")
    for i, variant in enumerate(variants):
        variant_score = score_prompt(name, variant, metric_type, eval_data)
        _log(f"  Variant {i + 1}: {variant_score:.2f}")
        if variant_score > best_score:
            best_score, best = variant_score, variant

    improved = best != current
    _log(f"  {'Winner' if improved else 'No improvement'}: {best_score:.2f}")
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
    """Format a string value as a Python parenthesized string constant."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
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
    args = parser.parse_args()

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

    # evolve each prompt
    results: list[dict] = []
    for entry in catalog:
        result = evolve_prompt(entry.name, entry.default, entry.metric_type,
                               eval_data, n_variants=args.variants)
        results.append(result)

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
