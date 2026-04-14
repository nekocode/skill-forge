"""Full test suite for skill_forge_session_start.py."""

import json
from io import StringIO

from skill_forge_session_start import MAX_SKILLS_SHOWN, main


# ── helpers ────────────────────────────────────────────────


def _make_skill(name: str, version: str = "1", auto: bool = False, updated: str = "2025-01-01") -> dict:
    """Build a single skill registry entry."""
    return {"name": name, "version": version, "auto_trigger": auto, "updated": updated}


def _run_main(monkeypatch, capsys, *, stdin_data: dict, registry: dict | None = None, state: dict | None = None):
    """Run main(), return (stdout_dict, save_state capture list).

    Mocks shared's three functions to avoid real file I/O.
    """
    if registry is None:
        registry = {"version": "1", "skills": []}
    if state is None:
        state = {"tool_calls": 5, "compacted": True}

    saved: list[dict] = []

    monkeypatch.setattr("skill_forge_session_start.load_registry", lambda: registry)
    monkeypatch.setattr("skill_forge_session_start.load_state", lambda: dict(state))
    monkeypatch.setattr("skill_forge_session_start.save_state", lambda s: saved.append(s))
    monkeypatch.setattr("sys.stdin", StringIO(json.dumps(stdin_data)))

    main()

    out = json.loads(capsys.readouterr().out)
    return out, saved


# ── TestMatcher: source field routing ────────────────────────


class TestMatcher:
    """hook_input["source"] determines whether to execute."""

    def test_startup_runs(self, monkeypatch, capsys) -> None:
        """source=startup -> normal output with additionalContext."""
        out, _ = _run_main(monkeypatch, capsys, stdin_data={"source": "startup"})
        assert "additionalContext" in out

    def test_clear_runs(self, monkeypatch, capsys) -> None:
        """source=clear -> also executes."""
        out, _ = _run_main(monkeypatch, capsys, stdin_data={"source": "clear"})
        assert "additionalContext" in out

    def test_missing_source_defaults_startup(self, monkeypatch, capsys) -> None:
        """no source field -> default startup, execute normally."""
        out, _ = _run_main(monkeypatch, capsys, stdin_data={})
        assert "additionalContext" in out

    def test_resume_skipped(self, monkeypatch, capsys) -> None:
        """source=resume -> output empty JSON, no logic triggered."""
        out, saved = _run_main(monkeypatch, capsys, stdin_data={"source": "resume"})
        assert out == {}
        assert saved == []  # save_state not called

    def test_compact_skipped(self, monkeypatch, capsys) -> None:
        """source=compact -> skip."""
        out, saved = _run_main(monkeypatch, capsys, stdin_data={"source": "compact"})
        assert out == {}
        assert saved == []

    def test_unknown_source_skipped(self, monkeypatch, capsys) -> None:
        """unknown source value -> skip."""
        out, saved = _run_main(monkeypatch, capsys, stdin_data={"source": "whatever"})
        assert out == {}
        assert saved == []


# ── TestStateReset: new session resets state ──────────────────────


class TestStateReset:
    """startup/clear resets tool_calls and compacted."""

    def test_resets_counters(self, monkeypatch, capsys) -> None:
        """all DEFAULT_STATE fields reset to zero/False."""
        state = {"tool_calls": 42, "compacted": True, "extra": "keep"}
        _, saved = _run_main(monkeypatch, capsys, stdin_data={"source": "startup"}, state=state)
        assert len(saved) == 1
        assert saved[0]["tool_calls"] == 0
        assert saved[0]["compacted"] is False

    def test_preserves_extra_fields(self, monkeypatch, capsys) -> None:
        """non-DEFAULT_STATE fields preserved."""
        state = {"tool_calls": 1, "compacted": True, "custom": "keep"}
        _, saved = _run_main(monkeypatch, capsys, stdin_data={"source": "clear"}, state=state)
        assert saved[0]["tool_calls"] == 0
        assert saved[0]["compacted"] is False
        assert saved[0]["custom"] == "keep"


