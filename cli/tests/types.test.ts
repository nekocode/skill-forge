import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import { resolveRoot, resolveTargetRoot, findProjectRoot, userHome, loadRegistry, GITHUB_REPO, EMBED_VERSION_FILE, EMBED_HOOKS_DIR, EMBED_COMMANDS, PLUGIN_NAME, embedCommandName } from "../src/types.js";

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
    const skillsDirPath = path.join(tmpDir, ".claude", "skills");
    fs.mkdirSync(skillsDirPath, { recursive: true });
    fs.writeFileSync(
      path.join(skillsDirPath, "skill_registry.json"),
      JSON.stringify({ version: "1", skills: [] }),
    );

    const result = resolveRoot(tmpDir);
    expect(result).toEqual({ root: tmpDir, scope: "project" });
  });

  it("walks up to find project root from subdirectory", () => {
    // Project root has .git + registry
    fs.mkdirSync(path.join(tmpDir, ".git"));
    const skillsDirPath = path.join(tmpDir, ".claude", "skills");
    fs.mkdirSync(skillsDirPath, { recursive: true });
    fs.writeFileSync(
      path.join(skillsDirPath, "skill_registry.json"),
      JSON.stringify({ version: "1", skills: [] }),
    );

    // Run from deep subdirectory
    const subDir = path.join(tmpDir, "src", "components");
    fs.mkdirSync(subDir, { recursive: true });

    const result = resolveRoot(subDir);
    expect(result).toEqual({ root: tmpDir, scope: "project" });
  });

  it("falls back to user scope when project has no registry", () => {
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

  it("falls back to user scope from subdirectory of non-project dir", () => {
    // No .git or .claude anywhere in tmpDir
    const subDir = path.join(tmpDir, "some", "deep");
    fs.mkdirSync(subDir, { recursive: true });

    const fakeHome = fs.mkdtempSync(path.join(os.tmpdir(), "sf-home-"));
    vi.stubEnv("HOME", fakeHome);
    const userSkillsDir = path.join(fakeHome, ".claude", "skills");
    fs.mkdirSync(userSkillsDir, { recursive: true });
    fs.writeFileSync(
      path.join(userSkillsDir, "skill_registry.json"),
      JSON.stringify({ version: "1", skills: [] }),
    );

    const result = resolveRoot(subDir);
    expect(result).toEqual({ root: fakeHome, scope: "user" });

    fs.rmSync(fakeHome, { recursive: true, force: true });
  });

  it("defaults to project root when neither scope has registry", () => {
    // Has .git so findProjectRoot finds it, but no registry anywhere
    fs.mkdirSync(path.join(tmpDir, ".git"));
    const result = resolveRoot(tmpDir);
    expect(result).toEqual({ root: tmpDir, scope: "project" });
  });

  it("defaults to cwd when no project root and no registry", () => {
    const result = resolveRoot(tmpDir);
    expect(result).toEqual({ root: tmpDir, scope: "project" });
  });

  it("prefers project over user when both exist", () => {
    const projectSkillsDir = path.join(tmpDir, ".claude", "skills");
    fs.mkdirSync(projectSkillsDir, { recursive: true });
    fs.writeFileSync(
      path.join(projectSkillsDir, "skill_registry.json"),
      JSON.stringify({ version: "1", skills: [] }),
    );

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

describe("findProjectRoot", () => {
  let tmpDir: string;

  beforeEach(() => {
    tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "sf-findroot-"));
  });

  afterEach(() => {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  });

  it("returns dir itself when .git exists", () => {
    fs.mkdirSync(path.join(tmpDir, ".git"));
    expect(findProjectRoot(tmpDir)).toBe(tmpDir);
  });

  it("returns dir itself when .claude exists", () => {
    fs.mkdirSync(path.join(tmpDir, ".claude"));
    expect(findProjectRoot(tmpDir)).toBe(tmpDir);
  });

  it("walks up to find ancestor with .git", () => {
    fs.mkdirSync(path.join(tmpDir, ".git"));
    const subDir = path.join(tmpDir, "src", "deep", "nested");
    fs.mkdirSync(subDir, { recursive: true });
    expect(findProjectRoot(subDir)).toBe(tmpDir);
  });

  it("walks up to find ancestor with .claude", () => {
    fs.mkdirSync(path.join(tmpDir, ".claude"));
    const subDir = path.join(tmpDir, "lib");
    fs.mkdirSync(subDir, { recursive: true });
    expect(findProjectRoot(subDir)).toBe(tmpDir);
  });

  it("returns null when no marker found", () => {
    expect(findProjectRoot(tmpDir)).toBeNull();
  });

  // existsSync returns false on EACCES — unreadable dir is skipped, not thrown
  it.skipIf(process.platform === "win32")(
    "skips unreadable directory and continues up",
    () => {
      // Project root at tmpDir
      fs.mkdirSync(path.join(tmpDir, ".git"));

      // Unreadable intermediate directory
      const locked = path.join(tmpDir, "locked");
      const child = path.join(locked, "deep");
      fs.mkdirSync(child, { recursive: true });
      fs.chmodSync(locked, 0o000);

      try {
        // Should skip locked/, walk up to tmpDir, find .git
        expect(findProjectRoot(child)).toBe(tmpDir);
      } finally {
        fs.chmodSync(locked, 0o755);
      }
    },
  );
});

describe("resolveTargetRoot", () => {
  let tmpDir: string;

  beforeEach(() => {
    tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "sf-target-"));
  });

  afterEach(() => {
    fs.rmSync(tmpDir, { recursive: true, force: true });
    vi.restoreAllMocks();
  });

  it("returns project scope when .git exists", () => {
    fs.mkdirSync(path.join(tmpDir, ".git"));
    expect(resolveTargetRoot(tmpDir)).toEqual({ root: tmpDir, scope: "project" });
  });

  it("returns project scope when .claude exists", () => {
    fs.mkdirSync(path.join(tmpDir, ".claude"));
    expect(resolveTargetRoot(tmpDir)).toEqual({ root: tmpDir, scope: "project" });
  });

  it("falls back to user scope when not a project dir", () => {
    const fakeHome = fs.mkdtempSync(path.join(os.tmpdir(), "sf-home-"));
    vi.stubEnv("HOME", fakeHome);

    const result = resolveTargetRoot(tmpDir);
    expect(result).toEqual({ root: fakeHome, scope: "user" });

    fs.rmSync(fakeHome, { recursive: true, force: true });
  });

  it("walks up to find project root from subdirectory", () => {
    fs.mkdirSync(path.join(tmpDir, ".git"));
    const subDir = path.join(tmpDir, "src", "deep");
    fs.mkdirSync(subDir, { recursive: true });

    const result = resolveTargetRoot(subDir);
    expect(result).toEqual({ root: tmpDir, scope: "project" });
  });

  it("falls back to cwd when not project dir and HOME is null", () => {
    vi.stubEnv("HOME", "");
    vi.stubEnv("USERPROFILE", "");

    const result = resolveTargetRoot(tmpDir);
    expect(result).toEqual({ root: tmpDir, scope: "project" });
  });
});

