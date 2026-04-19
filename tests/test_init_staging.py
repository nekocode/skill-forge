"""Tests for init_staging.py."""

from __future__ import annotations

from pathlib import Path

import pytest

import init_staging as mod
from shared import staging_dir


# ── validate_name ───────────────────────────────────────────────────


@pytest.mark.parametrize("name", [
    "foo",
    "foo-bar",
    "a1",
    "generate-endpoint",
    "seed-db-v2",
])
def test_validate_name_accepts(name):
    mod.validate_name(name)


@pytest.mark.parametrize("name", [
    "",
    "Foo",
    "foo_bar",
    "foo bar",
    "-foo",
    "foo-",
    "foo--bar",
    "123",
    "foo.bar",
])
def test_validate_name_rejects(name):
    with pytest.raises(ValueError):
        mod.validate_name(name)


# ── prepare: create mode ────────────────────────────────────────────


def test_prepare_create_writes_skeleton(tmp_path):
    target = mod.prepare("my-skill", project_dir=tmp_path)
    assert target == staging_dir(tmp_path) / "my-skill"
    assert target.is_dir()
    skill_md = target / "SKILL.md"
    assert skill_md.is_file()
    content = skill_md.read_text()
    # Frontmatter anchors + three-clause stubs + empty section headers
    # — what Claude fills via Edit rather than authoring from scratch.
    assert "name: my-skill" in content
    assert "Use when" in content and "Do NOT use when" in content
    assert "## Prerequisites" in content
    assert "## Steps" in content
    assert "## Verification" in content
    assert "## Notes" in content


def test_prepare_create_wipes_existing(tmp_path):
    target = staging_dir(tmp_path) / "my-skill"
    target.mkdir(parents=True)
    (target / "stale.md").write_text("old")
    result = mod.prepare("my-skill", project_dir=tmp_path)
    assert result.is_dir()
    assert not (result / "stale.md").exists()
    # skeleton regenerated
    assert (result / "SKILL.md").is_file()


# ── prepare: improve mode (seeded from source) ──────────────────────


def test_prepare_from_source(tmp_path):
    src = tmp_path / "real-skill"
    src.mkdir()
    (src / "SKILL.md").write_text("# skill")
    (src / "scripts").mkdir()
    (src / "scripts" / "helper.py").write_text("x = 1")

    target = mod.prepare("my-skill", source=src, project_dir=tmp_path)
    assert (target / "SKILL.md").read_text() == "# skill"
    assert (target / "scripts" / "helper.py").read_text() == "x = 1"


def test_prepare_from_source_wipes_existing_first(tmp_path):
    src = tmp_path / "real-skill"
    src.mkdir()
    (src / "SKILL.md").write_text("new")

    target = staging_dir(tmp_path) / "my-skill"
    target.mkdir(parents=True)
    (target / "stale.md").write_text("should be removed")

    result = mod.prepare("my-skill", source=src, project_dir=tmp_path)
    assert (result / "SKILL.md").read_text() == "new"
    assert not (result / "stale.md").exists()


def test_prepare_source_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        mod.prepare("my-skill", source=tmp_path / "nope", project_dir=tmp_path)


def test_prepare_rejects_invalid_name(tmp_path):
    with pytest.raises(ValueError):
        mod.prepare("Bad_Name", project_dir=tmp_path)


# ── main CLI ────────────────────────────────────────────────────────


def test_main_create_ok(tmp_path, capsys):
    rc = mod.main(["my-skill", "--project-dir", str(tmp_path)])
    assert rc == 0
    assert "Staging ready" in capsys.readouterr().out


def test_main_bad_name_returns_1(tmp_path, capsys):
    rc = mod.main(["Bad", "--project-dir", str(tmp_path)])
    err = capsys.readouterr().err
    assert rc == 1
    assert "kebab-case" in err


def test_main_with_source(tmp_path, capsys):
    src = tmp_path / "src-skill"
    src.mkdir()
    (src / "SKILL.md").write_text("# hi")
    rc = mod.main([
        "my-skill",
        "--source", str(src),
        "--project-dir", str(tmp_path),
    ])
    assert rc == 0
    staged = staging_dir(tmp_path) / "my-skill"
    assert (staged / "SKILL.md").read_text() == "# hi"
