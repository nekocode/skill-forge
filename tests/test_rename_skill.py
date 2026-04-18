"""Full test suite for rename_skill.py."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rename_skill import (
    build_plan,
    execute_plan,
    main,
    render_plan,
    resolve_skills_root,
)
from shared import REGISTRY_FILE, SKILLS_DIR, USER_SKILLS_DIR, draft_file


# ── Fixtures ──────────────────────────────────────────────


def _make_project(tmp_path: Path, skill_name: str = "foo") -> tuple[Path, Path]:
    """Create a minimal project layout with a single skill and registry."""
    skills_root = tmp_path / SKILLS_DIR
    skill_dir = skills_root / skill_name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {skill_name}\ndescription: >\n  Use when {skill_name} is needed.\n---\n\n"
        f"# {skill_name}\n\nHelper for {skill_name} tasks.\n"
    )
    (skill_dir / "CHANGELOG.md").write_text(f"## 2026-01-01 — v1.0.0\n- initial {skill_name}\n")
    scripts = skill_dir / "scripts"
    scripts.mkdir()
    (scripts / "helper.py").write_text(f'"""Helper for {skill_name}."""\n')

    registry = {
        "version": "1",
        "skills": [
            {
                "name": skill_name,
                "version": "1.0.0",
                "scope": "project",
                "created": "2026-01-01",
                "updated": "2026-01-01",
                "auto_trigger": True,
                "description_chars": 40,
                "eval_score": 7,
                "usage_count": 0,
            }
        ],
    }
    (skills_root / REGISTRY_FILE.name).write_text(json.dumps(registry, indent=2))
    return skills_root, skill_dir


# ── resolve_skills_root ───────────────────────────────────


class TestResolveSkillsRoot:
    def test_project_scope_explicit(self, tmp_path: Path) -> None:
        root, label = resolve_skills_root("project", tmp_path)
        assert root == tmp_path / SKILLS_DIR
        assert label == "project"

    def test_user_scope_explicit(self, tmp_path: Path) -> None:
        root, label = resolve_skills_root("user", tmp_path)
        assert root == USER_SKILLS_DIR
        assert label == "user"

    def test_auto_detect_prefers_project(self, tmp_path: Path) -> None:
        (tmp_path / SKILLS_DIR).mkdir(parents=True)
        root, label = resolve_skills_root(None, tmp_path)
        assert root == tmp_path / SKILLS_DIR
        assert label == "project"

    def test_auto_detect_falls_back_to_user(self, tmp_path: Path) -> None:
        root, label = resolve_skills_root(None, tmp_path)
        assert root == USER_SKILLS_DIR
        assert label == "user"


# ── build_plan ────────────────────────────────────────────


class TestBuildPlan:
    def test_happy_path(self, tmp_path: Path) -> None:
        skills_root, _ = _make_project(tmp_path, "foo")
        plan = build_plan("foo", "bar", skills_root, tmp_path)

        assert plan["errors"] == []
        assert plan["registry_entry"]["name"] == "foo"

        edited_paths = {p for p, _, _ in plan["file_edits"]}
        assert any(p.name == "SKILL.md" for p in edited_paths)
        assert any(p.name == "CHANGELOG.md" for p in edited_paths)
        assert any(p.name == "helper.py" for p in edited_paths)

        assert plan["dir_renames"] == [
            (skills_root / "foo", skills_root / "bar"),
        ]

    def test_identical_names_error(self, tmp_path: Path) -> None:
        skills_root, _ = _make_project(tmp_path, "foo")
        plan = build_plan("foo", "foo", skills_root, tmp_path)
        assert any("identical" in e for e in plan["errors"])

    def test_missing_source_error(self, tmp_path: Path) -> None:
        skills_root, _ = _make_project(tmp_path, "foo")
        plan = build_plan("missing", "bar", skills_root, tmp_path)
        assert any("not found" in e for e in plan["errors"])

    def test_target_exists_error(self, tmp_path: Path) -> None:
        skills_root, _ = _make_project(tmp_path, "foo")
        (skills_root / "bar").mkdir()
        plan = build_plan("foo", "bar", skills_root, tmp_path)
        assert any("already exists" in e for e in plan["errors"])

    def test_no_registry_entry_error(self, tmp_path: Path) -> None:
        skills_root, _ = _make_project(tmp_path, "foo")
        # overwrite registry with empty list
        (skills_root / REGISTRY_FILE.name).write_text(
            json.dumps({"version": "1", "skills": []})
        )
        plan = build_plan("foo", "bar", skills_root, tmp_path)
        assert any("no entry" in e for e in plan["errors"])

    def test_active_draft_guard(self, tmp_path: Path) -> None:
        skills_root, _ = _make_project(tmp_path, "foo")
        draft = draft_file(tmp_path)
        draft.parent.mkdir(parents=True)
        draft.write_text("# foo — IN PROGRESS\n")

        plan = build_plan("foo", "bar", skills_root, tmp_path)
        assert any("active draft" in e for e in plan["errors"])

    def test_binary_file_tolerated(self, tmp_path: Path) -> None:
        """Binary file in scripts/ must not crash scanning."""
        skills_root, skill_dir = _make_project(tmp_path, "foo")
        (skill_dir / "scripts" / "blob.bin").write_bytes(b"\x00\x01\x02foo\xff")

        plan = build_plan("foo", "bar", skills_root, tmp_path)
        # blob.bin decoded as utf-8 may or may not match; must not error
        assert plan["errors"] == []


# ── execute_plan ──────────────────────────────────────────


class TestExecutePlan:
    def test_renames_dir_and_updates_content(self, tmp_path: Path) -> None:
        skills_root, _ = _make_project(tmp_path, "foo")
        plan = build_plan("foo", "bar", skills_root, tmp_path)
        execute_plan(plan)

        assert (skills_root / "bar").is_dir()
        assert not (skills_root / "foo").exists()

        skill_md = (skills_root / "bar" / "SKILL.md").read_text()
        assert "name: bar" in skill_md
        assert "foo" not in skill_md

    def test_updates_registry(self, tmp_path: Path) -> None:
        skills_root, _ = _make_project(tmp_path, "foo")
        plan = build_plan("foo", "bar", skills_root, tmp_path)
        execute_plan(plan)

        registry = json.loads((skills_root / REGISTRY_FILE.name).read_text())
        names = [s["name"] for s in registry["skills"]]
        assert "bar" in names
        assert "foo" not in names

# ── render_plan ───────────────────────────────────────────


class TestRenderPlan:
    def test_prose_includes_header(self, tmp_path: Path) -> None:
        skills_root, _ = _make_project(tmp_path, "foo")
        plan = build_plan("foo", "bar", skills_root, tmp_path)
        text = render_plan(plan, "foo", "bar", "project")
        assert "'foo'" in text and "'bar'" in text
        assert "[scope: project]" in text
        assert "File edits" in text
        assert "Directory renames" in text

    def test_errors_render_first(self, tmp_path: Path) -> None:
        skills_root, _ = _make_project(tmp_path, "foo")
        plan = build_plan("foo", "foo", skills_root, tmp_path)
        text = render_plan(plan, "foo", "foo", "project")
        assert "Errors (aborting):" in text


# ── main / CLI ────────────────────────────────────────────


class TestMain:
    def test_dry_run_does_not_modify(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        skills_root, _ = _make_project(tmp_path, "foo")
        rc = main(["foo", "bar", "--dry-run", "--project-dir", str(tmp_path)])
        assert rc == 0
        assert "dry-run" in capsys.readouterr().out
        assert (skills_root / "foo").is_dir()
        assert not (skills_root / "bar").exists()

    def test_apply_renames(self, tmp_path: Path) -> None:
        skills_root, _ = _make_project(tmp_path, "foo")
        rc = main(["foo", "bar", "--project-dir", str(tmp_path)])
        assert rc == 0
        assert (skills_root / "bar").is_dir()

    def test_error_exits_nonzero(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        _make_project(tmp_path, "foo")
        rc = main(["missing", "bar", "--project-dir", str(tmp_path)])
        assert rc == 1
        assert "Errors" in capsys.readouterr().out

    def test_json_mode(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        skills_root, _ = _make_project(tmp_path, "foo")
        rc = main(["foo", "bar", "--json", "--project-dir", str(tmp_path)])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert data["scope"] == "project"
        assert data["errors"] == []
        assert any("SKILL.md" in e[0] for e in data["file_edits"])
        # --json implies no mutation
        assert (skills_root / "foo").is_dir()
