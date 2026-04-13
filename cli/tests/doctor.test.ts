import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import type { CheckResult } from "../src/commands/doctor.js";

// Mock child_process to control exec results
vi.mock("node:child_process", () => ({
  execSync: vi.fn(),
}));

import { execSync } from "node:child_process";
import { runDoctor } from "../src/commands/doctor.js";

const mockExecSync = vi.mocked(execSync);

describe("doctor command", () => {
  let tmpDir: string;

  beforeEach(() => {
    tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "sf-doc-"));
    vi.clearAllMocks();
  });

  afterEach(() => {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  });

  it("passes all checks when environment is healthy", () => {
    // Setup: claude CLI found, plugin listed, python3 available
    mockExecSync.mockImplementation((cmd: string) => {
      if (typeof cmd !== "string") return "";
      if (cmd.includes("which claude") || cmd.includes("where claude"))
        return "/usr/local/bin/claude";
      if (cmd.includes("plugin list"))
        return "skill-forge  0.2.0  installed";
      if (cmd.includes("python3 --version")) return "Python 3.12.0";
      return "";
    });

    // Setup: .claude/skills/ exists
    fs.mkdirSync(path.join(tmpDir, ".claude", "skills"), { recursive: true });

    const results = runDoctor(tmpDir);
    const allPassed = results.every((r: CheckResult) => r.status === "pass");
    expect(allPassed).toBe(true);
    expect(results.length).toBeGreaterThanOrEqual(4);
  });

  it("fails claude CLI check when not in PATH", () => {
    mockExecSync.mockImplementation(() => {
      throw new Error("not found");
    });

    const results = runDoctor(tmpDir);
    const claudeCheck = results.find((r: CheckResult) =>
      r.name.includes("claude"),
    );
    expect(claudeCheck?.status).toBe("fail");
  });

  it("fails plugin check when skill-forge not in plugin list", () => {
    mockExecSync.mockImplementation((cmd: string) => {
      if (typeof cmd !== "string") return "";
      if (cmd.includes("which claude") || cmd.includes("where claude"))
        return "/usr/local/bin/claude";
      if (cmd.includes("plugin list")) return "some-other-plugin  1.0.0";
      if (cmd.includes("python3 --version")) return "Python 3.12.0";
      return "";
    });

    fs.mkdirSync(path.join(tmpDir, ".claude", "skills"), { recursive: true });

    const results = runDoctor(tmpDir);
    const pluginCheck = results.find((r: CheckResult) =>
      r.name.includes("plugin"),
    );
    expect(pluginCheck?.status).toBe("fail");
  });

  it("warns when .claude/skills/ does not exist", () => {
    mockExecSync.mockImplementation((cmd: string) => {
      if (typeof cmd !== "string") return "";
      if (cmd.includes("which claude") || cmd.includes("where claude"))
        return "/usr/local/bin/claude";
      if (cmd.includes("plugin list")) return "skill-forge  0.2.0";
      if (cmd.includes("python3 --version")) return "Python 3.12.0";
      return "";
    });

    const results = runDoctor(tmpDir);
    const skillsDirCheck = results.find((r: CheckResult) =>
      r.name.includes("skills"),
    );
    expect(skillsDirCheck?.status).toBe("warn");
  });
});
