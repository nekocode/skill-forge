# skill-forge

[English](README.md)

把创建、发现、迭代、优化 Claude Code skills 这件事本身做成 skill 的元系统。

## 为什么

Claude Code skills 解决了「把工作流固化成可复用 slash command」的问题，但留了三个缺口：

| 缺口 | skill-forge 的解法 |
|------|-------------------|
| 不知道什么时候该建 skill | 自动检测复杂任务，主动提问 |
| 不知道 skill 写得好不好 | 内置 4 维评估器，不达标不落盘 |
| 不知道 skill 会不会触发 | 独立的 description 优化 phase，eval 驱动 |

## 安装

**通过 CLI（推荐）：**

```bash
npm install -g @nekocode/skill-forge
skill-forge install
```

**或在 Claude Code 内手动安装（安装到用户全局目录）：**

```
/plugin marketplace add nekocode/skill-forge
/plugin install skill-forge
```

运行 `skill-forge doctor` 验证环境。

## 命令

| 命令 | 功能 |
|------|------|
| `/scan [prompt]` | 扫描项目发现 skill 机会。可选 prompt 作为聚焦提示 |
| `/create <prompt>` | 从 prompt 创建新 skill，name 自动推导 |
| `/improve <prompt>` | 从 prompt 迭代 skill，目标从 registry 匹配 |
| `/rename <old> <new>` | AI 驱动的 skill 重命名 — 更新目录、SKILL.md 全文、workspace、registry |

**Auto 模式**：完成复杂任务（5+ 工具调用）后，Stop hook 自动检测并提议创建 skill，无需手动调用。

## 工作原理

### 设计来源

1. **Hermes Agent** — 自主创建，触发条件具体化；patch 优先于 rewrite
2. **planning-with-files** — 文件系统作为持久工作记忆（Context Window = RAM，文件 = 磁盘）
3. **Anthropic skill-creator** — Eval 驱动质量保证：description 是独立优化问题，20 条触发测试，解释 *why* 而非只写 *what*
4. **DSPy** — 所有内部 prompt（评估、改进引导）均经过自优化：结构化 FP/FN 失败分析、方向性改进、eval 驱动变体选择

### 双文件安全模型

外部内容（grep/glob/read 输出）写入 `.skill-forge/insights.md`（低信任，hooks 不读）。验证合法后才提升到 `.skill-forge/draft.md`（高信任，被 hooks 反复注入）。防止 prompt injection 放大。workspace 落在项目本地 `./.skill-forge/`（与 `.claude/` 平级，不在其内），天然规避 `.claude/` 信任边界，Python/Shell 都用同一绝对路径，彻底消除旧版 slug 漂移 bug。

### Staging + Finalize

新 skill 在 `.skill-forge/staging/<name>/` 组装（SKILL.md、scripts/、CHANGELOG、.opt/），`finalize_skill.py` 通过 subprocess `shutil.copytree` 拷入 `.claude/skills/<name>/`。subprocess 不过 Claude 工具层——绕开 fresh skill dir 因无 SKILL.md 而不享信任豁免的权限门。improve mode 也走同一路径：`init_improve.py` 把 live skill 拷入 staging，Claude 在 staging 里 Edit，`finalize --mode update` 原子覆盖回目标。

### Hooks 架构

**Skill-scoped hooks**（SKILL.md frontmatter）— 仅 skill-forge 激活时生效。四个 hook 通过一个 Python 入口（`hook_draft_inject.py` / `skill_check.py`）跨平台统一：
- `UserPromptSubmit` — 注入草稿头部到注意力窗口
- `PreToolUse` — Read/Glob/Grep/Bash 前注入小剂量草稿头（防 goal drift，减 transcript 噪声）
- `PostToolUse` — Write/Edit 后提示同步 insights→draft
- `Stop` — 检查未处理机会（活跃草稿时 skip，防套娃）

**全局 hooks**（`hooks/hooks.json`，plugin 系统自动注册）：
- `SessionStart` — 重置计数器 + 注入 skill 清单
- `PostToolUse` — 工具计数 + SKILL.md 写入时更新 registry
- `Stop` — 检测复杂工作流，触发 auto 模式
- `PreCompact` — 标记 compact 状态防误报
- `UserPromptSubmit` — 关键词匹配触发创建提示

### Skill 生命周期

```
复杂任务完成
  -> Stop hook / 手动调用
  -> scan -> create（草稿 -> 研究 -> SKILL.md -> 评估 >= 6/8）
  -> .claude/skills/<name>/SKILL.md
  -> improve（诊断 -> 内容 patch / 触发 eval 循环 -> changelog + 版本递增）
  -> 真实使用后继续迭代
```

### Session Catchup

每次新 session 启动时，`skill_catchup.py` 扫描上次 session 的 JSONL，找 5+ 工具调用的未捕获任务。解决「昨天做了复杂操作但忘了存 skill」的问题。

## 评估标准

| 维度 | 满分 | 检查内容 |
|------|------|---------|
| Trigger quality | 3 | 复杂场景举例？Pushy coverage？Do NOT use？250 字以内？ |
| Step clarity | 3 | 每步有具体动作？解释 why 不只是 what？ |
| Completeness | 2 | 有 prerequisites / verification / notes？ |
| 区分度 | bonus | 有/无 skill 时 assertion 都过 → 无区分度，需改写 |

落盘最低分：**6/8**。

## Description 写作规则

1. **用复杂场景，不用简单动词** — "Use when adding a new REST endpoint that requires route registration, Zod schema, test file, and index.ts update" 而非 "Generate API endpoints"
2. **Pushy coverage** — 覆盖用户不会说出 skill 名称的场景
3. **Do NOT use when** — 防止与相关 skill 的触发重叠

## CLI

`skill-forge` CLI 提供终端直接管理 plugin，无需进入 Claude Code session。

```bash
npm install -g @nekocode/skill-forge
```

| 命令 | 功能 |
|------|------|
| `skill-forge install` | 安装 plugin（project scope 嵌入文件，user scope 走 plugin 系统） |
| `skill-forge uninstall` | 卸载 plugin |
| `skill-forge list` | 打印当前项目 skill 注册表 |
| `skill-forge rm <name> [...]` | 删除 skill（`--force` 跳过确认） |
| `skill-forge doctor` | 诊断环境（claude CLI / plugin / Python / 项目结构） |
| `skill-forge init` | 初始化 `.claude/skills/` + 空注册表 |
| `skill-forge sync` | 同步 embed 文件到最新 release（project scope） |
| `skill-forge upgrade` | 升级 CLI npm 包到最新版本 |

## 对比

| 特性 | 手写 SKILL.md | Anthropic skill-creator | skill-forge |
|------|--------------|------------------------|-------------|
| 自动发现机会 | - | - | scan |
| 内容质量评估 | - | eval viewer | 4 维评估器 |
| Description 触发优化 | - | run_loop.py | improve |
| 持久工作记忆 | - | - | draft/insights 文件 |
| 跨 session 记忆 | - | - | catchup.py |
| Hooks 内聚（不污染全局） | - | - | frontmatter hooks |
| 注入防御 | - | - | 双文件隔离 |
| 自我迭代 | - | - | improve skill-forge |