# ── TestEmptyRegistry: no skills scenario ──────────────────


class TestEmptyRegistry:
    """empty registry -> prompt to scan."""

    def test_no_skills_message(self, monkeypatch, capsys) -> None:
        """output hints to run /skill-forge scan."""
        out, _ = _run_main(monkeypatch, capsys, stdin_data={"source": "startup"})
        ctx = out["additionalContext"]
        assert "no project skills yet" in ctx
        assert "/skill-forge scan" in ctx

    def test_empty_skills_list(self, monkeypatch, capsys) -> None:
        """skills=[] same behavior."""
        registry = {"version": "1", "skills": []}
        out, _ = _run_main(monkeypatch, capsys, stdin_data={"source": "startup"}, registry=registry)
        assert "no project skills yet" in out["additionalContext"]

    def test_registry_missing_skills_key(self, monkeypatch, capsys) -> None:
        """registry missing skills key -> treated as empty."""
        registry = {"version": "1"}
        out, _ = _run_main(monkeypatch, capsys, stdin_data={"source": "startup"}, registry=registry)
        assert "no project skills yet" in out["additionalContext"]


# ── TestPopulatedRegistry: has skills scenario ──────────────


class TestPopulatedRegistry:
    """non-empty registry -> display summary list."""

    def test_single_skill(self, monkeypatch, capsys) -> None:
        """single skill -> show name/version/type/date."""
        skills = [_make_skill("deploy", version="2", auto=True, updated="2025-06-01")]
        registry = {"version": "1", "skills": skills}
        out, _ = _run_main(monkeypatch, capsys, stdin_data={"source": "startup"}, registry=registry)
        ctx = out["additionalContext"]
        assert "1 project skill(s) registered" in ctx
        assert "/deploy" in ctx
        assert "v2" in ctx
        assert "[auto]" in ctx
        assert "2025-06-01" in ctx

    def test_manual_skill(self, monkeypatch, capsys) -> None:
        """auto_trigger=False -> tagged [manual]."""
        skills = [_make_skill("lint", auto=False)]
        registry = {"version": "1", "skills": skills}
        out, _ = _run_main(monkeypatch, capsys, stdin_data={"source": "startup"}, registry=registry)
        assert "[manual]" in out["additionalContext"]

    def test_auto_skill(self, monkeypatch, capsys) -> None:
        """auto_trigger=True -> tagged [auto]."""
        skills = [_make_skill("fmt", auto=True)]
        registry = {"version": "1", "skills": skills}
        out, _ = _run_main(monkeypatch, capsys, stdin_data={"source": "startup"}, registry=registry)
        assert "[auto]" in out["additionalContext"]

    def test_missing_version_fallback(self, monkeypatch, capsys) -> None:
        """skill missing version field -> show v?."""
        skills = [{"name": "test", "updated": "2025-01-01"}]
        registry = {"version": "1", "skills": skills}
        out, _ = _run_main(monkeypatch, capsys, stdin_data={"source": "startup"}, registry=registry)
        assert "v?" in out["additionalContext"]

    def test_missing_updated_fallback(self, monkeypatch, capsys) -> None:
        """skill missing updated field -> show updated ?."""
        skills = [{"name": "test", "version": "1"}]
        registry = {"version": "1", "skills": skills}
        out, _ = _run_main(monkeypatch, capsys, stdin_data={"source": "startup"}, registry=registry)
        assert "updated ?" in out["additionalContext"]

    def test_sorted_by_updated_desc(self, monkeypatch, capsys) -> None:
        """sorted by updated descending, newest first."""
        skills = [
            _make_skill("old", updated="2024-01-01"),
            _make_skill("new", updated="2025-12-31"),
            _make_skill("mid", updated="2025-06-15"),
        ]
        registry = {"version": "1", "skills": skills}
        out, _ = _run_main(monkeypatch, capsys, stdin_data={"source": "startup"}, registry=registry)
        ctx = out["additionalContext"]
        # new should precede mid, mid should precede old
        assert ctx.index("/new") < ctx.index("/mid") < ctx.index("/old")

    def test_improve_hint_present(self, monkeypatch, capsys) -> None:
        """/skill-forge improve hint at end."""
        skills = [_make_skill("a")]
        registry = {"version": "1", "skills": skills}
        out, _ = _run_main(monkeypatch, capsys, stdin_data={"source": "startup"}, registry=registry)
        assert "/skill-forge improve" in out["additionalContext"]

    def test_count_header(self, monkeypatch, capsys) -> None:
        """header line shows correct skill count."""
        skills = [_make_skill(f"s{i}") for i in range(3)]
        registry = {"version": "1", "skills": skills}
        out, _ = _run_main(monkeypatch, capsys, stdin_data={"source": "startup"}, registry=registry)
        assert "3 project skill(s) registered" in out["additionalContext"]


