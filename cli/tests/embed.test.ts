// Tests for the embed module — pure functions use real filesystem (tmpdir).
// embedInstall uses mocked child_process.

import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";

// Mock child_process before importing module (hoisted)
vi.mock("node:child_process", () => ({
  execSync: vi.fn(),
}));

import { execSync } from "node:child_process";
import {
  convertHooksForEmbed,
  mergeHooksIntoSettings,
  writeVersionFile,
  readVersionFile,
  removeEmbedFiles,
  detectEmbedInstall,
  embedInstall,
} from "../src/commands/embed.js";
import { embedCommandName, EMBED_COMMANDS } from "../src/types.js";

const mockExecSync = vi.mocked(execSync);

// ── convertHooksForEmbed ──────────────────────────────────────────────────

describe("convertHooksForEmbed", () => {
  it("rewrites CLAUDE_PLUGIN_ROOT hooks path to embed path", () => {
    const input = {
      hooks: {
        Stop: [
          {
            hooks: [
              {
                type: "command",
                command: 'python3 "${CLAUDE_PLUGIN_ROOT}/hooks/skill_forge_stop.py"',
              },
            ],
          },
        ],
      },
    };
    const result = convertHooksForEmbed(input);
    const stop = result.hooks.Stop[0].hooks[0];
    expect(stop.command).toContain("${CLAUDE_PROJECT_DIR}/.claude/hooks/skill-forge/");
    expect(stop.command).not.toContain("${CLAUDE_PLUGIN_ROOT}/hooks/");
    expect(stop.command).toContain("skill_forge_stop.py");
  });

  it("rewrites CLAUDE_PLUGIN_ROOT skills path to embed skills path", () => {
    const input = {
      hooks: {
        SessionStart: [
          {
            hooks: [
              {
                type: "command",
                command: 'python3 "${CLAUDE_PLUGIN_ROOT}/skills/skill-forge/scripts/phase0_load.py"',
              },
            ],
          },
        ],
      },
    };
    const result = convertHooksForEmbed(input);
    const cmd = result.hooks.SessionStart[0].hooks[0].command;
    expect(cmd).toContain("${CLAUDE_PROJECT_DIR}/.claude/skills/");
    expect(cmd).not.toContain("${CLAUDE_PLUGIN_ROOT}/skills/");
  });

  it("handles multiple hooks with mixed paths", () => {
    const input = {
      hooks: {
        PostToolUse: [
          {
            hooks: [
              {
                command: 'python3 "${CLAUDE_PLUGIN_ROOT}/hooks/skill_forge_post_tool.py"',
              },
              {
                command: 'python3 "${CLAUDE_PLUGIN_ROOT}/skills/skill-forge/scripts/scan_structure.py"',
              },
            ],
          },
        ],
      },
    };
    const result = convertHooksForEmbed(input);
    const hooks = result.hooks.PostToolUse[0].hooks;
    expect(hooks[0].command).toContain("${CLAUDE_PROJECT_DIR}/.claude/hooks/skill-forge/");
    expect(hooks[1].command).toContain("${CLAUDE_PROJECT_DIR}/.claude/skills/");
  });
});

// ── mergeHooksIntoSettings ────────────────────────────────────────────────

