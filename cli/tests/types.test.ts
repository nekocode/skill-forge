import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import { resolveRoot, GITHUB_REPO, EMBED_VERSION_FILE, EMBED_HOOKS_DIR, EMBED_COMMANDS } from "../src/types.js";

describe("resolveRoot", () => {
  let tmpDir: string;

  beforeEach(() => {
    tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "sf-resolve-"));
  });

  afterEach(() => {
    fs.rmSync(tmpDir, { recursive: true, force: true });
    vi.restoreAllMocks();
  });

  it("returns project scope when project registry exists", () => {
    const skillsDir = path.join(tmpDir, ".claude", "skills");
    fs.mkdirSync(skillsDir, { recursive: true });
    fs.writeFileSync(
      path.join(skillsDir, "skill_registry.json"),
      JSON.stringify({ version: "1", skills: [] }),
    );

    const result = resolveRoot(tmpDir);
    expect(result).toEqual({ root: tmpDir, scope: "project" });
  });

  it("falls back to user scope when project has no registry", () => {
    // Simulate user-level registry via HOME override
    const fakeHome = fs.mkdtempSync(path.join(os.tmpdir(), "sf-home-"));
    vi.stubEnv("HOME", fakeHome);

    const userSkillsDir = path.join(fakeHome, ".claude", "skills");
    fs.mkdirSync(userSkillsDir, { recursive: true });
    fs.writeFileSync(
      path.join(userSkillsDir, "skill_registry.json"),
      JSON.stringify({ version: "1", skills: [] }),
    );

    const result = resolveRoot(tmpDir);
    expect(result).toEqual({ root: fakeHome, scope: "user" });

    fs.rmSync(fakeHome, { recursive: true, force: true });
  });

  it("defaults to project scope when neither scope has registry", () => {
    const result = resolveRoot(tmpDir);
    expect(result).toEqual({ root: tmpDir, scope: "project" });
  });

  it("prefers project over user when both exist", () => {
    // Project registry
    const projectSkillsDir = path.join(tmpDir, ".claude", "skills");
    fs.mkdirSync(projectSkillsDir, { recursive: true });
    fs.writeFileSync(
      path.join(projectSkillsDir, "skill_registry.json"),
      JSON.stringify({ version: "1", skills: [] }),
    );

    // User registry
    const fakeHome = fs.mkdtempSync(path.join(os.tmpdir(), "sf-home-"));
    vi.stubEnv("HOME", fakeHome);
    const userSkillsDir = path.join(fakeHome, ".claude", "skills");
    fs.mkdirSync(userSkillsDir, { recursive: true });
    fs.writeFileSync(
      path.join(userSkillsDir, "skill_registry.json"),
      JSON.stringify({ version: "1", skills: [] }),
    );

    const result = resolveRoot(tmpDir);
    expect(result).toEqual({ root: tmpDir, scope: "project" });

    fs.rmSync(fakeHome, { recursive: true, force: true });
  });
});

describe("embed constants", () => {
  it("exports GitHub repo identifier", () => {
    expect(GITHUB_REPO).toBe("nekocode/skill-forge");
  });

  it("exports embed version file path", () => {
    expect(EMBED_VERSION_FILE).toBe(".claude/hooks/skill-forge/version.json");
  });

  it("exports embed hooks directory", () => {
    expect(EMBED_HOOKS_DIR).toBe(".claude/hooks/skill-forge");
  });

  it("exports embed command filenames", () => {
    expect(EMBED_COMMANDS).toEqual(["scan.md", "create.md", "improve.md"]);
  });
});
