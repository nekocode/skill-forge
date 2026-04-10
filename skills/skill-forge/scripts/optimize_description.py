"""Eval-driven description optimizer.

Iteratively evaluate skill description trigger accuracy via claude --print subprocess,
train/test split to prevent overfitting, improve until optimal.
Result JSON to stdout, progress to stderr.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

# shared module from same directory
from shared import parse_frontmatter, run_subprocess

# ── data loading ─────────────────────────────────────


def load_skill(skill_path: Path) -> tuple[str, str]:
    """Read SKILL.md, parse name and description from YAML frontmatter.

    skill_path can be file or directory (directory auto-resolves to SKILL.md).
    Failure or missing returns ("", "").
    """
    if skill_path.is_dir():
        skill_path = skill_path / "SKILL.md"

    if not skill_path.is_file():
        return ("", "")

    try:
        content = skill_path.read_text()
    except OSError:
        return ("", "")

    fm = parse_frontmatter(content)
    if fm is None:
        return ("", "")

    return (fm.get("name", ""), fm.get("description", ""))


def load_evals(eval_path: Path) -> list[dict]:
    """Read trigger eval data in JSON array format.

    Failure returns empty list.
    """
    if not eval_path.is_file():
        return []

    try:
        data = json.loads(eval_path.read_text())
    except (json.JSONDecodeError, OSError):
        return []

    if not isinstance(data, list):
        return []

    return data


def split_train_test(
    evals: list[dict],
    ratio: float = 0.6,
    seed: int = 42,
) -> tuple[list[dict], list[dict]]:
    """Shuffle with fixed seed then split by ratio into train/test.

    20 items ratio=0.6 -> 12 train + 8 test.
    Empty list returns ([], []).
    """
    if not evals:
        return ([], [])

    shuffled = list(evals)
    random.Random(seed).shuffle(shuffled)

    split_index = int(len(shuffled) * ratio)
    return (shuffled[:split_index], shuffled[split_index:])


# ── Claude CLI wrapper ───────────────────────────────


def call_claude(prompt: str) -> str:
    """Call claude --print subprocess, return stdout.

    Timeout/file not found/OS error returns empty string.
    """
    return run_subprocess(["claude", "--print", "-p", prompt], timeout=30)


# ── evaluation logic ─────────────────────────────────


def evaluate_single(
    description: str,
    query: str,
    runs: int = 3,
) -> bool:
    """Trigger decision for a single query via majority vote.

    Call claude `runs` times. YES counts as triggered, others (NO/maybe/empty) as not.
    Majority YES -> True.
    """
    yes_count = 0
    prompt = (
        f"A skill has this description:\n\n{description}\n\n"
        f"User query: {query}\n\n"
        "Should this skill be triggered for this query? "
        "Answer only YES or NO."
    )
    for _ in range(runs):
        response = call_claude(prompt)
        # only explicit YES (case-insensitive) counts as triggered
        if response.strip().upper() == "YES":
            yes_count += 1

    # float division for strict majority (> half, not >=), do not change to //
    return yes_count > runs / 2


def evaluate_set(
    description: str,
    eval_set: list[dict],
) -> tuple[float, list[dict]]:
    """Score against entire eval set.

    Returns (accuracy 0.0-1.0, failure list).
    Each failure: {query, should_trigger, got}.
    """
    if not eval_set:
        return (1.0, [])

    failures: list[dict] = []
    correct = 0

    for item in eval_set:
        query = item["query"]
        should_trigger = item["should_trigger"]
        triggered = evaluate_single(description, query)

        if triggered == should_trigger:
            correct += 1
        else:
            failures.append({
                "query": query,
                "should_trigger": should_trigger,
                "got": triggered,
            })

    accuracy = correct / len(eval_set)
    return (accuracy, failures)


def improve_description(
    description: str,
    failures: list[dict],
) -> str:
    """Improve description via claude based on failure cases.

    No failures -> return original description (no claude call).
    Empty result or >300 chars -> fallback to original.
    """
    if not failures:
        return description

    # classify failures: false negatives (should trigger but didn't) and false positives (triggered but shouldn't)
    false_negatives = [f for f in failures if f["should_trigger"] is True]
    false_positives = [f for f in failures if f["should_trigger"] is False]

    prompt_parts = [
        "Improve this skill description for better triggering accuracy.",
        f"\nCurrent description:\n{description}",
    ]

    if false_negatives:
        queries = "\n".join(f"- {f['query']}" for f in false_negatives)
        prompt_parts.append(
            f"\nFalse negatives (should trigger but didn't):\n{queries}"
        )

    if false_positives:
        queries = "\n".join(f"- {f['query']}" for f in false_positives)
        prompt_parts.append(
            f"\nFalse positives (triggered but shouldn't):\n{queries}"
        )

    prompt_parts.append(
        "\nWrite an improved description under 250 characters. "
        "Output ONLY the new description text, nothing else."
    )

    result = call_claude("\n".join(prompt_parts))

    # prompt asks for 250 chars, but allow 300 tolerance — LLM may slightly exceed, soft fallback beats hard truncation
    if not result or len(result) > 300:
        return description

    return result


# ── optimization loop ────────────────────────────────


def run_optimization(
    description: str,
    train_set: list[dict],
    test_set: list[dict],
    max_iterations: int = 5,
) -> dict:
    """Iteratively optimize description, select best by test score.

    Each round: evaluate train -> evaluate test -> record best.
    Perfect train (1.0) -> early stop.
    Returns {best_description, best_test_score, iterations}.
    """
    best_description = description
    best_test_score = -1.0
    current_description = description

    iteration = 0
    for iteration in range(1, max_iterations + 1):
        _log(f"Iteration {iteration}/{max_iterations}")

        train_score, train_failures = evaluate_set(current_description, train_set)
        _log(f"  Train score: {train_score:.2f}")

        test_score, _ = evaluate_set(current_description, test_set)
        _log(f"  Test score:  {test_score:.2f}")

        if test_score > best_test_score:
            best_test_score = test_score
            best_description = current_description

        # perfect train -> stop (evaluate test before break to include final test score in best selection)
        if train_score >= 1.0:
            _log("  Perfect train score, stopping early.")
            break

        current_description = improve_description(
            current_description, train_failures
        )
        _log(f"  Improved: {current_description[:80]}...")

    return {
        "best_description": best_description,
        "best_test_score": best_test_score,
        "iterations": iteration,
    }


def _log(message: str) -> None:
    """Progress log output to stderr."""
    print(message, file=sys.stderr)


# ── entry point ──────────────────────────────────────


def main() -> None:
    """CLI entry point.

    Parse args, load data, run optimization, output JSON to stdout.
    Skill or evals load failure -> exit(1).
    """
    parser = argparse.ArgumentParser(
        description="Eval-driven skill description optimizer"
    )
    parser.add_argument("--skill-path", required=True, help="Path to SKILL.md or skill directory")
    parser.add_argument("--eval-set", required=True, help="Path to trigger_evals.json")
    parser.add_argument("--max-iterations", type=int, default=5, help="Max optimization iterations")
    args = parser.parse_args()

    # load skill
    name, original_description = load_skill(Path(args.skill_path))
    if not name or not original_description:
        _log("ERROR: Failed to load skill or missing name/description")
        sys.exit(1)

    # load evals
    evals = load_evals(Path(args.eval_set))
    if not evals:
        _log("ERROR: Failed to load eval set or empty")
        sys.exit(1)

    # 60/40 split
    train_set, test_set = split_train_test(evals, ratio=0.6, seed=42)
    _log(f"Loaded {len(evals)} evals: {len(train_set)} train, {len(test_set)} test")

    # run optimization
    result = run_optimization(
        original_description,
        train_set,
        test_set,
        max_iterations=args.max_iterations,
    )

    # output result JSON
    output = {
        "skill_name": name,
        "original_description": original_description,
        "best_description": result["best_description"],
        "best_test_score": result["best_test_score"],
        "iterations": result["iterations"],
    }
    print(json.dumps(output, indent=2))


if __name__ == "__main__":  # pragma: no cover — entry guard
    main()
