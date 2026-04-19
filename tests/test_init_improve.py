"""Full test suite for init_improve.py."""

from pathlib import Path

import pytest

from init_improve import init_improve_session, main
from shared import draft_file, staging_dir


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

    def test_seeds_staging_from_live_skill(self, tmp_path: Path) -> None:
        """Live skill dir contents mirror into staging for atomic edits."""
        skill_dir = tmp_path / ".claude" / "skills" / "my-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("# body\n")
        scripts = skill_dir / "scripts"
        scripts.mkdir()
        (scripts / "helper.py").write_text("x = 1\n")

        init_improve_session("my-skill", project_dir=tmp_path)

        staged = staging_dir(tmp_path) / "my-skill"
        assert (staged / "SKILL.md").read_text() == "# body\n"
        assert (staged / "scripts" / "helper.py").read_text() == "x = 1\n"

    def test_staging_wiped_on_reinit(self, tmp_path: Path) -> None:
        """Re-running init_improve clears stale staging from a prior attempt."""
        skill_dir = tmp_path / ".claude" / "skills" / "my-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("new\n")

        # pre-existing stale file under staging
        staged = staging_dir(tmp_path) / "my-skill"
        staged.mkdir(parents=True)
        (staged / "stale.md").write_text("should vanish")

        init_improve_session("my-skill", project_dir=tmp_path)

        assert not (staged / "stale.md").exists()
        assert (staged / "SKILL.md").read_text() == "new\n"

    def test_missing_skill_does_not_touch_staging(self, tmp_path: Path) -> None:
        """Failure exit leaves staging dir untouched (no partial state)."""
        result = init_improve_session("nope", project_dir=tmp_path)
        assert result is False
        assert not (staging_dir(tmp_path) / "nope").exists()


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
