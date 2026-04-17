"""Eval-driven description optimizer.

Iteratively evaluate skill description trigger accuracy via claude --print subprocess,
train/test split to prevent overfitting, improve until optimal.
Result JSON to stdout, progress to stderr.

DSPy-inspired improvements:
- Structured failure analysis (FP/FN classification with directional improvement prompts)
- Context-rich evaluation prompts (undertrigger bias, complex-task-only semantics)
- Per-round state persistence (opt_state.json: round history, convergence detection)
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

# shared module from same directory
from shared import log_stderr as _log, parse_frontmatter, run_subprocess

# model used for eval/improve calls — change to test different models
CLAUDE_MODEL = "claude-sonnet-4-6"

# ── prompt templates (optimized via self_evolve.py dev tool) ──
# Developer runs self_evolve.py to find better variants, then updates these constants.
# Placeholders: {description}, {query} are filled at call site.

EVALUATE_TEMPLATE = (
    "You are a skill activation filter for Claude Code. Your job: decide if a user query "
    "warrants invoking a specialized multi-step skill.\n\nSkill "
    "description:\n{description}\n\nUser query:\n{query}\n\nAsk yourself:\n1. Does the "
    "query require **coordinated, sequential actions** — not just a single operation?\n2. "
    "Would a developer expect this to take **multiple distinct phases** to complete?\n3. "
    "Does the skill description **closely match the problem being solved**, not just "
    "share keywords?\n\nIf all three are YES, output YES. Otherwise output NO.\n\nBias "
    "toward NO — a falsely triggered skill is more disruptive than a missed one."
)

IMPROVE_FN_GUIDANCE = (
    "Fix: the description failed to match these queries. Analyze what they have in common "
    "and add trigger patterns that capture that shared intent. Strategies:\n"
    "- Add 'Even if the user just says X, use this skill when they likely need Y' for "
    "cases where users understate their needs.\n"
    "- Name specific artifacts or actions from the missed queries (file types, commands, "
    "tools) so the description covers real phrasing, not just abstract concepts.\n"
    "- Front-load the most distinctive trigger keywords — Claude may truncate from the end."
)

IMPROVE_FP_GUIDANCE = (
    "Fix: these queries triggered the skill but should not have. Identify what made "
    "the description too broad. Strategies:\n"
    "- Add a 'Do NOT use when' clause listing the specific tasks that were false positives "
    "(e.g., 'Do NOT use for simple file reads, single-step edits, or code explanations').\n"
    "- Replace vague verbs ('manage', 'handle', 'work with') with precise multi-step "
    "scenarios that only match when the full workflow is needed.\n"
    "- If the FP queries share a keyword with the description, qualify that keyword "
    "with a condition (e.g., 'deploy' → 'deploy with rollback and health checks')."
)


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
    except OSError:  # pragma: no cover — requires OS-level permission denial after is_file() passes
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


def _call_claude_once(prompt: str) -> str:
    """Single claude --print invocation; empty on failure.

    cwd=/tmp keeps the CLI from auto-loading project CLAUDE.md and leaking
    house style into the response.
    """
    cmd = ["claude", "--model", CLAUDE_MODEL, "--print", "-p", prompt]
    return run_subprocess(cmd, timeout=60, cwd="/tmp")


def call_claude(prompt: str) -> str:
    """Call claude --print with a 2s-backoff retry on empty response."""
    result = _call_claude_once(prompt)
    if result:
        return result
    time.sleep(2)
    return _call_claude_once(prompt)


# ── DSPy-inspired data structures ───────────────────


@dataclass
class RoundRecord:
    """Per-round optimization metrics for state persistence."""

    round: int
    description: str
    train_score: float
    test_score: float
    false_positive_count: int
    false_negative_count: int


@dataclass
class OptState:
    """Persistent optimization state across runs."""

    skill_name: str
    best_score: float
    best_description: str
    current_round: int
    converged: bool
    rounds: list[RoundRecord]


def load_opt_state(path: Path) -> OptState | None:
    """Load opt state from JSON. Missing/corrupt/schema-mismatch returns None.

    Not called from main() — provided for external callers (SKILL.md improve mode
    inspect/resume, CLI status command). Optimizer always starts fresh per run.
    """
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None

    if not isinstance(data, dict) or "skill_name" not in data:
        return None

    try:
        rounds = [RoundRecord(**r) for r in data.get("rounds", [])]
        return OptState(
            skill_name=data["skill_name"],
            best_score=data["best_score"],
            best_description=data["best_description"],
            current_round=data["current_round"],
            converged=data["converged"],
            rounds=rounds,
        )
    except (KeyError, TypeError):
        return None


def save_opt_state(state: OptState, path: Path) -> None:
    """Persist opt state. Auto-creates parent directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(state), indent=2))
    _log(f"  State saved: round={state.current_round} best={state.best_score:.2f} path={path}")


