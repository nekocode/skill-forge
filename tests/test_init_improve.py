"""Full test suite for init_improve.py."""

from pathlib import Path

import pytest

from init_improve import init_improve_session, main
from shared import draft_file


# ── TestInitImproveSession ─────────────────────────────


class TestInitImproveSession:
    """Improve session initialization."""

    def test_copies_skill_to_draft(self, tmp_path: Path) -> None:
        """copy existing SKILL.md to skill_draft.md."""
        skill_dir = tmp_path / ".claude" / "skills" / "my-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("---\nname: my-skill\n---\n# my-skill\nsteps\n")

        init_improve_session("my-skill", project_dir=tmp_path)

        draft = draft_file(tmp_path)
        assert draft.exists()
        content = draft.read_text()
        assert "name: my-skill" in content

    def test_appends_session_header(self, tmp_path: Path) -> None:
        """append improve session timestamp to draft end."""
        skill_dir = tmp_path / ".claude" / "skills" / "my-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("# content\n")

        init_improve_session("my-skill", project_dir=tmp_path)

        content = draft_file(tmp_path).read_text()
        assert "## Improve session" in content

    def test_skill_not_found(self, tmp_path: Path) -> None:
        """skill dir missing -> return False."""
        result = init_improve_session("nonexistent", project_dir=tmp_path)
        assert result is False
        assert not draft_file(tmp_path).exists()

    def test_creates_claude_dir(self, tmp_path: Path) -> None:
        """creates even if .claude/ does not exist."""
        skill_dir = tmp_path / ".claude" / "skills" / "test"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("content\n")

        init_improve_session("test", project_dir=tmp_path)
        assert draft_file(tmp_path).exists()


# ── TestMain ───────────────────────────────────────────


class TestMain:
    """CLI integration."""

    def test_main_success(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """success -> output confirmation."""
        skill_dir = tmp_path / ".claude" / "skills" / "my-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("# content\n")

        main(name="my-skill", project_dir=tmp_path)
        output = capsys.readouterr().out
        assert "my-skill" in output

    def test_main_not_found(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """skill not found -> output error."""
        main(name="nonexistent", project_dir=tmp_path)
        output = capsys.readouterr().out
        assert "not found" in output.lower()
