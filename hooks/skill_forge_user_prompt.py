#!/usr/bin/env python3
"""
UserPromptSubmit hook: keyword matching to trigger skill creation prompt.

Reads stdin JSON (hook protocol), checks whether prompt contains skill-creation
keywords. On match, outputs systemMessage guiding Claude to proactively offer
skill creation after task completion.
"""

import json
import re
import sys

# multilingual trigger keywords, precompiled to avoid per-call overhead
_SKILL_RE = re.compile(
    # English
    r"(remember this|make.*skill|save.*workflow|skill for this"
    # Chinese
    r"|做成.*skill|记住这个"
    # Japanese
    r"|スキルを作|スキルにして|これを覚えて|ワークフローを保存"
    # Korean
    r"|스킬로 만들|스킬을 만들|이걸 기억|워크플로우를 저장"
    # Spanish
    r"|crear.*skill|guardar.*workflow|recuerda esto"
    # French
    r"|créer.*skill|sauvegarder.*workflow|retiens ça"
    # German
    r"|skill erstellen|workflow speichern|merk dir das)",
    re.IGNORECASE,
)


def check_prompt(prompt: str) -> dict:
    """Check whether prompt contains skill-creation keywords.

    Match -> {"systemMessage": "..."}.
    No match -> {}.
    """
    if _SKILL_RE.search(prompt):
        return {
            "systemMessage": (
                "[skill-forge] User appears to want a skill created from this workflow. "
                "When the task completes, proactively offer to run /skill-forge create <prompt>."
            )
        }
    return {}


def main() -> None:
    """Entry point. Read stdin JSON, check keywords, output result JSON."""
    try:
        data = json.loads(sys.stdin.read())
    except Exception:
        print(json.dumps({}))
        return

    prompt = data.get("prompt", "")
    result = check_prompt(prompt)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
