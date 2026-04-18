---
description: Rename a skill — updates directory, all file references, workspace, and registry. Handles both project and user scope.
---

Rename a skill. `$ARGUMENTS` is `<old-name> <new-name>`.

All work is delegated to `rename_skill.py` so Claude never has to shell out
`mv`, Write `skill_registry.json` directly, or Edit files under
`<old>-workspace/` — each of those paths triggers a permission prompt
(unstable Bash allowlist / outside skill-dir trust exemption).

## Steps

1. **Parse args.** Extract `old-name` and `new-name` from `$ARGUMENTS`.
   If missing, ask the user with `AskUserQuestion` (load via
   `ToolSearch select:AskUserQuestion` if not in scope).

2. **Dry-run to build the plan.**
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/skill-forge/scripts/rename_skill.py" \
     "<old-name>" "<new-name>" --dry-run
   ```
   The script auto-detects scope (project `.claude/skills/` first, else user
   `~/.claude/skills/`). Pass `--scope project` or `--scope user` to force.

3. **Review output.** The plan lists every file edit, directory rename, and
   the registry entry update. If it starts with `Errors (aborting):`, stop
   and report the errors — do NOT attempt manual workarounds.

4. **Ask for confirmation** with `AskUserQuestion`, showing the plan.
   Options: `Apply` / `Cancel`.

5. **Apply (on Apply)** — same command without `--dry-run`:
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/skill-forge/scripts/rename_skill.py" \
     "<old-name>" "<new-name>"
   ```
   The script prints `Done. Renamed ...` on success. Relay that to the user.

## Notes

- The script guards against renaming while an active draft references the
  old name — it will error out and ask you to finish the current
  create/improve session first.
- Legacy `<old>-workspace/` sibling dirs (from before `.opt/` migration) are
  renamed too, with a warning suggesting manual migration into `<new>/.opt/`.
