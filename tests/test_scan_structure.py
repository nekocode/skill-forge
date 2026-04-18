"""Full test suite for scan_structure.py."""

from pathlib import Path

import pytest

from scan_structure import DEFAULT_EXCLUDES, main, scan_tree
from shared import WORKSPACE_DIR


# ── TestScanTree ───────────────────────────────────────


class TestScanTree:
    """Directory tree scanning."""

    def test_lists_files(self, tmp_path: Path) -> None:
        """normal dir -> list files and subdirs."""
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").touch()
        (tmp_path / "README.md").touch()

        result = scan_tree(tmp_path, max_depth=2)
        assert "src" in result
        assert "main.py" in result
        assert "README.md" in result

    def test_excludes_default_dirs(self, tmp_path: Path) -> None:
        """exclude node_modules, .git, dist and other default dirs."""
        (tmp_path / "node_modules" / "pkg").mkdir(parents=True)
        (tmp_path / ".git" / "objects").mkdir(parents=True)
        (tmp_path / "src" / "app.ts").mkdir(parents=True)

        result = scan_tree(tmp_path, max_depth=3)
        assert "node_modules" not in result
        assert ".git" not in result
        assert "app.ts" in result

    def test_max_depth(self, tmp_path: Path) -> None:
        """depth limit -> entries beyond max_depth not shown."""
        (tmp_path / "a" / "b" / "c" / "d").mkdir(parents=True)
        (tmp_path / "a" / "b" / "c" / "d" / "deep.txt").touch()

        result = scan_tree(tmp_path, max_depth=2)
        assert "deep.txt" not in result

    def test_files_at_max_depth_visible(self, tmp_path: Path) -> None:
        """files at max_depth boundary still visible, just no further recursion."""
        (tmp_path / "a" / "b").mkdir(parents=True)
        (tmp_path / "a" / "b" / "at_boundary.txt").touch()
        (tmp_path / "a" / "b" / "sub").mkdir()
        (tmp_path / "a" / "b" / "sub" / "too_deep.txt").touch()

        result = scan_tree(tmp_path, max_depth=2)
        assert "at_boundary.txt" in result
        assert "too_deep.txt" not in result

    def test_max_lines(self, tmp_path: Path) -> None:
        """line limit -> output does not exceed max_lines."""
        for i in range(200):
            (tmp_path / f"file_{i:03d}.txt").touch()

        result = scan_tree(tmp_path, max_depth=1, max_lines=10)
        lines = result.strip().splitlines()
        assert len(lines) <= 10

    def test_empty_dir(self, tmp_path: Path) -> None:
        """empty dir -> return empty string."""
        result = scan_tree(tmp_path, max_depth=2)
        assert result == ""

    def test_custom_excludes(self, tmp_path: Path) -> None:
        """custom excludes list."""
        (tmp_path / "build").mkdir()
        (tmp_path / "build" / "out.js").touch()
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "app.js").touch()

        result = scan_tree(tmp_path, max_depth=2, excludes={"build"})
        assert "build" not in result
        assert "app.js" in result


# ── TestDefaultExcludes ────────────────────────────────


class TestDefaultExcludes:
    """Default excludes list."""

    def test_contains_common_dirs(self) -> None:
        """contains common build/dependency dirs."""
        assert "node_modules" in DEFAULT_EXCLUDES
        assert ".git" in DEFAULT_EXCLUDES
        assert "dist" in DEFAULT_EXCLUDES


# ── TestMain ───────────────────────────────────────────


class TestMain:
    """CLI integration."""

    def test_main_output(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """main outputs directory tree."""
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "app.py").touch()

        main(project_dir=tmp_path)
        output = capsys.readouterr().out
        assert "app.py" in output

    def test_main_creates_workspace(self, tmp_path: Path) -> None:
        """main ensures .workspace/ exists so later Writes don't trigger shell mkdir."""
        main(project_dir=tmp_path)
        assert (tmp_path / WORKSPACE_DIR).is_dir()

    def test_main_workspace_idempotent(self, tmp_path: Path) -> None:
        """pre-existing workspace is preserved."""
        workspace = tmp_path / WORKSPACE_DIR
        workspace.mkdir(parents=True)
        (workspace / "insights.md").write_text("existing")

        main(project_dir=tmp_path)
        assert (workspace / "insights.md").read_text() == "existing"
