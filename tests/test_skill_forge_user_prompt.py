"""Full test suite for skill_forge_user_prompt.py."""

import json
from io import StringIO

import pytest

from skill_forge_user_prompt import _SKILL_RE, check_prompt, main


# ── TestCheckPrompt ────────────────────────────────────


class TestCheckPrompt:
    """Keyword matching logic."""

    @pytest.mark.parametrize("prompt", [
        # English
        "remember this workflow",
        "make a skill for this",
        "save this workflow please",
        "can you make it a skill",
        "REMEMBER THIS",
        "Make A Skill out of this",
        # Chinese
        "帮我做成 skill",
        "记住这个流程",
        # Japanese
        "このスキルを作って",
        "これを覚えて",
        # Korean
        "이걸 스킬로 만들어줘",
        "이걸 기억해",
        # Spanish
        "crear un skill para esto",
        "recuerda esto por favor",
        # French
        "créer un skill pour ça",
        "retiens ça",
        # German
        "skill erstellen bitte",
        "merk dir das",
    ])
    def test_matching_keywords(self, prompt: str) -> None:
        """contains trigger keyword -> return systemMessage."""
        result = check_prompt(prompt)
        assert "systemMessage" in result
        assert "skill-forge" in result["systemMessage"]

    @pytest.mark.parametrize("prompt", [
        "fix the login bug",
        "read the file",
        "",
        "tell me about skills in general",
        "what is a workflow",
    ])
    def test_non_matching(self, prompt: str) -> None:
        """no keyword -> empty dict."""
        result = check_prompt(prompt)
        assert result == {}


# ── TestMain ───────────────────────────────────────────


class TestMain:
    """stdin/stdout integration."""

    def test_matching_stdin(self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
        """stdin with keyword -> stdout outputs systemMessage JSON."""
        monkeypatch.setattr("sys.stdin", StringIO(json.dumps({"prompt": "remember this"})))
        main()
        output = json.loads(capsys.readouterr().out)
        assert "systemMessage" in output

    def test_non_matching_stdin(self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
        """stdin without keyword -> stdout outputs empty JSON."""
        monkeypatch.setattr("sys.stdin", StringIO(json.dumps({"prompt": "fix a bug"})))
        main()
        output = json.loads(capsys.readouterr().out)
        assert output == {}

    def test_malformed_json(self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
        """stdin invalid JSON -> output empty JSON, no crash."""
        monkeypatch.setattr("sys.stdin", StringIO("not json"))
        main()
        output = json.loads(capsys.readouterr().out)
        assert output == {}

    def test_missing_prompt_key(self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
        """stdin JSON missing prompt field -> output empty JSON."""
        monkeypatch.setattr("sys.stdin", StringIO(json.dumps({"other": "data"})))
        main()
        output = json.loads(capsys.readouterr().out)
        assert output == {}


# ── TestKeywordsPattern ────────────────────────────────


class TestKeywordsPattern:
    """_SKILL_RE precompiled regex boundary cases."""

    def test_pattern_is_case_insensitive(self) -> None:
        """precompiled regex has IGNORECASE flag."""
        import re
        assert _SKILL_RE.flags & re.IGNORECASE

    def test_partial_match_within_sentence(self) -> None:
        """keyword in middle of sentence also matches."""
        result = check_prompt("Could you save this workflow for later?")
        assert "systemMessage" in result


