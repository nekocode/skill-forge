import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import { run } from "../src/commands/init.js";

describe("init command", () => {
  let tmpDir: string;

  beforeEach(() => {
    tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "sf-init-"));
    // Make it look like a project dir so init targets it
    fs.mkdirSync(path.join(tmpDir, ".git"));
  });

  afterEach(() => {
    fs.rmSync(tmpDir, { recursive: true, force: true });
    vi.restoreAllMocks();
  });

  it("creates .claude/skills/ directory and empty registry", () => {
    run(tmpDir);

    const skillsDir = path.join(tmpDir, ".claude", "skills");
    expect(fs.existsSync(skillsDir)).toBe(true);

    const registryPath = path.join(skillsDir, "skill_registry.json");
    const registry = JSON.parse(fs.readFileSync(registryPath, "utf-8"));
    expect(registry).toEqual({ version: "1", skills: [] });
  });

  it("is idempotent — does not overwrite existing registry", () => {
    const skillsDir = path.join(tmpDir, ".claude", "skills");
    fs.mkdirSync(skillsDir, { recursive: true });
    const registryPath = path.join(skillsDir, "skill_registry.json");
    const existing = { version: "1", skills: [{ name: "test-skill" }] };
    fs.writeFileSync(registryPath, JSON.stringify(existing));

    run(tmpDir);

    const registry = JSON.parse(fs.readFileSync(registryPath, "utf-8"));
    expect(registry).toEqual(existing);
  });

  it("initializes at user scope when cwd is not a project dir", () => {
    const nonProjectDir = fs.mkdtempSync(path.join(os.tmpdir(), "sf-noproj-"));
    const fakeHome = fs.mkdtempSync(path.join(os.tmpdir(), "sf-home-"));
    vi.stubEnv("HOME", fakeHome);

    run(nonProjectDir);

    const skillsDir = path.join(fakeHome, ".claude", "skills");
    expect(fs.existsSync(skillsDir)).toBe(true);

    const registryPath = path.join(skillsDir, "skill_registry.json");
    const registry = JSON.parse(fs.readFileSync(registryPath, "utf-8"));
    expect(registry).toEqual({ version: "1", skills: [] });

    fs.rmSync(nonProjectDir, { recursive: true, force: true });
    fs.rmSync(fakeHome, { recursive: true, force: true });
  });
});
