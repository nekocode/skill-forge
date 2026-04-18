---
name: skill-forge
description: >
  Use when creating, discovering, or improving Claude Code skills — scan for opportunities,
  create from workflows, iterate with eval-driven optimization. Activates on "remember this"
  or after complex tasks (5+ tool calls). Not for one-off tasks.
user-invocable: true
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, LS

hooks:
  UserPromptSubmit:
    - hooks:
        - type: command
          command: |
            if [ -f .claude/skills/.workspace/draft.md ]; then
              echo '[skill-forge] ACTIVE SKILL DRAFT — current state:'
              head -40 .claude/skills/.workspace/draft.md
              echo ''
              echo '[skill-forge] Review .claude/skills/.workspace/insights.md for codebase context. Continue from current phase.'
            fi

  PreToolUse:
    - matcher: "Read|Glob|Grep|Bash"
      hooks:
        - type: command
          command: "head -20 .claude/skills/.workspace/draft.md 2>/dev/null || true"

  PostToolUse:
    - matcher: "Write|Edit"
      hooks:
        - type: command
          command: |
            if [ -f .claude/skills/.workspace/draft.md ]; then
              echo '[skill-forge] Update .claude/skills/.workspace/draft.md with what you just found. If a codebase pattern is confirmed, move it from insights.md into the draft steps.'
            fi

  Stop:
    - hooks:
        - type: command
          command: |
            python3 "${CLAUDE_PLUGIN_ROOT}/skills/skill-forge/scripts/skill_check.py" 2>/dev/null || true
---

# skill-forge