describe("mergeHooksIntoSettings", () => {
  const sfHooks = {
    hooks: {
      Stop: [
        {
          hooks: [
            {
              type: "command",
              command: 'python3 "${CLAUDE_PROJECT_DIR}/.claude/hooks/skill-forge/skill_forge_stop.py"',
            },
          ],
        },
      ],
    },
  };

  it("creates hooks section in empty settings", () => {
    const result = mergeHooksIntoSettings({}, sfHooks);
    expect(result.hooks).toBeDefined();
    expect(result.hooks.Stop).toBeDefined();
    expect(result.hooks.Stop[0].hooks[0].command).toContain("skill_forge_stop.py");
  });

  it("preserves existing user hooks when adding skill-forge hooks", () => {
    const existing = {
      hooks: {
        Stop: [
          {
            hooks: [
              {
                type: "command",
                command: "python3 /my/custom/hook.py",
              },
            ],
          },
        ],
      },
      permissions: { allow: ["Bash"] },
    };
    const result = mergeHooksIntoSettings(existing, sfHooks);
    // User hook preserved
    const stopEntries = result.hooks.Stop;
    const userEntry = stopEntries.find((e: any) =>
      JSON.stringify(e).includes("/my/custom/hook.py"),
    );
    expect(userEntry).toBeDefined();
    // SF hook added
    const sfEntry = stopEntries.find((e: any) =>
      JSON.stringify(e).includes(".claude/hooks/skill-forge/"),
    );
    expect(sfEntry).toBeDefined();
    // Permissions preserved
    expect(result.permissions).toEqual({ allow: ["Bash"] });
  });

  it("replaces old skill-forge hooks on re-embed", () => {
    const oldSfHook = {
      hooks: [
        {
          type: "command",
          command: 'python3 "${CLAUDE_PROJECT_DIR}/.claude/hooks/skill-forge/skill_forge_stop.py"',
        },
      ],
    };
    const existing = {
      hooks: {
        Stop: [
          // old SF entry
          oldSfHook,
          // user entry
          {
            hooks: [{ type: "command", command: "python3 /user/hook.py" }],
          },
        ],
      },
    };
    const result = mergeHooksIntoSettings(existing, sfHooks);
    const stopEntries = result.hooks.Stop;
    // Only one SF entry — no duplicates
    const sfEntries = stopEntries.filter((e: any) =>
      JSON.stringify(e).includes(".claude/hooks/skill-forge/"),
    );
    expect(sfEntries.length).toBe(1);
    // User entry still present
    const userEntry = stopEntries.find((e: any) =>
      JSON.stringify(e).includes("/user/hook.py"),
    );
    expect(userEntry).toBeDefined();
  });

  it("merges hooks from multiple events", () => {
    const multiHooks = {
      hooks: {
        Stop: [{ hooks: [{ command: '"${CLAUDE_PROJECT_DIR}/.claude/hooks/skill-forge/stop.py"' }] }],
        SessionStart: [{ hooks: [{ command: '"${CLAUDE_PROJECT_DIR}/.claude/hooks/skill-forge/start.py"' }] }],
      },
    };
    const result = mergeHooksIntoSettings({}, multiHooks);
    expect(result.hooks.Stop).toBeDefined();
    expect(result.hooks.SessionStart).toBeDefined();
  });
});

// ── writeVersionFile / readVersionFile ────────────────────────────────────

describe("writeVersionFile / readVersionFile", () => {
  let tmpDir: string;

  beforeEach(() => {
    tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "sf-embed-"));
  });

  afterEach(() => {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  });

  it("round-trips write then read", () => {
    const filePath = path.join(tmpDir, "sub", "version.json");
    writeVersionFile(filePath, "0.5.0");
    const result = readVersionFile(filePath);
    expect(result).not.toBeNull();
    expect(result!.version).toBe("0.5.0");
    expect(result!.installed).toMatch(/^\d{4}-\d{2}-\d{2}T/);
  });

  it("auto-creates parent dirs", () => {
    const filePath = path.join(tmpDir, "deep", "nested", "version.json");
    writeVersionFile(filePath, "1.2.3");
    expect(fs.existsSync(filePath)).toBe(true);
  });

  it("returns null for missing file", () => {
    const result = readVersionFile(path.join(tmpDir, "nonexistent.json"));
    expect(result).toBeNull();
  });

  it("returns null for invalid JSON", () => {
    const filePath = path.join(tmpDir, "bad.json");
    fs.writeFileSync(filePath, "not json");
    const result = readVersionFile(filePath);
    expect(result).toBeNull();
  });
});

// ── removeEmbedFiles ──────────────────────────────────────────────────────

