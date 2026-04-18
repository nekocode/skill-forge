"""Record session evaluator score → state.json.

The evaluator runs in-session (Claude scores draft against rubric in SKILL.md).
The score lives only in chat output; the PostToolUse hook that upserts the
registry on SKILL.md write has no access to it. This script bridges them:
Claude calls it before Write, the hook consumes `pending_eval_score` from
state.json on the next SKILL.md write and clears it.

Usage: python3 record_eval_score.py <score 0-8>
"""

from __future__ import annotations

import sys

from shared import PENDING_EVAL_SCORE_KEY, load_state, save_state

MAX_SCORE = 8


def record_score(score: int) -> None:
    """Persist pending eval score in workspace state.

    Hook reads the key on next SKILL.md write and clears it.
    Out-of-range raises ValueError to fail loudly rather than silently mis-record.
    """
    if not 0 <= score <= MAX_SCORE:
        raise ValueError(f"score must be 0..{MAX_SCORE}, got {score}")

    state = load_state()
    state[PENDING_EVAL_SCORE_KEY] = score
    save_state(state)


def main(argv: list[str] | None = None) -> None:
    if argv is None:
        argv = sys.argv[1:]
    if len(argv) != 1:
        print("Usage: record_eval_score.py <score 0-8>")
        sys.exit(1)
    try:
        score = int(argv[0])
    except ValueError:
        print(f"score must be an integer 0..{MAX_SCORE}, got {argv[0]!r}")
        sys.exit(1)

    try:
        record_score(score)
    except ValueError as e:
        print(str(e))
        sys.exit(1)
    print(f"[skill-forge] Recorded eval score: {score}/{MAX_SCORE}")


if __name__ == "__main__":  # pragma: no cover — entry guard
    main()
