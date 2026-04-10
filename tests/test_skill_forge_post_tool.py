"""Full test suite for skill_forge_post_tool.py."""

import json
from datetime import date
from io import StringIO
from pathlib import Path
import pytest

from skill_forge_post_tool import (
    bump_version,
    main,
    upsert_skill,
    validate_skill,
)


# ── helpers ──────────────────────────────────────────────────

VALID_FRONTMATTER = """\
---
name: my-skill
description: Use when you need to do X and Y
---
# Body
"""

MISSING_FM = """\
# No frontmatter at all
Just body content.
"""

MISSING_FIELDS_FM = """\
---
name: incomplete
---
# Body
"""

LONG_DESC_FM = """\
---
name: verbose
description: {long_desc}
---
"""

NO_USE_WHEN_FM = """\
---
name: no-trigger
description: This does something cool
---
"""


def _make_registry(*entries: dict) -> dict:
    """Build registry structure."""
    return {"version": "1", "skills": list(entries)}


def _existing_entry(name: str = "my-skill", version: str = "1.0.0") -> dict:
    return {
        "name": name,
        "version": version,
        "scope": "project",
        "created": "2025-01-01",
        "updated": "2025-01-01",
        "auto_trigger": True,
        "description_chars": 30,
        "eval_score": 0,
        "usage_count": 0,
    }


# ── TestBumpVersion ───────────────────────────────────────


class TestBumpVersion:
    """Version bump logic."""

    def test_normal_semver(self) -> None:
        """standard semver -> patch +1."""
        assert bump_version("1.0.0") == "1.0.1"
        assert bump_version("2.3.9") == "2.3.10"
        assert bump_version("0.0.0") == "0.0.1"

    def test_two_part_version(self) -> None:
        """two-part version -> last segment +1."""
        assert bump_version("1.0") == "1.1"

    def test_single_part_version(self) -> None:
        """single-part version -> +1."""
        assert bump_version("5") == "6"

    def test_malformed_non_numeric(self) -> None:
        """last segment non-numeric -> fallback to 1.0.1."""
        assert bump_version("1.0.abc") == "1.0.1"

    def test_malformed_empty(self) -> None:
        """empty string -> fallback to 1.0.1."""
        assert bump_version("") == "1.0.1"

    def test_malformed_garbage(self) -> None:
        """garbage input -> fallback to 1.0.1."""
        assert bump_version("not-a-version") == "1.0.1"


# ── TestUpsertSkill ───────────────────────────────────────


