"""Tests for finalize_skill.py."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import finalize_skill as mod
from shared import (
    PENDING_EVAL_SCORE_KEY,
    SKILLS_DIR,
    draft_file,
    save_state,
    staging_dir,
)


# ── fixtures / helpers ──────────────────────────────────────────────


VALID_SKILL_BODY = """\
---
name: {name}
description: >
  Use when generating X with multi-step setup.
  Use when the user says Y.
  Do NOT use when Z.
user-invocable: true
---

# {name}

## Prerequisites
- thing A

## Steps
1. step one
2. step two

## Verification
- check Z

## Notes
- footnote
"""


def _write_staged_skill(
    tmp_path: Path,
    name: str,
    *,
    extra_files: dict[str, str] | None = None,
    body: str | None = None,
) -> Path:
    staged = staging_dir(tmp_path) / name
    staged.mkdir(parents=True, exist_ok=True)
    (staged / "SKILL.md").write_text(
        body if body is not None else VALID_SKILL_BODY.format(name=name)
    )
    for rel, text in (extra_files or {}).items():
        p = staged / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return staged


def _load_registry(tmp_path: Path) -> dict:
    path = tmp_path / SKILLS_DIR / "skill_registry.json"
    return json.loads(path.read_text())


# ── _load_frontmatter ───────────────────────────────────────────────


def test_load_frontmatter_ok(tmp_path):
    p = tmp_path / "SKILL.md"
    p.write_text("---\nname: foo\ndescription: bar\n---\n# body\n")
    fm = mod._load_frontmatter(p)
    assert fm == {"name": "foo", "description": "bar"}


def test_load_frontmatter_missing_block(tmp_path):
    p = tmp_path / "SKILL.md"
    p.write_text("# no frontmatter here\n")
    with pytest.raises(ValueError, match="no YAML frontmatter"):
        mod._load_frontmatter(p)


def test_load_frontmatter_missing_fields(tmp_path):
    p = tmp_path / "SKILL.md"
    p.write_text("---\nname: foo\n---\n# body\n")
    with pytest.raises(ValueError, match="missing required field"):
        mod._load_frontmatter(p)


# ── _validate_mode ──────────────────────────────────────────────────


def test_validate_mode_create_rejects_existing(tmp_path):
    target = tmp_path / "exists"
    target.mkdir()
    with pytest.raises(FileExistsError):
        mod._validate_mode("create", target)


def test_validate_mode_update_rejects_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        mod._validate_mode("update", tmp_path / "nope")


def test_validate_mode_accepts_matching(tmp_path):
    target_existing = tmp_path / "x"
    target_existing.mkdir()
    mod._validate_mode("update", target_existing)  # no raise
    mod._validate_mode("create", tmp_path / "y")  # no raise


# ── finalize: create mode ───────────────────────────────────────────


def test_finalize_create_happy_path(tmp_path):
    _write_staged_skill(
        tmp_path, "my-skill",
        extra_files={"scripts/run.py": "print(1)\n"},
    )
    target = mod.finalize("my-skill", mode="create", project_dir=tmp_path)

    assert target == tmp_path / SKILLS_DIR / "my-skill"
    assert (target / "SKILL.md").is_file()
    assert (target / "scripts" / "run.py").read_text() == "print(1)\n"

    # staging cleared
    assert not (staging_dir(tmp_path) / "my-skill").exists()


def test_finalize_create_registers_entry(tmp_path):
    _write_staged_skill(tmp_path, "my-skill")
    mod.finalize("my-skill", mode="create", project_dir=tmp_path)

    reg = _load_registry(tmp_path)
    names = [s["name"] for s in reg["skills"]]
    assert "my-skill" in names
    entry = next(s for s in reg["skills"] if s["name"] == "my-skill")
    assert entry["scope"] == "project"
    assert entry["version"] == "1.0.0"


def test_finalize_create_consumes_pending_score(tmp_path):
    _write_staged_skill(tmp_path, "my-skill")
    save_state({PENDING_EVAL_SCORE_KEY: 7})

    mod.finalize("my-skill", mode="create", project_dir=tmp_path)

    entry = _load_registry(tmp_path)["skills"][0]
    assert entry["eval_score"] == 7


def test_finalize_create_clears_draft(tmp_path):
    _write_staged_skill(tmp_path, "my-skill")
    draft = draft_file(tmp_path)
    draft.parent.mkdir(parents=True, exist_ok=True)
    draft.write_text("in-progress content")

    mod.finalize("my-skill", mode="create", project_dir=tmp_path)

    # File still exists but empty so hook checks won't flip.
    assert draft.is_file()
    assert draft.read_text() == ""


def test_finalize_create_rejects_existing_target(tmp_path):
    _write_staged_skill(tmp_path, "my-skill")
    existing = tmp_path / SKILLS_DIR / "my-skill"
    existing.mkdir(parents=True)

    with pytest.raises(FileExistsError):
        mod.finalize("my-skill", mode="create", project_dir=tmp_path)


def test_finalize_missing_staging(tmp_path):
    with pytest.raises(FileNotFoundError, match="staging dir not found"):
        mod.finalize("ghost", mode="create", project_dir=tmp_path)


def test_finalize_missing_skill_md(tmp_path):
    staged = staging_dir(tmp_path) / "my-skill"
    staged.mkdir(parents=True)
    # no SKILL.md written
    with pytest.raises(FileNotFoundError, match="SKILL.md missing"):
        mod.finalize("my-skill", mode="create", project_dir=tmp_path)


def test_finalize_rejects_name_mismatch(tmp_path):
    _write_staged_skill(tmp_path, "my-skill")
    # rewrite SKILL.md so the frontmatter name disagrees with dir name
    skill_md = staging_dir(tmp_path) / "my-skill" / "SKILL.md"
    skill_md.write_text(VALID_SKILL_BODY.format(name="other-name"))

    with pytest.raises(ValueError, match="does not match"):
        mod.finalize("my-skill", mode="create", project_dir=tmp_path)


# ── finalize: update mode ───────────────────────────────────────────


def test_finalize_update_replaces_target(tmp_path):
    target = tmp_path / SKILLS_DIR / "my-skill"
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text("old version")
    (target / "stale.md").write_text("should vanish")

    _write_staged_skill(
        tmp_path, "my-skill",
        extra_files={"CHANGELOG.md": "## 2026-04-19 — v1.1.0\n- new\n"},
    )

    mod.finalize("my-skill", mode="update", project_dir=tmp_path)

    # new file present, old stale file gone, SKILL.md rewritten
    assert (target / "CHANGELOG.md").is_file()
    assert not (target / "stale.md").exists()
    assert "old version" not in (target / "SKILL.md").read_text()


def test_finalize_update_bumps_version(tmp_path):
    # preload registry with a 1.0.0 entry
    reg_path = tmp_path / SKILLS_DIR / "skill_registry.json"
    reg_path.parent.mkdir(parents=True, exist_ok=True)
    reg_path.write_text(json.dumps({
        "version": "1",
        "skills": [{
            "name": "my-skill",
            "version": "1.0.0",
            "scope": "project",
            "created": "2026-01-01",
            "updated": "2026-01-01",
            "auto_trigger": True,
            "description_chars": 50,
            "eval_score": 6,
            "usage_count": 0,
        }],
    }))
    # target must exist for update mode
    target = tmp_path / SKILLS_DIR / "my-skill"
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text("existing")

    _write_staged_skill(tmp_path, "my-skill")
    mod.finalize("my-skill", mode="update", project_dir=tmp_path)

    entry = _load_registry(tmp_path)["skills"][0]
    assert entry["version"] == "1.0.1"


def test_finalize_update_rejects_missing_target(tmp_path):
    _write_staged_skill(tmp_path, "my-skill")
    with pytest.raises(FileNotFoundError):
        mod.finalize("my-skill", mode="update", project_dir=tmp_path)


# ── changelog + bump ────────────────────────────────────────────────


def _preload_registry(tmp_path: Path, name: str, version: str) -> None:
    reg_path = tmp_path / SKILLS_DIR / "skill_registry.json"
    reg_path.parent.mkdir(parents=True, exist_ok=True)
    reg_path.write_text(json.dumps({
        "version": "1",
        "skills": [{
            "name": name,
            "version": version,
            "scope": "project",
            "created": "2026-01-01",
            "updated": "2026-01-01",
            "auto_trigger": True,
            "description_chars": 50,
            "eval_score": 6,
            "usage_count": 0,
        }],
    }))


def test_finalize_changelog_appended_with_computed_version(tmp_path):
    _preload_registry(tmp_path, "my-skill", "1.2.3")
    target = tmp_path / SKILLS_DIR / "my-skill"
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text("old")

    _write_staged_skill(tmp_path, "my-skill")
    mod.finalize(
        "my-skill", mode="update", project_dir=tmp_path,
        changelog="clarify step 3", bump="minor",
    )

    changelog = (target / "CHANGELOG.md").read_text()
    # header uses new version (1.3.0 after minor bump) and today's date;
    # one-liner in the body below the header
    assert "v1.3.0" in changelog
    assert "clarify step 3" in changelog


def test_finalize_changelog_prepends_over_existing(tmp_path):
    _preload_registry(tmp_path, "my-skill", "1.0.0")
    target = tmp_path / SKILLS_DIR / "my-skill"
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text("old")

    _write_staged_skill(
        tmp_path, "my-skill",
        extra_files={"CHANGELOG.md": "## 2026-04-01 — v1.0.0\n- initial\n\n"},
    )
    mod.finalize(
        "my-skill", mode="update", project_dir=tmp_path,
        changelog="second entry",
    )

    content = (target / "CHANGELOG.md").read_text()
    # new entry appears before old entry in the file
    new_idx = content.index("second entry")
    old_idx = content.index("initial")
    assert new_idx < old_idx
    assert "v1.0.1" in content  # default patch bump


def test_finalize_without_changelog_writes_nothing(tmp_path):
    """No --changelog → CHANGELOG.md is not touched at all."""
    _preload_registry(tmp_path, "my-skill", "1.0.0")
    target = tmp_path / SKILLS_DIR / "my-skill"
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text("old")

    _write_staged_skill(tmp_path, "my-skill")
    mod.finalize("my-skill", mode="update", project_dir=tmp_path)

    assert not (target / "CHANGELOG.md").exists()


def test_finalize_bump_major_updates_registry(tmp_path):
    _preload_registry(tmp_path, "my-skill", "1.2.3")
    target = tmp_path / SKILLS_DIR / "my-skill"
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text("old")

    _write_staged_skill(tmp_path, "my-skill")
    mod.finalize("my-skill", mode="update", project_dir=tmp_path, bump="major")

    entry = _load_registry(tmp_path)["skills"][0]
    assert entry["version"] == "2.0.0"


def test_main_passes_changelog_and_bump(tmp_path, capsys):
    _preload_registry(tmp_path, "my-skill", "1.0.0")
    target = tmp_path / SKILLS_DIR / "my-skill"
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text("old")

    _write_staged_skill(tmp_path, "my-skill")
    rc = mod.main([
        "my-skill",
        "--mode", "update",
        "--project-dir", str(tmp_path),
        "--changelog", "fixed a bug",
        "--bump", "minor",
    ])
    assert rc == 0
    changelog = (target / "CHANGELOG.md").read_text()
    assert "v1.1.0" in changelog and "fixed a bug" in changelog


# ── CLI ─────────────────────────────────────────────────────────────


def test_main_create_ok(tmp_path, capsys):
    _write_staged_skill(tmp_path, "my-skill")
    rc = mod.main([
        "my-skill",
        "--mode", "create",
        "--project-dir", str(tmp_path),
    ])
    captured = capsys.readouterr()
    assert rc == 0
    assert "Created" in captured.out


def test_main_reports_error_to_stderr(tmp_path, capsys):
    rc = mod.main([
        "ghost",
        "--mode", "create",
        "--project-dir", str(tmp_path),
    ])
    err = capsys.readouterr().err
    assert rc == 1
    assert "finalize failed" in err


def test_main_mode_required(tmp_path):
    with pytest.raises(SystemExit):
        mod.main(["my-skill", "--project-dir", str(tmp_path)])
