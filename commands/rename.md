---
description: Rename a skill — updates directory, all file references, workspace, and registry. Handles both project and user scope.
---

Rename a skill. `$ARGUMENTS` is `<old-name> <new-name>`.

## Steps

1. **Parse args.** Extract `old-name` and `new-name` from `$ARGUMENTS`. If missing, ask user.

2. **Locate registry.** Check project scope first (`.claude/skills/skill_registry.json` under project root), then user scope (`~/.claude/skills/skill_registry.json`). Use whichever has the skill. If neither, error.

3. **Validate.** `old-name` must exist in registry. `new-name` must NOT exist. `old-name` must differ from `new-name`.

4. **Abort if active draft references old name.** Check `.claude/skills/skill-forge/.workspace/draft.md` — if it exists and references `old-name`, warn user and abort (finish the improve/create session first).

5. **Scan all files for old name references.** Read and list every occurrence:
   - `.claude/skills/<old-name>/SKILL.md` — frontmatter `name:`, headings, body text, script path references
   - `.claude/skills/<old-name>/CHANGELOG.md` (if exists)
   - `.claude/skills/<old-name>/scripts/*` (if exists) — file contents referencing old name
   - `.claude/skills/<old-name>-workspace/` (if exists) — directory itself needs renaming

6. **Show planned changes and ask for confirmation.**

7. **On confirmation, execute in this order:**
   - Edit file contents FIRST (while paths are still at old location):
     - `SKILL.md`: update frontmatter `name:` field + all body references
     - `CHANGELOG.md`: update references (if exists)
     - Scripts: update references (if any)
   - Then rename directories:
     - `.claude/skills/<old-name>/` → `.claude/skills/<new-name>/`
     - `.claude/skills/<old-name>-workspace/` → `.claude/skills/<new-name>-workspace/` (if exists)
   - Finally update registry:
     - Set entry `name` to `new-name`
     - Set entry `updated` to today (`YYYY-MM-DD`)
     - Write back `skill_registry.json`

8. **Print summary** of all files modified and directories renamed.