class TestUpsertSkill:
    """Registry upsert logic."""

    def test_new_skill_appended(self) -> None:
        """new skill -> appended to skills list."""
        registry = _make_registry()
        fm = {"name": "new-one", "user-invocable": "true", "description": "x" * 42}
        upsert_skill(registry, fm, "project")

        assert len(registry["skills"]) == 1
        entry = registry["skills"][0]
        assert entry["name"] == "new-one"
        assert entry["version"] == "1.0.0"
        assert entry["scope"] == "project"
        assert entry["description_chars"] == 42
        assert entry["auto_trigger"] is True
        assert entry["created"] == date.today().isoformat()
        assert entry["updated"] == date.today().isoformat()
        assert entry["eval_score"] == 0
        assert entry["usage_count"] == 0

    def test_new_skill_not_invocable(self) -> None:
        """user-invocable=false -> auto_trigger=False."""
        registry = _make_registry()
        fm = {"name": "hidden", "user-invocable": "false", "description": "x" * 10}
        upsert_skill(registry, fm, "personal")

        assert registry["skills"][0]["auto_trigger"] is False

    def test_new_skill_invocable_default(self) -> None:
        """no user-invocable field -> auto_trigger=True (default triggerable)."""
        registry = _make_registry()
        fm = {"name": "default-trigger", "description": "x" * 20}
        upsert_skill(registry, fm, "project")

        assert registry["skills"][0]["auto_trigger"] is True

    def test_existing_skill_updated(self) -> None:
        """existing skill -> update updated/version/description_chars, preserve rest."""
        existing = _existing_entry("my-skill", "1.0.3")
        registry = _make_registry(existing)
        fm = {"name": "my-skill", "description": "x" * 99}
        upsert_skill(registry, fm, "project")

        assert len(registry["skills"]) == 1
        entry = registry["skills"][0]
        assert entry["version"] == "1.0.4"
        assert entry["updated"] == date.today().isoformat()
        assert entry["description_chars"] == 99
        # original fields preserved
        assert entry["created"] == "2025-01-01"
        assert entry["usage_count"] == 0

    def test_existing_skill_missing_version(self) -> None:
        """existing skill missing version field -> bump from 1.0.0 to 1.0.1."""
        existing = _existing_entry()
        del existing["version"]
        registry = _make_registry(existing)
        fm = {"name": "my-skill", "description": "x" * 30}
        upsert_skill(registry, fm, "project")

        assert registry["skills"][0]["version"] == "1.0.1"

    def test_multiple_skills_only_target_updated(self) -> None:
        """multiple skills -> only update the matching name."""
        a = _existing_entry("skill-a", "1.0.0")
        b = _existing_entry("skill-b", "2.0.0")
        registry = _make_registry(a, b)
        fm = {"name": "skill-b", "description": "x" * 50}
        upsert_skill(registry, fm, "project")

        assert registry["skills"][0]["version"] == "1.0.0"  # a unchanged
        assert registry["skills"][1]["version"] == "2.0.1"  # b bumped


# ── TestValidateSkill ─────────────────────────────────────


class TestValidateSkill:
    """SKILL.md content validation."""

    def test_valid_content_no_warnings(self) -> None:
        """valid content -> no warnings."""
        assert validate_skill(VALID_FRONTMATTER) == []

    def test_missing_frontmatter(self) -> None:
        """no frontmatter -> single warning."""
        warnings = validate_skill(MISSING_FM)
        assert len(warnings) == 1
        assert "Missing YAML frontmatter" in warnings[0]

    def test_missing_required_fields(self) -> None:
        """missing description -> report missing fields + missing 'use when'."""
        warnings = validate_skill(MISSING_FIELDS_FM)
        assert any("missing fields" in w.lower() for w in warnings)
        assert any("description" in w for w in warnings)

    def test_description_too_long(self) -> None:
        """description >250 chars -> truncation warning."""
        long_desc = "Use when " + "x" * 250
        content = LONG_DESC_FM.format(long_desc=long_desc)
        warnings = validate_skill(content)
        assert any("truncates at 250" in w for w in warnings)

    def test_description_exactly_250(self) -> None:
        """description exactly 250 chars -> no truncation warning."""
        # 9 ("Use when ") + 241 = 250
        desc_250 = "Use when " + "x" * 241
        assert len(desc_250) == 250
        content = LONG_DESC_FM.format(long_desc=desc_250)
        warnings = validate_skill(content)
        assert not any("truncates" in w for w in warnings)

    def test_missing_use_when(self) -> None:
        """description without 'use when' -> trigger phrase warning."""
        warnings = validate_skill(NO_USE_WHEN_FM)
        assert any("Use when" in w for w in warnings)

    def test_use_when_case_insensitive(self) -> None:
        """'USE WHEN' uppercase -> still passes."""
        content = """\
---
name: case-test
description: USE WHEN you want to test case
---
"""
        warnings = validate_skill(content)
        assert not any("Use when" in w for w in warnings)

    def test_missing_fields_and_long_desc(self) -> None:
        """missing fields + too long -> returns multiple warnings."""
        content = """\
---
name: bad
---
"""
        warnings = validate_skill(content)
        # at least missing description + missing 'use when' (desc is empty)
        assert len(warnings) >= 2


# ── TestMain ──────────────────────────────────────────────