describe("removeEmbedFiles", () => {
  let tmpDir: string;

  beforeEach(() => {
    tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "sf-remove-"));
  });

  afterEach(() => {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  });

  function setupFullEmbed(root: string) {
    // SF command files (prefixed, as embed installs them)
    const commandsDir = path.join(root, ".claude", "commands");
    fs.mkdirSync(commandsDir, { recursive: true });
    fs.writeFileSync(path.join(commandsDir, embedCommandName("scan.md")), "scan");
    fs.writeFileSync(path.join(commandsDir, embedCommandName("create.md")), "create");
    fs.writeFileSync(path.join(commandsDir, embedCommandName("improve.md")), "improve");
    // User command file
    fs.writeFileSync(path.join(commandsDir, "my-command.md"), "user");

    // SF skills dir
    const sfSkills = path.join(root, ".claude", "skills", "skill-forge");
    fs.mkdirSync(sfSkills, { recursive: true });
    fs.writeFileSync(path.join(sfSkills, "SKILL.md"), "skill");

    // SF hooks dir + version.json
    const sfHooks = path.join(root, ".claude", "hooks", "skill-forge");
    fs.mkdirSync(sfHooks, { recursive: true });
    fs.writeFileSync(path.join(sfHooks, "version.json"), JSON.stringify({ version: "0.5.0" }));
    fs.writeFileSync(path.join(sfHooks, "skill_forge_stop.py"), "# stop");

    // settings.json with SF + user hooks
    const settingsPath = path.join(root, ".claude", "settings.json");
    const settings = {
      hooks: {
        Stop: [
          {
            hooks: [
              {
                type: "command",
                command: `python3 "\${CLAUDE_PROJECT_DIR}/.claude/hooks/skill-forge/skill_forge_stop.py"`,
              },
            ],
          },
          {
            hooks: [{ type: "command", command: "python3 /user/custom.py" }],
          },
        ],
        SessionStart: [
          {
            hooks: [
              {
                type: "command",
                command: `python3 "\${CLAUDE_PROJECT_DIR}/.claude/hooks/skill-forge/skill_forge_session_start.py"`,
              },
            ],
          },
        ],
      },
      permissions: { allow: ["Bash(*)", "Read"] },
      env: { MY_VAR: "hello" },
    };
    fs.writeFileSync(settingsPath, JSON.stringify(settings, null, 2));
  }

  it("removes SF command files but keeps user command files", () => {
    setupFullEmbed(tmpDir);
    removeEmbedFiles(tmpDir);

    const commandsDir = path.join(tmpDir, ".claude", "commands");
    expect(fs.existsSync(path.join(commandsDir, embedCommandName("scan.md")))).toBe(false);
    expect(fs.existsSync(path.join(commandsDir, embedCommandName("create.md")))).toBe(false);
    expect(fs.existsSync(path.join(commandsDir, embedCommandName("improve.md")))).toBe(false);
    expect(fs.existsSync(path.join(commandsDir, "my-command.md"))).toBe(true);
  });

  it("removes legacy unprefixed command files on uninstall", () => {
    const commandsDir = path.join(tmpDir, ".claude", "commands");
    fs.mkdirSync(commandsDir, { recursive: true });
    for (const file of EMBED_COMMANDS) {
      fs.writeFileSync(path.join(commandsDir, file), "legacy");
    }

    removeEmbedFiles(tmpDir);

    for (const file of EMBED_COMMANDS) {
      expect(fs.existsSync(path.join(commandsDir, file))).toBe(false);
    }
  });

  it("removes .claude/skills/skill-forge/ directory", () => {
    setupFullEmbed(tmpDir);
    removeEmbedFiles(tmpDir);

    const sfSkills = path.join(tmpDir, ".claude", "skills", "skill-forge");
    expect(fs.existsSync(sfSkills)).toBe(false);
    // Parent skills dir should still exist (don't nuke user skills)
    const skillsDir = path.join(tmpDir, ".claude", "skills");
    expect(fs.existsSync(skillsDir)).toBe(true);
  });

  it("removes .claude/hooks/skill-forge/ directory", () => {
    setupFullEmbed(tmpDir);
    removeEmbedFiles(tmpDir);

    const sfHooks = path.join(tmpDir, ".claude", "hooks", "skill-forge");
    expect(fs.existsSync(sfHooks)).toBe(false);
  });

  it("cleans SF hooks from settings.json while keeping user hooks and permissions", () => {
    setupFullEmbed(tmpDir);
    removeEmbedFiles(tmpDir);

    const settingsPath = path.join(tmpDir, ".claude", "settings.json");
    const settings = JSON.parse(fs.readFileSync(settingsPath, "utf-8"));

    // SF Stop hook removed
    const stopEntries: any[] = settings.hooks?.Stop ?? [];
    const sfStop = stopEntries.find((e: any) =>
      JSON.stringify(e).includes(".claude/hooks/skill-forge/"),
    );
    expect(sfStop).toBeUndefined();

    // User Stop hook preserved
    const userStop = stopEntries.find((e: any) =>
      JSON.stringify(e).includes("/user/custom.py"),
    );
    expect(userStop).toBeDefined();

    // SessionStart event removed entirely (only had SF entries)
    expect(settings.hooks?.SessionStart).toBeUndefined();

    // Permissions and env preserved
    expect(settings.permissions).toEqual({ allow: ["Bash(*)", "Read"] });
    expect(settings.env).toEqual({ MY_VAR: "hello" });
  });

  it("deletes empty hooks object after cleanup", () => {
    setupFullEmbed(tmpDir);
    // Overwrite settings with only SF hooks
    const settingsPath = path.join(tmpDir, ".claude", "settings.json");
    const settings = {
      hooks: {
        Stop: [
          {
            hooks: [
              {
                type: "command",
                command: `python3 "\${CLAUDE_PROJECT_DIR}/.claude/hooks/skill-forge/stop.py"`,
              },
            ],
          },
        ],
      },
    };
    fs.writeFileSync(settingsPath, JSON.stringify(settings, null, 2));

    removeEmbedFiles(tmpDir);

    const result = JSON.parse(fs.readFileSync(settingsPath, "utf-8"));
    // hooks key should be gone since all events are empty
    expect(result.hooks).toBeUndefined();
  });

  it("no-op when embed files don't exist", () => {
    // No setup — just an empty tmpDir
    // Should not throw
    expect(() => removeEmbedFiles(tmpDir)).not.toThrow();
  });
});

