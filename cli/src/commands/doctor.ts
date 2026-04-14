// Diagnose environment health: claude CLI, plugin status, Python, project structure.
// Each check returns a CheckResult with pass/fail/warn status.

import { execSync } from "node:child_process";
import fs from "node:fs";
import { skillsDir, resolveRoot } from "../types.js";

// Prevent indefinite hang if a subprocess blocks (e.g. claude plugin list doing network I/O)
const EXEC_TIMEOUT_MS = 10_000;

export interface CheckResult {
  name: string;
  status: "pass" | "fail" | "warn";
  message: string;
}

function checkClaudeCli(): CheckResult {
  const name = "claude CLI";
  try {
    const cmd = process.platform === "win32" ? "where claude" : "which claude";
    const location = execSync(cmd, { encoding: "utf-8", timeout: EXEC_TIMEOUT_MS }).trim();
    return { name, status: "pass", message: `Found: ${location}` };
  } catch {
    return {
      name,
      status: "fail",
      message: "Not found in PATH. Install Claude Code CLI first.",
    };
  }
}

function checkPluginInstalled(): CheckResult {
  const name = "skill-forge plugin";
  try {
    const output = execSync("claude plugin list", { encoding: "utf-8", timeout: EXEC_TIMEOUT_MS });
    if (output.split("\n").some((line) => line.trim().startsWith("skill-forge"))) {
      return { name, status: "pass", message: "Installed" };
    }
    return {
      name,
      status: "fail",
      message: "Not found. Run: skill-forge install",
    };
  } catch {
    return {
      name,
      status: "fail",
      message: "Could not run `claude plugin list` — is claude CLI available?",
    };
  }
}

function checkPython(): CheckResult {
  const name = "Python 3";
  try {
    const version = execSync("python3 --version", { encoding: "utf-8", timeout: EXEC_TIMEOUT_MS }).trim();
    return { name, status: "pass", message: version };
  } catch {
    return {
      name,
      status: "fail",
      message: "python3 not found. Install Python 3.10+ and add to PATH.",
    };
  }
}

function checkSkillsDir(cwd: string): CheckResult {
  const name = "skills directory";
  const { root, scope } = resolveRoot(cwd);
  if (fs.existsSync(skillsDir(root))) {
    return { name, status: "pass", message: `Found [${scope}]` };
  }
  return {
    name,
    status: "warn",
    message: "Not found. Run `skill-forge init` to create.",
  };
}

export function runDoctor(projectRoot: string): CheckResult[] {
  return [
    checkClaudeCli(),
    checkPluginInstalled(),
    checkPython(),
    checkSkillsDir(projectRoot),
  ];
}

// Format check results for terminal output
export function formatResults(results: CheckResult[]): string {
  const symbols: Record<CheckResult["status"], string> = {
    pass: "\u2713",
    fail: "\u2717",
    warn: "!",
  };

  return results
    .map((r) => `[${symbols[r.status]}] ${r.name}: ${r.message}`)
    .join("\n");
}