def classify_failures(failures: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split failures into (false_positives, false_negatives).

    FP: should_trigger=False but got=True (description too broad).
    FN: should_trigger=True but got=False (description misses scenario).
    """
    false_positives = [f for f in failures if f["should_trigger"] is False]
    false_negatives = [f for f in failures if f["should_trigger"] is True]
    return (false_positives, false_negatives)


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
    prompt = EVALUATE_TEMPLATE.format(description=description, query=query)
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
    *,
    classified: tuple[list[dict], list[dict]] | None = None,
) -> str:
    """Improve description via claude based on failure cases.

    No failures -> return original description (no claude call).
    Empty result or >300 chars -> fallback to original.
    classified: pre-computed (false_positives, false_negatives) to avoid re-classification.
    """
    if not failures:
        return description

    false_positives, false_negatives = classified or classify_failures(failures)

    prompt_parts = [
        "Improve this skill description for better trigger accuracy.",
        f"\nCurrent description:\n{description}",
    ]

    # FN direction: description misses scenarios → add concrete trigger patterns
    if false_negatives:
        queries = "\n".join(f"- {f['query']}" for f in false_negatives)
        prompt_parts.append(
            f"\nFalse negatives — missed these scenarios (should trigger but did not):\n{queries}\n"
            f"{IMPROVE_FN_GUIDANCE}"
        )

    # FP direction: description too broad → add DO NOT use clauses
    if false_positives:
        queries = "\n".join(f"- {f['query']}" for f in false_positives)
        prompt_parts.append(
            f"\nFalse positives — triggered when it should not:\n{queries}\n"
            f"{IMPROVE_FP_GUIDANCE}"
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
    state_path: Path | None = None,
    skill_name: str = "",
) -> dict:
    """Iteratively optimize description, select best by test score.

    Each round: evaluate train -> evaluate test -> record best -> persist state.
    Perfect train (1.0) -> early stop.
    state_path: when provided, saves OptState after each round for history/convergence tracking.
    Returns {best_description, best_test_score, iterations, rounds, converged}.
    """
    best_description = description
    best_test_score = -1.0
    current_description = description
    rounds: list[RoundRecord] = []
    converged = False

    iteration = 0
    for iteration in range(1, max_iterations + 1):
        _log(f"Iteration {iteration}/{max_iterations}")

        train_score, train_failures = evaluate_set(current_description, train_set)
        _log(f"  Train score: {train_score:.2f}")

        test_score, _ = evaluate_set(current_description, test_set)
        _log(f"  Test score:  {test_score:.2f}")

        # DSPy-inspired: track FP/FN counts per round for structured history
        false_positives, false_negatives = classify_failures(train_failures)
        round_record = RoundRecord(
            round=iteration,
            description=current_description,
            train_score=train_score,
            test_score=test_score,
            false_positive_count=len(false_positives),
            false_negative_count=len(false_negatives),
        )
        rounds.append(round_record)

        _log(f"  FP: {round_record.false_positive_count}  FN: {round_record.false_negative_count}")

        if test_score > best_test_score:
            best_test_score = test_score
            best_description = current_description

        # convergence: computed unconditionally, used by both state persistence and early-stop
        converged = train_score >= 1.0

        # persist state after each round (partial runs still capture history)
        if state_path is not None:
            save_opt_state(
                OptState(
                    skill_name=skill_name,
                    best_score=best_test_score,
                    best_description=best_description,
                    current_round=iteration,
                    converged=converged,
                    rounds=rounds,
                ),
                state_path,
            )

        # perfect train -> stop (evaluate test before break to include final test score in best selection)
        if converged:
            _log("  Perfect train score, stopping early.")
            break

        current_description = improve_description(
            current_description, train_failures,
            classified=(false_positives, false_negatives),
        )
        _log(f"  Improved: {current_description[:80]}...")

    return {
        "best_description": best_description,
        "best_test_score": best_test_score,
        "iterations": iteration,
        "rounds": [asdict(r) for r in rounds],
        "converged": converged,
    }


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
    skill_path = Path(args.skill_path)
    name, original_description = load_skill(skill_path)
    if not name or not original_description:
        _log("ERROR: Failed to load skill or missing name/description")
        sys.exit(1)

    # derive state path: <skill_dir>/.opt/opt_state.json
    skill_dir = skill_path if skill_path.is_dir() else skill_path.parent
    state_path = skill_dir / ".opt" / "opt_state.json"

    # load evals
    evals = load_evals(Path(args.eval_set))
    if not evals:
        _log("ERROR: Failed to load eval set or empty")
        sys.exit(1)

    # 60/40 split
    train_set, test_set = split_train_test(evals, ratio=0.6, seed=42)
    _log(f"Loaded {len(evals)} evals: {len(train_set)} train, {len(test_set)} test")

    # run optimization with state persistence
    result = run_optimization(
        original_description,
        train_set,
        test_set,
        max_iterations=args.max_iterations,
        state_path=state_path,
        skill_name=name,
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