// ── detectEmbedInstall ────────────────────────────────────────────────────

describe("detectEmbedInstall", () => {
  let tmpDir: string;

  beforeEach(() => {
    tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "sf-detect-"));
  });

  afterEach(() => {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  });

  it("returns true when version.json exists", () => {
    const versionDir = path.join(tmpDir, ".claude", "hooks", "skill-forge");
    fs.mkdirSync(versionDir, { recursive: true });
    fs.writeFileSync(
      path.join(versionDir, "version.json"),
      JSON.stringify({ version: "0.5.0" }),
    );
    expect(detectEmbedInstall(tmpDir)).toBe(true);
  });

  it("returns false when version.json missing", () => {
    expect(detectEmbedInstall(tmpDir)).toBe(false);
  });
});

// ── embedInstall ──────────────────────────────────────────────────────────

describe("embedInstall", () => {
  let tmpDir: string;

  beforeEach(() => {
    tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "sf-install-"));
    vi.clearAllMocks();
  });

  afterEach(() => {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  });

  /** Build a minimal tarball structure in a dir that mimics extracted release */
  function buildFakeExtract(extractDir: string) {
    // commands/
    const commandsDir = path.join(extractDir, "commands");
    fs.mkdirSync(commandsDir, { recursive: true });
    fs.writeFileSync(path.join(commandsDir, "scan.md"), "# scan");
    fs.writeFileSync(path.join(commandsDir, "create.md"), "# create");
    fs.writeFileSync(path.join(commandsDir, "improve.md"), "# improve");

    // skills/skill-forge/
    const sfSkillDir = path.join(extractDir, "skills", "skill-forge");
    fs.mkdirSync(sfSkillDir, { recursive: true });
    fs.writeFileSync(path.join(sfSkillDir, "SKILL.md"), "# skill");

    // hooks/
    const hooksDir = path.join(extractDir, "hooks");
    fs.mkdirSync(hooksDir, { recursive: true });
    fs.writeFileSync(path.join(hooksDir, "skill_forge_stop.py"), "# stop");
    fs.writeFileSync(
      path.join(hooksDir, "hooks.json"),
      JSON.stringify({
        hooks: {
          Stop: [
            {
              hooks: [
                {
                  type: "command",
                  command: `python3 "\${CLAUDE_PLUGIN_ROOT}/hooks/skill_forge_stop.py"`,
                },
              ],
            },
          ],
        },
      }),
    );

  }

  /**
   * Mock factory for execSync — routes gh/tar commands with per-test overrides.
   * Returns the captured tmp dir so tests can assert on it.
   */
  function makeMockExec(opts: {
    throwOnLatest?: boolean;
    throwOnTar?: boolean;
    tag?: string;
  } = {}): { capturedTmpDir: () => string } {
    const tag = opts.tag ?? "v0.5.0";
    let tmpDirCapture = "";

    mockExecSync.mockImplementation((cmd: string) => {
      const cmdStr = typeof cmd === "string" ? cmd : String(cmd);

      if (cmdStr.includes("releases/latest")) {
        if (opts.throwOnLatest) throw new Error("should not call releases/latest when tag is supplied");
        return `${tag}\n`;
      }

      if (cmdStr.includes("release download")) {
        const dirMatch = cmdStr.match(/--dir\s+"?([^"\s]+)"?/);
        const dir = dirMatch ? dirMatch[1]! : "";
        tmpDirCapture = dir;
        fs.mkdirSync(dir, { recursive: true });
        fs.writeFileSync(path.join(dir, `skill-forge-${tag}.tar.gz`), "fake");
        return "";
      }

      if (cmdStr.includes("tar")) {
        if (opts.throwOnTar) throw new Error("tar failed");
        buildFakeExtract(tmpDirCapture);
        return "";
      }

      return "";
    });

    return { capturedTmpDir: () => tmpDirCapture };
  }

  it("installs files, converts hooks, writes version, returns version string", () => {
    makeMockExec();

    const version = embedInstall(tmpDir);

    expect(version).toBe("0.5.0");

    // Commands installed with plugin prefix
    expect(fs.existsSync(path.join(tmpDir, ".claude", "commands", embedCommandName("scan.md")))).toBe(true);
    expect(fs.existsSync(path.join(tmpDir, ".claude", "commands", embedCommandName("create.md")))).toBe(true);
    expect(fs.existsSync(path.join(tmpDir, ".claude", "commands", embedCommandName("improve.md")))).toBe(true);

    // skills/skill-forge installed
    expect(fs.existsSync(path.join(tmpDir, ".claude", "skills", "skill-forge", "SKILL.md"))).toBe(true);

    // hooks installed
    expect(
      fs.existsSync(path.join(tmpDir, ".claude", "hooks", "skill-forge", "skill_forge_stop.py")),
    ).toBe(true);

    // version.json written
    const versionPath = path.join(tmpDir, ".claude", "hooks", "skill-forge", "version.json");
    expect(fs.existsSync(versionPath)).toBe(true);
    const versionData = JSON.parse(fs.readFileSync(versionPath, "utf-8"));
    expect(versionData.version).toBe("0.5.0");

    // settings.json written with converted hooks
    const settingsPath = path.join(tmpDir, ".claude", "settings.json");
    expect(fs.existsSync(settingsPath)).toBe(true);
    const settings = JSON.parse(fs.readFileSync(settingsPath, "utf-8"));
    const stopCmd = settings.hooks?.Stop?.[0]?.hooks?.[0]?.command ?? "";
    expect(stopCmd).toContain("${CLAUDE_PROJECT_DIR}/.claude/hooks/skill-forge/");
    expect(stopCmd).not.toContain("${CLAUDE_PLUGIN_ROOT}");
  });

  it("uses caller-supplied tag, skips gh api fetch", () => {
    makeMockExec({ throwOnLatest: true });

    const version = embedInstall(tmpDir, "v0.5.0");

    expect(version).toBe("0.5.0");
    // Verify releases/latest was not called
    const apiCalls = mockExecSync.mock.calls.filter(
      ([c]) => String(c).includes("releases/latest"),
    );
    expect(apiCalls).toHaveLength(0);
    // Files still installed correctly
    expect(fs.existsSync(path.join(tmpDir, ".claude", "commands", embedCommandName("scan.md")))).toBe(true);
    expect(fs.existsSync(path.join(tmpDir, ".claude", "hooks", "skill-forge", "version.json"))).toBe(true);
  });

  it("handles corrupted existing settings.json gracefully", () => {
    // Pre-create a corrupted settings.json
    const settingsDir = path.join(tmpDir, ".claude");
    fs.mkdirSync(settingsDir, { recursive: true });
    fs.writeFileSync(path.join(settingsDir, "settings.json"), "NOT VALID JSON{{{");

    makeMockExec();

    // Should not throw — corrupted settings.json is handled
    const version = embedInstall(tmpDir);
    expect(version).toBe("0.5.0");

    // settings.json should now be valid (fresh merge)
    const settings = JSON.parse(fs.readFileSync(path.join(settingsDir, "settings.json"), "utf-8"));
    expect(settings.hooks).toBeDefined();
  });

  it("removes legacy unprefixed command files during install", () => {
    // Pre-create old-style bare command files (pre-prefix era)
    const commandsDir = path.join(tmpDir, ".claude", "commands");
    fs.mkdirSync(commandsDir, { recursive: true });
    fs.writeFileSync(path.join(commandsDir, "scan.md"), "old");
    fs.writeFileSync(path.join(commandsDir, "create.md"), "old");
    fs.writeFileSync(path.join(commandsDir, "improve.md"), "old");

    makeMockExec();
    embedInstall(tmpDir);

    // Legacy bare files removed
    expect(fs.existsSync(path.join(commandsDir, "scan.md"))).toBe(false);
    expect(fs.existsSync(path.join(commandsDir, "create.md"))).toBe(false);
    expect(fs.existsSync(path.join(commandsDir, "improve.md"))).toBe(false);
    // Prefixed files installed
    expect(fs.existsSync(path.join(commandsDir, embedCommandName("scan.md")))).toBe(true);
  });

  it("cleans up temp dir on tar failure", () => {
    const { capturedTmpDir } = makeMockExec({ throwOnTar: true });

    expect(() => embedInstall(tmpDir)).toThrow("tar failed");
    // Temp dir should be cleaned up
    const dir = capturedTmpDir();
    if (dir) {
      expect(fs.existsSync(dir)).toBe(false);
    }
  });
});
