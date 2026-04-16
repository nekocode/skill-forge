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
    // SF command files
    const commandsDir = path.join(root, ".claude", "commands");
    fs.mkdirSync(commandsDir, { recursive: true });
    fs.writeFileSync(path.join(commandsDir, "scan.md"), "scan");
    fs.writeFileSync(path.join(commandsDir, "create.md"), "create");
    fs.writeFileSync(path.join(commandsDir, "improve.md"), "improve");
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
    expect(fs.existsSync(path.join(commandsDir, "scan.md"))).toBe(false);
    expect(fs.existsSync(path.join(commandsDir, "create.md"))).toBe(false);
    expect(fs.existsSync(path.join(commandsDir, "improve.md"))).toBe(false);
    expect(fs.existsSync(path.join(commandsDir, "my-command.md"))).toBe(true);
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

  it("installs files, converts hooks, writes version, returns version string", () => {
    let capturedTmpDir = "";

    mockExecSync.mockImplementation((cmd: string) => {
      const cmdStr = typeof cmd === "string" ? cmd : String(cmd);

      if (cmdStr.includes("releases/latest")) {
        return "v0.5.0\n";
      }

      if (cmdStr.includes("release download")) {
        // Extract the --dir argument from the command
        const dirMatch = cmdStr.match(/--dir\s+"?([^"\s]+)"?/);
        const dir = dirMatch ? dirMatch[1]! : "";
        capturedTmpDir = dir;
        // Create a fake tarball file in the dir
        fs.mkdirSync(dir, { recursive: true });
        fs.writeFileSync(path.join(dir, "skill-forge-v0.5.0.tar.gz"), "fake");
        return "";
      }

      if (cmdStr.includes("tar")) {
        // Extract tar — build fake structure in capturedTmpDir
        buildFakeExtract(capturedTmpDir);
        return "";
      }

      return "";
    });

    const version = embedInstall(tmpDir);

    expect(version).toBe("0.5.0");

    // Commands installed
    expect(fs.existsSync(path.join(tmpDir, ".claude", "commands", "scan.md"))).toBe(true);
    expect(fs.existsSync(path.join(tmpDir, ".claude", "commands", "create.md"))).toBe(true);
    expect(fs.existsSync(path.join(tmpDir, ".claude", "commands", "improve.md"))).toBe(true);

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

  it("cleans up temp dir even on error", () => {
    let createdTmpDir = "";

    mockExecSync.mockImplementation((cmd: string) => {
      const cmdStr = typeof cmd === "string" ? cmd : String(cmd);
      if (cmdStr.includes("releases/latest")) return "v0.5.0\n";
      if (cmdStr.includes("release download")) {
        const dirMatch = cmdStr.match(/--dir\s+"?([^"\s]+)"?/);
        createdTmpDir = dirMatch ? dirMatch[1]! : "";
        fs.mkdirSync(createdTmpDir, { recursive: true });
        return "";
      }
      // tar fails
      if (cmdStr.includes("tar")) throw new Error("tar failed");
      return "";
    });

    expect(() => embedInstall(tmpDir)).toThrow();
    // Temp dir should be cleaned up
    if (createdTmpDir) {
      expect(fs.existsSync(createdTmpDir)).toBe(false);
    }
  });
});
