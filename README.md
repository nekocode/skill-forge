# skill-forge

[中文版](README.zh.md)

A Claude Code plugin that turns skill creation, discovery, iteration, and optimization into a skill itself — a meta-system for skills.

## Why

Claude Code skills solve "how to codify workflows into reusable slash commands." But three gaps remain:

| Gap | skill-forge's Answer |
|-----|---------------------|
| Don't know when to create a skill | Auto-detects complex tasks, proactively asks |
| Don't know if a skill is well-written | Built-in 5-dimension evaluator, won't save below threshold |
| Don't know if a skill will actually trigger | Dedicated description optimization phase, eval-driven |

## Install

**Via CLI (recommended):**

```bash
npm install -g @nekocode/skill-forge
skill-forge install
```

**Or manually in Claude Code:**

```
/plugin marketplace add nekocode/skill-forge
/plugin install skill-forge
```

Run `skill-forge doctor` to verify your environment.

## Commands

| Command | What it does |
|---------|-------------|
| `/scan [prompt]` | Scan project for skill opportunities. Optional prompt as focus hint |
| `/create <prompt>` | Create a new skill from prompt. Name auto-derived |
| `/improve <prompt>` | Iterate existing skill from prompt. Target matched from registry |

**Auto mode**: After complex tasks (5+ tool calls, error recovery, user corrections), the Stop hook detects the pattern and offers to create a skill — no manual invocation needed.

## How It Works

### Design Principles

1. **Hermes Agent** — Autonomous creation with concrete trigger conditions; patch over rewrite
2. **planning-with-files** — File system as persistent working memory (context window = RAM, files = disk)
3. **Anthropic skill-creator** — Eval-driven quality: description is a separate optimization problem, 20-case trigger evals, explain *why* not just *what*
4. **DSPy** — All internal prompts (evaluation, improvement guidance) are self-optimized: structured FP/FN failure analysis, directional improvement, eval-driven variant selection

### Dual-File Security Model

External content (grep/glob/read output) goes to `skill_insights.md` (low trust, hooks don't read it). Only after validation does content get promoted to `skill_draft.md` (high trust, injected by hooks). This prevents prompt injection amplification.

### Hooks Architecture

**Skill-scoped hooks** (SKILL.md frontmatter) — only active when skill-forge is engaged:
- `UserPromptSubmit` — Inject draft header into attention window
- `PreToolUse` — Re-read draft before each tool call (prevent goal drift)
- `PostToolUse` — Prompt draft status update after Write/Edit
- `Stop` — Check for unprocessed skill opportunities

**Global hooks** (`hooks/hooks.json`, auto-registered by plugin system):
- `SessionStart` — Reset counters + inject skill inventory
- `PostToolUse` — Tool counting + registry update on SKILL.md writes
- `Stop` — Detect complex workflows, trigger auto mode
- `PreCompact` — Mark compact state to prevent false positives
- `UserPromptSubmit` — Keyword matching for skill creation prompts

### Skill Lifecycle

```
Complex task completed
  -> Stop hook / manual invocation
  -> scan -> create (draft -> research -> SKILL.md -> eval >= 6/8)
  -> .claude/skills/<name>/SKILL.md
  -> improve (diagnose -> content patch / trigger eval loop -> changelog + version bump)
  -> repeat after real usage
```

### Session Catchup

On each new session, `skill_catchup.py` scans the previous session's JSONL for uncaptured complex tasks (5+ tool calls after last draft write). Solves "forgot to save as skill yesterday."

## Evaluation Criteria

| Dimension | Max | Checks |
|-----------|-----|--------|
| Trigger quality | 3 | Complex scenarios? Pushy coverage? Do NOT use? Under 250 chars? |
| Step clarity | 3 | Concrete actions per step? Explains why, not just what? |
| Completeness | 2 | Prerequisites / verification / notes? |
| Discriminability | bonus | Assertions pass both with and without skill -> no discriminability, rewrite |

Minimum score to save: **6/8**.

## Description Writing Rules

1. **Complex scenarios, not simple verbs** — "Use when adding a new REST endpoint that requires route registration, Zod schema, test file, and index.ts update" not "Generate API endpoints"
2. **Pushy coverage** — Cover cases where users won't name the skill explicitly
3. **Do NOT use when** — Prevent trigger overlap with related skills

## CLI

The `skill-forge` CLI provides terminal-based plugin management without entering a Claude Code session.

```bash
npm install -g @nekocode/skill-forge
```

| Command | What it does |
|---------|-------------|
| `skill-forge install` | Install plugin via `claude` CLI (marketplace add + install) |
| `skill-forge uninstall` | Uninstall plugin |
| `skill-forge list` | Print skill registry for current project |
| `skill-forge registry clean` | Remove orphaned registry entries |
| `skill-forge doctor` | Diagnose environment (claude CLI, plugin, Python, project structure) |
| `skill-forge init` | Initialize `.claude/skills/` with empty registry |
| `skill-forge upgrade` | Upgrade CLI to latest version |

## Comparison

| Feature | Hand-written SKILL.md | Anthropic skill-creator | skill-forge |
|---------|----------------------|------------------------|-------------|
| Auto-discover opportunities | - | - | scan |
| Content quality evaluation | - | eval viewer | 5-dim evaluator |
| Description trigger optimization | - | run_loop.py | improve |
| Persistent working memory | - | - | draft/insights files |
| Cross-session memory | - | - | catchup.py |
| Scoped hooks (no global pollution) | - | - | frontmatter hooks |
| Injection defense | - | - | dual-file isolation |
| Self-iteration | - | - | improve skill-forge |
