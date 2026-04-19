"""Tests for hook_draft_inject.py.

Exercises the three hook modes (prompt / pretool / posttool) plus the
empty-draft and missing-draft quiet paths. conftest's env fixture already
redirects workspace_dir() to tmp_path/.skill-forge/, so we just write
files there and call the functions.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import hook_draft_inject as mod
from shared import draft_file, insights_file


# ── helpers ─────────────────────────────────────────────────────────


def _write_draft(tmp_path: Path, content: str) -> Path:
    path = draft_file(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


# ── _read_nonempty ──────────────────────────────────────────────────


def test_read_nonempty_missing(tmp_path):
    assert mod._read_nonempty(tmp_path / "nope.md") is None


def test_read_nonempty_empty_string(tmp_path):
    p = tmp_path / "empty.md"
    p.write_text("")
    assert mod._read_nonempty(p) is None


def test_read_nonempty_whitespace_only(tmp_path):
    p = tmp_path / "ws.md"
    p.write_text("   \n\t\n")
    assert mod._read_nonempty(p) is None


def test_read_nonempty_content(tmp_path):
    p = tmp_path / "c.md"
    p.write_text("body\n")
    assert mod._read_nonempty(p) == "body\n"


# ── _head ───────────────────────────────────────────────────────────


def test_head_truncates():
    text = "\n".join(str(i) for i in range(10))
    assert mod._head(text, 3) == "0\n1\n2"


def test_head_shorter_than_limit():
    assert mod._head("a\nb", 10) == "a\nb"


# ── inject_prompt ───────────────────────────────────────────────────


def test_inject_prompt_no_draft(tmp_path):
    assert mod.inject_prompt(tmp_path, lines=40) == ""


def test_inject_prompt_empty_draft(tmp_path):
    _write_draft(tmp_path, "")
    assert mod.inject_prompt(tmp_path, lines=40) == ""


def test_inject_prompt_with_draft(tmp_path):
    _write_draft(tmp_path, "# my-skill\nline2\nline3\n")
    result = mod.inject_prompt(tmp_path, lines=2)
    assert "ACTIVE SKILL DRAFT" in result
    assert "# my-skill\nline2" in result
    assert "line3" not in result  # truncated
    assert str(insights_file(tmp_path)) in result


# ── inject_pretool ──────────────────────────────────────────────────


def test_inject_pretool_no_draft(tmp_path):
    assert mod.inject_pretool(tmp_path, lines=5) == ""


def test_inject_pretool_returns_head_only(tmp_path):
    _write_draft(tmp_path, "a\nb\nc\nd\ne\nf\n")
    result = mod.inject_pretool(tmp_path, lines=3)
    assert result == "a\nb\nc"
    # pretool mode should NOT include the prompt wrapper text
    assert "ACTIVE" not in result


# ── inject_posttool ─────────────────────────────────────────────────


def test_inject_posttool_no_draft(tmp_path):
    assert mod.inject_posttool(tmp_path) == ""


def test_inject_posttool_with_draft(tmp_path):
    _write_draft(tmp_path, "draft body\n")
    result = mod.inject_posttool(tmp_path)
    assert "Update" in result
    assert str(draft_file(tmp_path)) in result


# ── main CLI ────────────────────────────────────────────────────────


def test_main_prompt_dispatch(tmp_path, monkeypatch, capsys):
    _write_draft(tmp_path, "# skill\nphase\n")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    rc = mod.main(["--mode", "prompt"])
    captured = capsys.readouterr()
    assert rc == 0
    assert "ACTIVE SKILL DRAFT" in captured.out


def test_main_pretool_default_lines(tmp_path, monkeypatch, capsys):
    _write_draft(tmp_path, "\n".join(f"L{i}" for i in range(20)))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    mod.main(["--mode", "pretool"])
    captured = capsys.readouterr()
    # default pretool lines=5 → first 5
    assert "L4" in captured.out
    assert "L5" not in captured.out


def test_main_posttool(tmp_path, monkeypatch, capsys):
    _write_draft(tmp_path, "body")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    mod.main(["--mode", "posttool"])
    assert "Update" in capsys.readouterr().out


def test_main_silent_when_no_draft(tmp_path, monkeypatch, capsys):
    # No draft written — all three modes stay silent.
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    for mode in ("prompt", "pretool", "posttool"):
        mod.main(["--mode", mode])
        assert capsys.readouterr().out == ""


def test_main_requires_mode():
    with pytest.raises(SystemExit):
        mod.main([])


def test_project_dir_env_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    assert mod._project_dir() == tmp_path


def test_project_dir_cwd_fallback(monkeypatch, tmp_path):
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    assert mod._project_dir() == Path.cwd()