class TestMain:
    """stdin/stdout integration, including tool_call counting and SKILL.md write detection."""

    def _run_main(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
        tmp_path: Path,
        hook_input: dict,
        *,
        state_init: dict | None = None,
        registry_init: dict | None = None,
        skill_content: str | None = None,
        skill_subpath: str = ".claude/skills/my-skill/SKILL.md",
    ) -> tuple[dict, dict, dict]:
        """Unified entry to run main. Returns (stdout_json, state, registry)."""
        state_file = tmp_path / ".claude" / "skill_forge_state.json"
        registry_file = tmp_path / ".claude" / "skills" / "skill_registry.json"

        # init state
        if state_init:
            state_file.parent.mkdir(parents=True, exist_ok=True)
            state_file.write_text(json.dumps(state_init))

        # init registry
        if registry_init:
            registry_file.parent.mkdir(parents=True, exist_ok=True)
            registry_file.write_text(json.dumps(registry_init))

        # write SKILL.md
        if skill_content is not None:
            skill_file = tmp_path / skill_subpath
            skill_file.parent.mkdir(parents=True, exist_ok=True)
            skill_file.write_text(skill_content)
            # hook_input's file_path points to actual file
            hook_input.setdefault("tool_input", {})["file_path"] = str(skill_file)

        monkeypatch.setattr("sys.stdin", StringIO(json.dumps(hook_input)))
        # redirect shared module path constants
        monkeypatch.setattr(
            "skill_forge_post_tool.load_state",
            lambda: json.loads(state_file.read_text())
            if state_file.exists()
            else {"tool_calls": 0},
        )
        monkeypatch.setattr(
            "skill_forge_post_tool.save_state",
            lambda s: (
                state_file.parent.mkdir(parents=True, exist_ok=True),
                state_file.write_text(json.dumps(s)),
            ),
        )
        monkeypatch.setattr(
            "skill_forge_post_tool.load_registry",
            lambda: json.loads(registry_file.read_text())
            if registry_file.exists()
            else {"version": "1", "skills": []},
        )
        monkeypatch.setattr(
            "skill_forge_post_tool.save_registry",
            lambda r: (
                registry_file.parent.mkdir(parents=True, exist_ok=True),
                registry_file.write_text(json.dumps(r)),
            ),
        )

        main()

        stdout_json = json.loads(capsys.readouterr().out)
        state = json.loads(state_file.read_text()) if state_file.exists() else {}
        registry = (
            json.loads(registry_file.read_text())
            if registry_file.exists()
            else {"version": "1", "skills": []}
        )
        return stdout_json, state, registry

    # ── tool_call counting ──

    def test_tool_call_incremented(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
        tmp_path: Path,
    ) -> None:
        """each call -> tool_calls +1."""
        out, state, _ = self._run_main(
            monkeypatch,
            capsys,
            tmp_path,
            {"tool_name": "Read", "tool_input": {"file_path": "/some/file.py"}},
            state_init={"tool_calls": 5},
        )
        assert state["tool_calls"] == 6
        assert out == {}

    def test_tool_call_from_zero(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
        tmp_path: Path,
    ) -> None:
        """no initial state -> tool_calls starts from 0."""
        out, state, _ = self._run_main(
            monkeypatch,
            capsys,
            tmp_path,
            {"tool_name": "Bash", "tool_input": {"command": "ls"}},
        )
        assert state["tool_calls"] == 1

    # ── non-SKILL.md file -> no registration ──

    def test_non_skill_file_ignored(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
        tmp_path: Path,
    ) -> None:
        """writing non-SKILL.md file -> registry not updated."""
        out, _, registry = self._run_main(
            monkeypatch,
            capsys,
            tmp_path,
            {"tool_name": "Write", "tool_input": {"file_path": "/some/random.py"}},
        )
        assert out == {}
        assert registry["skills"] == []

    # ── non-write tool -> no registration ──

    def test_non_write_tool_ignored(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
        tmp_path: Path,
    ) -> None:
        """Read tool reading SKILL.md -> no registration."""
        out, _, registry = self._run_main(
            monkeypatch,
            capsys,
            tmp_path,
            {"tool_name": "Read", "tool_input": {}},
            skill_content=VALID_FRONTMATTER,
        )
        assert out == {}
        assert registry["skills"] == []

    # ── SKILL.md Write -> register + no warnings ──

    def test_valid_skill_write_registers(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
        tmp_path: Path,
    ) -> None:
        """valid SKILL.md write -> registered in registry, no systemMessage."""
        out, _, registry = self._run_main(
            monkeypatch,
            capsys,
            tmp_path,
            {"tool_name": "Write", "tool_input": {}},
            skill_content=VALID_FRONTMATTER,
        )
        assert out == {}
        assert len(registry["skills"]) == 1
        assert registry["skills"][0]["name"] == "my-skill"

    # ── SKILL.md Edit -> also triggers ──

    def test_edit_tool_triggers(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
        tmp_path: Path,
    ) -> None:
        """Edit tool writing SKILL.md -> also triggers registration."""
        out, _, registry = self._run_main(
            monkeypatch,
            capsys,
            tmp_path,
            {"tool_name": "Edit", "tool_input": {}},
            skill_content=VALID_FRONTMATTER,
        )
        assert len(registry["skills"]) == 1

    # ── SKILL.md with warnings -> systemMessage ──

    def test_warnings_in_system_message(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
        tmp_path: Path,
    ) -> None:
        """validation has warnings -> stdout contains systemMessage."""
        out, _, _ = self._run_main(
            monkeypatch,
            capsys,
            tmp_path,
            {"tool_name": "Write", "tool_input": {}},
            skill_content=NO_USE_WHEN_FM,
        )
        assert "systemMessage" in out
        assert "Use when" in out["systemMessage"]

    def test_missing_frontmatter_warning(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
        tmp_path: Path,
    ) -> None:
        """no frontmatter -> output systemMessage but no registration."""
        out, _, registry = self._run_main(
            monkeypatch,
            capsys,
            tmp_path,
            {"tool_name": "Write", "tool_input": {}},
            skill_content=MISSING_FM,
        )
        assert "systemMessage" in out
        assert "Missing YAML frontmatter" in out["systemMessage"]
        assert registry["skills"] == []

    # ── SKILL.md read failure (file missing) ──

    def test_file_read_failure(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
        tmp_path: Path,
    ) -> None:
        """SKILL.md path points to missing file -> output empty JSON, no crash."""
        state_file = tmp_path / ".claude" / "skill_forge_state.json"

        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": str(tmp_path / "ghost" / "SKILL.md")},
        }
        monkeypatch.setattr("sys.stdin", StringIO(json.dumps(hook_input)))
        monkeypatch.setattr(
            "skill_forge_post_tool.load_state", lambda: {"tool_calls": 0}
        )
        monkeypatch.setattr(
            "skill_forge_post_tool.save_state",
            lambda s: (
                state_file.parent.mkdir(parents=True, exist_ok=True),
                state_file.write_text(json.dumps(s)),
            ),
        )
        monkeypatch.setattr(
            "skill_forge_post_tool.load_registry",
            lambda: {"version": "1", "skills": []},
        )
        monkeypatch.setattr("skill_forge_post_tool.save_registry", lambda r: None)

        main()

        out = json.loads(capsys.readouterr().out)
        assert out == {}

    # ── scope inference: .claude in path -> project ──

    def test_scope_project(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
        tmp_path: Path,
    ) -> None:
        """path contains .claude -> scope=project."""
        _, _, registry = self._run_main(
            monkeypatch,
            capsys,
            tmp_path,
            {"tool_name": "Write", "tool_input": {}},
            skill_content=VALID_FRONTMATTER,
            skill_subpath=".claude/skills/my-skill/SKILL.md",
        )
        assert registry["skills"][0]["scope"] == "project"

    def test_scope_personal(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
        tmp_path: Path,
    ) -> None:
        """path without .claude -> scope=personal."""
        _, _, registry = self._run_main(
            monkeypatch,
            capsys,
            tmp_path,
            {"tool_name": "Write", "tool_input": {}},
            skill_content=VALID_FRONTMATTER,
            skill_subpath="personal/skills/my-skill/SKILL.md",
        )
        assert registry["skills"][0]["scope"] == "personal"

    # ── existing skill -> version bump ──

    def test_existing_skill_version_bumped(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
        tmp_path: Path,
    ) -> None:
        """second write of same skill -> version bump."""
        _, _, registry = self._run_main(
            monkeypatch,
            capsys,
            tmp_path,
            {"tool_name": "Write", "tool_input": {}},
            skill_content=VALID_FRONTMATTER,
            registry_init=_make_registry(_existing_entry("my-skill", "1.0.5")),
        )
        assert registry["skills"][0]["version"] == "1.0.6"

    # ── fm without name -> no registration but still output warnings ──

    def test_no_name_in_frontmatter(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
        tmp_path: Path,
    ) -> None:
        """frontmatter present but no name field -> no registration, output missing fields warning."""
        content = """\
---
description: Use when testing nameless skills
---
"""
        out, _, registry = self._run_main(
            monkeypatch,
            capsys,
            tmp_path,
            {"tool_name": "Write", "tool_input": {}},
            skill_content=content,
        )
        assert "systemMessage" in out
        assert "missing fields" in out["systemMessage"].lower()
        assert registry["skills"] == []

    # ── tool_input.path compat (Edit uses path instead of file_path) ──

    def test_path_field_fallback(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
        tmp_path: Path,
    ) -> None:
        """tool_input uses path instead of file_path -> still detects SKILL.md."""
        skill_file = tmp_path / ".claude" / "skills" / "alt" / "SKILL.md"
        skill_file.parent.mkdir(parents=True, exist_ok=True)
        skill_file.write_text(VALID_FRONTMATTER)

        state_file = tmp_path / ".claude" / "skill_forge_state.json"
        registry_file = tmp_path / ".claude" / "skills" / "skill_registry.json"

        hook_input = {
            "tool_name": "Write",
            "tool_input": {"path": str(skill_file)},
        }
        monkeypatch.setattr("sys.stdin", StringIO(json.dumps(hook_input)))
        monkeypatch.setattr(
            "skill_forge_post_tool.load_state", lambda: {"tool_calls": 0}
        )
        monkeypatch.setattr(
            "skill_forge_post_tool.save_state",
            lambda s: (
                state_file.parent.mkdir(parents=True, exist_ok=True),
                state_file.write_text(json.dumps(s)),
            ),
        )
        monkeypatch.setattr(
            "skill_forge_post_tool.load_registry",
            lambda: {"version": "1", "skills": []},
        )
        monkeypatch.setattr(
            "skill_forge_post_tool.save_registry",
            lambda r: (
                registry_file.parent.mkdir(parents=True, exist_ok=True),
                registry_file.write_text(json.dumps(r)),
            ),
        )

        main()

        out = json.loads(capsys.readouterr().out)
        assert out == {}
        registry = json.loads(registry_file.read_text())
        assert len(registry["skills"]) == 1

    # ── MultiEdit tool -> also triggers ──

    def test_multi_edit_tool_triggers(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
        tmp_path: Path,
    ) -> None:
        """MultiEdit is also in FILE_WRITE_TOOLS -> triggers registration."""
        _, _, registry = self._run_main(
            monkeypatch,
            capsys,
            tmp_path,
            {"tool_name": "MultiEdit", "tool_input": {}},
            skill_content=VALID_FRONTMATTER,
        )
        assert len(registry["skills"]) == 1