# ── TestMaxSkillsOverflow: exceeds MAX_SKILLS_SHOWN ──────


class TestMaxSkillsOverflow:
    """Truncate and hint when skills count > MAX_SKILLS_SHOWN."""

    def test_exactly_max_no_overflow(self, monkeypatch, capsys) -> None:
        """exactly MAX_SKILLS_SHOWN -> no '... and N more' hint."""
        skills = [_make_skill(f"s{i}", updated=f"2025-01-{i+1:02d}") for i in range(MAX_SKILLS_SHOWN)]
        registry = {"version": "1", "skills": skills}
        out, _ = _run_main(monkeypatch, capsys, stdin_data={"source": "startup"}, registry=registry)
        ctx = out["additionalContext"]
        assert "... and" not in ctx
        assert "/skill-forge list" not in ctx

    def test_overflow_shows_remainder(self, monkeypatch, capsys) -> None:
        """overflow by 1 -> show '... and 1 more'."""
        total = MAX_SKILLS_SHOWN + 1
        skills = [_make_skill(f"s{i}", updated=f"2025-01-{i+1:02d}") for i in range(total)]
        registry = {"version": "1", "skills": skills}
        out, _ = _run_main(monkeypatch, capsys, stdin_data={"source": "startup"}, registry=registry)
        ctx = out["additionalContext"]
        assert "... and 1 more" in ctx
        assert "/skill-forge list" in ctx

    def test_large_overflow(self, monkeypatch, capsys) -> None:
        """large overflow -> correctly compute remainder."""
        extra = 20
        total = MAX_SKILLS_SHOWN + extra
        skills = [_make_skill(f"s{i}", updated=f"2025-{(i % 12)+1:02d}-01") for i in range(total)]
        registry = {"version": "1", "skills": skills}
        out, _ = _run_main(monkeypatch, capsys, stdin_data={"source": "startup"}, registry=registry)
        ctx = out["additionalContext"]
        assert f"... and {extra} more" in ctx
        assert f"{total} project skill(s) registered" in ctx

    def test_only_max_skills_listed(self, monkeypatch, capsys) -> None:
        """on overflow, only MAX_SKILLS_SHOWN skill lines listed."""
        total = MAX_SKILLS_SHOWN + 5
        skills = [_make_skill(f"skill{i}", updated=f"2025-01-{i+1:02d}") for i in range(total)]
        registry = {"version": "1", "skills": skills}
        out, _ = _run_main(monkeypatch, capsys, stdin_data={"source": "startup"}, registry=registry)
        ctx = out["additionalContext"]
        # count /skillN occurrences (indented lines only)
        skill_lines = [line for line in ctx.splitlines() if line.strip().startswith("/skill")]
        assert len(skill_lines) == MAX_SKILLS_SHOWN


# ── TestMaxSkillsConstant ─────────────────────────────


class TestMaxSkillsConstant:
    """MAX_SKILLS_SHOWN exported value check."""

    def test_value(self) -> None:
        """current value is 8."""
        assert MAX_SKILLS_SHOWN == 8
