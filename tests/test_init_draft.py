"""Full test suite for init_draft.py."""

from pathlib import Path

import pytest

from init_draft import DRAFT_TEMPLATE, create_draft, main


# ── TestCreateDraft ────────────────────────────────────


class TestCreateDraft:
    """Draft initialization logic."""

    def test_creates_file(self, tmp_path: Path) -> None:
        """normal creation -> file exists, content contains name and goal."""
        create_draft("my-skill", "Automate deployment", project_dir=tmp_path)
        draft = tmp_path / ".claude" / "skill_draft.md"
        assert draft.exists()
        content = draft.read_text()
        assert "my-skill" in content
        assert "Automate deployment" in content

    def test_contains_required_sections(self, tmp_path: Path) -> None:
        """draft contains required sections: Goal, Phase, Status."""
        create_draft("test", "goal", project_dir=tmp_path)
        content = (tmp_path / ".claude" / "skill_draft.md").read_text()
        assert "## Goal" in content
        assert "## Phase" in content
        assert "## Status" in content
        assert "pending" in content

    def test_creates_parent_dir(self, tmp_path: Path) -> None:
        """parent dir missing -> auto-create."""
        create_draft("test", "goal", project_dir=tmp_path)
        assert (tmp_path / ".claude").is_dir()

    def test_overwrites_existing(self, tmp_path: Path) -> None:
        """existing draft -> overwrite."""
        draft = tmp_path / ".claude" / "skill_draft.md"
        draft.parent.mkdir(parents=True)
        draft.write_text("old content")
        create_draft("new-skill", "new goal", project_dir=tmp_path)
        assert "new-skill" in draft.read_text()
        assert "old content" not in draft.read_text()


# ── TestDraftTemplate ──────────────────────────────────


class TestDraftTemplate:
    """Template format."""

    def test_template_has_placeholders(self) -> None:
        """template contains {name} and {goal} placeholders."""
        assert "{name}" in DRAFT_TEMPLATE
        assert "{goal}" in DRAFT_TEMPLATE

    def test_template_renders(self) -> None:
        """placeholders render correctly."""
        result = DRAFT_TEMPLATE.format(name="x", goal="y")
        assert "x" in result
        assert "y" in result


# ── TestMain ───────────────────────────────────────────


class TestMain:
    """CLI integration."""

    def test_main_creates_draft(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """main outputs confirmation message."""
        main(name="my-skill", goal="Automate tests", project_dir=tmp_path)
        output = capsys.readouterr().out
        assert "my-skill" in output
        assert (tmp_path / ".claude" / "skill_draft.md").exists()
