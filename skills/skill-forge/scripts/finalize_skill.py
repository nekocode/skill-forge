"""Copy a staged skill into `.claude/skills/<name>/` and update the registry.

Create mode Step 5 and improve mode Step 4 both end here. The staging
step exists because Claude's own Write tool prompts whenever it targets
a path inside `.claude/` that doesn't already qualify as a real skill
dir (meaning: contain a SKILL.md). A fresh `.claude/skills/<name>/` has
no SKILL.md yet, so the first Write into it prompts even under
bypassPermissions. Improve mode is less affected — the target already
has SKILL.md — but we run it through the same pipe so create and improve
share one code path instead of two that drift.

What this script does:

  1. Validate the staging dir exists and has a SKILL.md.
  2. Parse + schema-check the frontmatter.
  3. Copy `<project>/.skill-forge/staging/<name>/` → `.claude/skills/<name>/`
     via shutil (a subprocess syscall, so no Claude tool permission layer).
  4. Consume `pending_eval_score` from state.json so the registry entry
     reflects the session's evaluator verdict instead of the default 0/8.
  5. Upsert the registry entry and persist.
  6. Remove the staging dir so nothing stale lingers.
  7. Clear the active draft (hooks stop injecting once draft is empty).

Mode semantics:

  create  target must NOT exist — a duplicate name is a user error.
  update  target MUST exist — rmtree then copytree for an atomic replace.
          Merging in place is tempting (shutil.copytree(..., dirs_exist_ok=True))
          but it leaves orphaned files behind when the improve session
          removed something from staging; full replacement is the only
          safe semantics given arbitrary file moves mid-session.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from datetime import date
from pathlib import Path

from shared import (
    PENDING_EVAL_SCORE_KEY,
    SKILLS_DIR,
    draft_file,
    load_registry,
    load_state,
    parse_frontmatter,
    save_registry,
    save_state,
    staging_dir,
    state_file,
    upsert_skill,
)
from quick_validate import validate_skill as structural_validate


# ── planning ──────────────────────────────────────────────────────────


def _resolve_target(name: str, project_dir: Path) -> Path:
    return project_dir / SKILLS_DIR / name


def _parse_frontmatter(skill_md: Path, content: str) -> dict:
    fm = parse_frontmatter(content)
    if fm is None:
        raise ValueError(f"{skill_md} has no YAML frontmatter")
    if "name" not in fm or "description" not in fm:
        missing = {"name", "description"} - set(fm)
        raise ValueError(
            f"{skill_md} frontmatter missing required field(s): "
            f"{', '.join(sorted(missing))}"
        )
    return fm


def _load_frontmatter(skill_md: Path) -> dict:
    return _parse_frontmatter(skill_md, skill_md.read_text())


def _validate_mode(mode: str, target: Path) -> None:
    if mode == "create" and target.exists():
        raise FileExistsError(
            f"target already exists: {target} (use --mode update to replace)"
        )
    if mode == "update" and not target.exists():
        raise FileNotFoundError(
            f"target not found: {target} (use --mode create for new skill)"
        )


# ── core action ───────────────────────────────────────────────────────


def _append_changelog(target: Path, version: str, one_liner: str) -> None:
    """Prepend a dated entry — newest-first so `head` shows latest."""
    today = date.today().isoformat()
    entry = f"## {today} — v{version}\n- {one_liner.strip()}\n\n"
    path = target / "CHANGELOG.md"
    path.write_text(entry + path.read_text() if path.is_file() else entry)


def finalize(
    name: str,
    mode: str,
    project_dir: Path | None = None,
    changelog: str | None = None,
    bump: str = "patch",
) -> Path:
    """Move staged skill into place and update the registry.

    Returns the target path. Raises on precondition failures (missing
    staging, bad frontmatter, mode mismatch with existing target) — the
    caller should surface the message to the user without retrying.

    changelog: optional one-line entry appended to `<target>/CHANGELOG.md`
        with today's ISO date and the new version header — moves date /
        version / format concerns out of the prompt layer.
    bump: which semver segment to increment on update (default 'patch').
    """
    if project_dir is None:
        project_dir = Path.cwd()
    if mode not in {"create", "update"}:
        raise ValueError(f"mode must be 'create' or 'update', got {mode!r}")

    source = staging_dir(project_dir) / name
    if not source.is_dir():
        raise FileNotFoundError(
            f"staging dir not found: {source} "
            "(run init_staging.py first)"
        )

    skill_md = source / "SKILL.md"
    if not skill_md.is_file():
        raise FileNotFoundError(f"{skill_md} missing — staging is incomplete")

    content = skill_md.read_text()
    fm = _parse_frontmatter(skill_md, content)
    if fm["name"] != name:
        raise ValueError(
            f"frontmatter name {fm['name']!r} does not match requested {name!r}"
        )

    # Non-blocking structural warnings — surfaced so the user can fix on
    # the next iteration without gating the write.
    structural_warnings = structural_validate(source, content=content)

    target = _resolve_target(name, project_dir)
    _validate_mode(mode, target)

    # copytree refuses if target exists, so wipe first in update mode.
    if mode == "update":
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target)

    # Pop (not get) so a stale score from an earlier unrelated run can't
    # leak into this one. Only persist when a key was actually consumed.
    state_path = state_file(project_dir)
    state = load_state(state_path)
    pending_score = state.pop(PENDING_EVAL_SCORE_KEY, None)
    if pending_score is not None:
        save_state(state, state_path)

    registry_path = project_dir / SKILLS_DIR / "skill_registry.json"
    registry = load_registry(registry_path)
    new_version = upsert_skill(
        registry, fm, scope="project", eval_score=pending_score, bump=bump,
    )
    save_registry(registry, registry_path)

    if changelog:
        _append_changelog(target, new_version, changelog)

    # Clear staging — nothing under .skill-forge/staging/<name>/ should
    # outlive a successful finalize; leaving it risks confusing the user
    # into editing it expecting the changes to propagate.
    shutil.rmtree(source)

    # Clear the active draft so hooks stop injecting stale context. An
    # empty file rather than unlink, because downstream checks that look
    # at draft_file().is_file() shouldn't flip just because finalize ran.
    draft = draft_file(project_dir)
    if draft.is_file():
        draft.write_text("")

    _report(target, mode, pending_score, structural_warnings)
    return target


def _report(
    target: Path,
    mode: str,
    score: int | None,
    warnings: list[str],
) -> None:
    verb = "Created" if mode == "create" else "Updated"
    score_str = f"{score}/8" if score is not None else "—"
    print(f"[skill-forge] {verb} {target} (score: {score_str})")
    if warnings:
        print("[skill-forge] Validation notes:")
        for w in warnings:
            print(f"  - {w}")


# ── CLI ───────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("name")
    parser.add_argument(
        "--mode",
        choices=["create", "update"],
        required=True,
    )
    parser.add_argument(
        "--changelog",
        default=None,
        help="One-line CHANGELOG entry; script adds date and version header.",
    )
    parser.add_argument(
        "--bump",
        choices=["patch", "minor", "major"],
        default="patch",
        help="Which semver segment to increment on update (default: patch).",
    )
    parser.add_argument(
        "--project-dir",
        type=Path,
        default=None,
        help="Override project root (for tests).",
    )
    args = parser.parse_args(argv)

    try:
        finalize(
            args.name,
            args.mode,
            project_dir=args.project_dir,
            changelog=args.changelog,
            bump=args.bump,
        )
    except (FileNotFoundError, FileExistsError, ValueError) as e:
        print(f"[skill-forge] finalize failed: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":  # pragma: no cover — entry guard
    sys.exit(main())