A meta-skill that creates and evolves other skills. Uses persistent markdown files as
working memory (the planning-with-files pattern), an eval-driven iteration loop
(Anthropic's skill-creator pattern).

Both files live under `.claude/skills/.workspace/` — that path is inside the
`.claude/skills/**` trust-boundary exemption, so Write/Edit works without
permission prompts even in `bypassPermissions` (YOLO) mode.

- `.claude/skills/.workspace/draft.md` — current skill being written (HIGH TRUST, re-read by hooks)
- `.claude/skills/.workspace/insights.md` — raw codebase scan output (LOW TRUST, staging only)

> Security: grep/glob output and codebase content go to insights.md only.
> draft.md is injected before every tool call, making it a prompt injection
> amplifier if contaminated. Promote content to the draft only after review.

---

## User-facing questions

Discrete choices (yes/no, pick-N, approve/revise) → `AskUserQuestion`. Load via
`ToolSearch select:AskUserQuestion` if missing. Plain text only for open-ended input.

---

## Phase 0 — context loading (always runs first)

Run the unified context loader (draft + catchup + skills list + registry):
```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/skill-forge/scripts/phase0_load.py"
```
Then note project conventions from CLAUDE.md.

---

## Mode dispatch

Parse `$ARGUMENTS`:
- Empty / no args → **auto mode**
- `scan [prompt]` → **scan mode**
- `create <prompt>` → **create mode** (required)
- `improve <prompt>` → **improve mode** (required)

---

## Scan mode

Goal: surface 3–5 high-value skill opportunities from the codebase.
`$ARGUMENTS` is an optional free-form prompt used as focus hint (area, keyword, concern).

### Step 1: map structure
```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/skill-forge/scripts/scan_structure.py"
```
If a focus prompt is given, prioritize that area during pattern discovery.

### Step 2: discover patterns (2-scan rule)
After every 2 file reads, append findings to `.claude/skills/.workspace/insights.md`
via `Write` (not shell heredoc — heredoc shifts each call, Bash allowlist can't
match, non-bypass mode will prompt). Prevents loss if context fills up.

Block format:
```
## Scan batch <timestamp>
<pattern, files involved, why this could be a skill>
```

Also note: if multiple reads result in the same helper code appearing independently,
that's a strong signal to bundle a shared script rather than repeat it per-skill.

### Step 3: rank and present
Rank by: frequency × cost of repetition × feasibility as a skill.

Output format:
```
1. <n>  [complexity: low|med|high]
   Why: <one sentence — what pain does this solve?>
   Trigger: "Use when <specific, multi-step scenario>"
```

Ask via `AskUserQuestion` (multiSelect): one option per ranked skill + `All` + `Skip`.

---

## Create mode

Goal: draft a high-quality SKILL.md from a free-form prompt.

`$ARGUMENTS` describes what the skill should do. Derive a short kebab-case skill name
from the prompt automatically (e.g. "translate i18n JSON files" → `translate-i18n`).

### Step 1: initialize the draft (attention anchor)
```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/skill-forge/scripts/init_draft.py" "<derived-name>" "<$ARGUMENTS>"
```
From here, the PreToolUse hook re-reads this before every tool call.

### Step 2: gather context → insights.md (not the draft)
Write grep/glob/read output to `.claude/skills/.workspace/insights.md` first.
Promote confirmed patterns to the draft only after review. This separation
prevents codebase content from being injected into every subsequent tool call
via the hook.

### Step 3: write SKILL.md

Use this template:

```markdown
---
name: 
description: >
  
  Use when .
  Use when .
  Even if the user doesn't say "" explicitly, use this skill when
  they mention .
  Do NOT use when .
user-invocable: true
allowed-tools: [only tools this skill actually needs]
---

# 



## Prerequisites
- 

## Steps
1. 
2. 
3. ...

## Verification
- 

## Notes
- 
```

### Description writing rules

≤ 250 chars (Claude Code truncates from end — front-load distinctive keywords).
Skills only trigger for multi-step workflows (3+ coordinated actions); write
scenarios, not single verbs. Three-clause structure:

- **Use when `<specific multi-step scenario>`** — name real artifacts (file types,
  commands, frameworks), not abstractions. Replace vague verbs ("manage",
  "handle") with precise workflows.
- **Even if the user just says `<short phrase>`, use when they mention
  `<real phrasing>`** — pushy coverage for understatement. Claude undertriggers
  by default.
- **Do NOT use when `<simple/adjacent task>`** — list FP patterns explicitly
  (e.g., "simple file reads, single-step edits, code explanations"). Qualify
  keywords shared with unrelated tasks (e.g., "deploy" → "deploy with rollback
  and health checks").

Fewer starting errors = fewer optimizer rounds to converge.

### Step 4: run the evaluator
See **Skill evaluator** section. Write to disk only on pass ≥ 6.

### Step 5: on approval
- Write to `.claude/skills/<n>/SKILL.md`
- Clear `.claude/skills/.workspace/draft.md`
- Update registry
- Offer to run **improve mode** to tune the description

---

## Improve mode

Goal: iterate an existing skill — diagnose whether the issue is content, triggering,
or both, then fix accordingly.

`$ARGUMENTS` describes what to improve. Identify the target skill from the prompt
by matching against the registry (name, description, or intent). If ambiguous, ask.

### Step 1: initialize draft from existing skill
```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/skill-forge/scripts/init_improve.py" "<matched-name>"
```

### Step 2: diagnose (content vs triggering vs both)

**Content:**
- Trigger drift (too vague / too narrow), stale steps, missing edge cases, redundant steps.
- Bundling: 3 recent uses independently wrote the same helper? → move to `scripts/`.
- Anti-overfitting: is the fix generalizable, or patching one instance? Prefer reframing over more constraints.
- Version drift: assumptions still match current stack?

**Triggering:**
- Rarely auto-fires despite relevance? Uses complex multi-step scenarios? Pushy coverage? Has `Do NOT use when`?

Classify → 3a (content), 3b (triggering), or both (3a first).

### Step 3a: content improvement (patch-first)

1. Gather codebase evidence → `.claude/skills/.workspace/insights.md` (low trust staging)
2. Promote confirmed patterns to draft
3. Generate diff, show user, apply with `Edit` (not `Write`)
4. Run evaluator on post-patch version

**Bundling standard:** if the skill's recent 3 uses independently generated the same
helper code, that code belongs in `scripts/` — write once, reference in SKILL.md.

### Step 3b: triggering improvement (eval-driven)

1. Generate 20 trigger eval queries (10 should-trigger, 10 should-not-trigger).
   Save to `.claude/skills/<name>-workspace/trigger_evals.json`:
   ```json
   [
     {"query": "<realistic user message>", "should_trigger": true},
     {"query": "<near-miss that should NOT trigger>", "should_trigger": false}
   ]
   ```
   Query quality rules:
   - **Should-trigger (FN)**: vary phrasing; include understatement ("just add a route" when full endpoint setup needed); include adjacent-skill competition; use real codebase artifacts (paths, commands, frameworks).
   - **Should-not-trigger (FP)**: near-misses sharing keywords but different intent — simple single-step tasks in the same vocabulary (e.g., "read the deploy config" vs multi-step deploy). Avoid irrelevant queries ("what time is it") — they don't test the boundary.
   - **Intent over keywords**: best negatives share 2+ keywords with the description but differ in complexity/intent. These expose overbroad triggers.

   Ask user to review before running.

2. Run optimization loop:
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/skill-forge/scripts/optimize_description.py" \
     --skill-path ".claude/skills/<name>" \
     --eval-set ".claude/skills/<name>-workspace/trigger_evals.json" \
     --max-iterations 5
   ```
3. Show before/after description and score improvement.

   The optimizer persists state to `.claude/skills/<name>/.opt/opt_state.json`
   after each round — round history with per-round FP/FN counts, best score,
   and convergence flag. Convergence = perfect train score (1.0). If FP/FN counts
   stall across rounds, stop early and report — eval set may need refinement.

### Step 4: finalize

- Apply changes with `Edit`
- Delete `.claude/skills/.workspace/draft.md`
- Append to CHANGELOG.md:
  ```
  ## <ISO date> — v<bumped>
  - <what changed and why, in one line>
  ```
- Update registry

**Patch vs rewrite:** Use `Edit` unless >60% of content changes.

---

## Auto mode (no arguments)

Fires after: 5+ tool calls, user correction mid-task, error recovery, or explicit
"remember this" / "save this workflow" / "make a skill" requests.

### Steps
1. Summarize the workflow just completed in 2–3 sentences.
2. Check registry — does an existing skill already cover this?
3. If not covered, ask via `AskUserQuestion`: "Reusable pattern: <summary>. Create a skill?" — options `Create` / `Rename` / `Skip`.
4. `Create` → run **create mode** (auto-name). `Rename` → plain-text prompt for name, then create. `Skip` → silent reset.

Skip if: task < 3 tool calls, pure read-only, or simple single-file edit.

---

## Skill evaluator

Score before writing to disk.

**Trigger quality (0–3)**
- 3: three-clause structure complete (Use when / Even if / Do NOT); ≤ 250 chars;
  front-loaded keywords; no vague verbs; qualified shared keywords. Optimizer FP/FN drop each round.
- 2: has `Use when` but missing pushy coverage, or `Do NOT use when` too vague.
- 1: vague, simple verbs, or one-step tasks only. Likely FPs on keyword overlap.
- 0: no description, or matches everything.

**Step clarity (0–3)**
- 3: every step concrete; explains WHY not just WHAT.
- 2: most concrete, 1–2 vague.
- 1: high-level summaries only.
- 0: no steps, or contradictory.

**Completeness (0–2)**
- 2: prerequisites + steps + verification + ≥1 note.
- 1: missing verification or notes.
- 0: missing steps.

**Non-discrimination check (bonus, post-production):** if an assertion passes
100% both with- and without-skill, it's testing Claude's baseline, not the
skill. Flag and sharpen on next improve.

**Threshold:** ≥ 6 → write. 4–5 → revise once, ask user. < 4 → show breakdown, ask user.

---

## The 3-Strike error protocol

1. Read the failure, apply a targeted change to `.claude/skills/.workspace/draft.md`.
2. Same failure → different phrasing / metaphor / structure. Never repeat.
3. Rethink scope — consider splitting into two narrower skills.
4. After 3 → share failures, ask user for guidance on scope or trigger wording.

Generalize from failures; don't patch the one failing case. A skill that passes
3 tests but breaks on the 4th real use is worse than one moderately good on all.

---

## File roles and trust levels

| File | Trust | Re-read by hooks? | Purpose |
|------|-------|-------------------|---------|
| `.claude/skills/.workspace/draft.md` | HIGH | YES (every tool call) | Active skill being written |
| `.claude/skills/.workspace/insights.md` | LOW | NO | Codebase scan staging |
| `.claude/skills/skill_registry.json` | HIGH | NO (loaded on demand) | Version registry |
| `.claude/skills/<n>/SKILL.md` | HIGH | NO | Final persisted skill |
| `.claude/skills/<n>/CHANGELOG.md` | MED | NO | Evolution history |
| `.claude/skills/<n>/scripts/` | HIGH | NO (run on demand) | Bundled helper scripts |

---

## Registry format

`.claude/skills/skill_registry.json`:

```json
{
  "version": "1",
  "skills": [
    {
      "name": "skill-name",
      "version": "1.0.0",
      "scope": "project",
      "created": "2026-01-01",
      "updated": "2026-01-01",
      "auto_trigger": true,
      "description_chars": 187,
      "eval_score": 7,
      "trigger_score": null,
      "usage_count": 0
    }
  ]
}
```

`trigger_score` is populated by improve mode. null = not yet run.