describe("userHome", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("returns HOME env var", () => {
    vi.stubEnv("HOME", "/fake/home");
    expect(userHome()).toBe("/fake/home");
  });

  it("falls back to USERPROFILE when HOME is unset", () => {
    vi.stubEnv("HOME", "");
    vi.stubEnv("USERPROFILE", "/win/profile");
    expect(userHome()).toBe("/win/profile");
  });

  it("returns null when both are unset", () => {
    vi.stubEnv("HOME", "");
    vi.stubEnv("USERPROFILE", "");
    expect(userHome()).toBeNull();
  });
});

describe("loadRegistry auto-prune", () => {
  let tmpDir: string;

  beforeEach(() => {
    tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "sf-autoprune-"));
  });

  afterEach(() => {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  });

  it("removes orphaned entries and rewrites registry", () => {
    const sd = path.join(tmpDir, ".claude", "skills");
    fs.mkdirSync(path.join(sd, "alive-skill"), { recursive: true });
    fs.writeFileSync(
      path.join(sd, "skill_registry.json"),
      JSON.stringify({
        version: "1",
        skills: [
          { name: "alive-skill", version: "1.0.0" },
          { name: "dead-skill", version: "1.0.0" },
        ],
      }),
    );

    const result = loadRegistry(tmpDir);
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.registry.skills).toHaveLength(1);
    expect(result.registry.skills[0]!.name).toBe("alive-skill");

    // Verify file was rewritten
    const onDisk = JSON.parse(fs.readFileSync(path.join(sd, "skill_registry.json"), "utf-8"));
    expect(onDisk.skills).toHaveLength(1);
  });

  it("does not rewrite when all entries are alive", () => {
    const sd = path.join(tmpDir, ".claude", "skills");
    fs.mkdirSync(path.join(sd, "my-skill"), { recursive: true });
    const regPath = path.join(sd, "skill_registry.json");
    const content = JSON.stringify({ version: "1", skills: [{ name: "my-skill", version: "1.0.0" }] });
    fs.writeFileSync(regPath, content);

    loadRegistry(tmpDir);

    // File unchanged — no unnecessary write
    expect(fs.readFileSync(regPath, "utf-8")).toBe(content);
  });

  it("does not rewrite empty skills array", () => {
    const sd = path.join(tmpDir, ".claude", "skills");
    fs.mkdirSync(sd, { recursive: true });
    const regPath = path.join(sd, "skill_registry.json");
    const content = JSON.stringify({ version: "1", skills: [] });
    fs.writeFileSync(regPath, content);

    loadRegistry(tmpDir);

    expect(fs.readFileSync(regPath, "utf-8")).toBe(content);
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

describe("embedCommandName", () => {
  it("prefixes source filename with plugin name", () => {
    for (const file of EMBED_COMMANDS) {
      expect(embedCommandName(file)).toBe(`${PLUGIN_NAME}:${file}`);
    }
  });
});
