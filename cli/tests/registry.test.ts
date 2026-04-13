import { describe, it, expect, beforeEach, afterEach } from "vitest";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import { clean } from "../src/commands/registry.js";

describe("registry clean", () => {
  let tmpDir: string;

  beforeEach(() => {
    tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "sf-reg-"));
  });

  afterEach(() => {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  });

  it("returns error when no registry exists", () => {
    const result = clean(tmpDir);
    expect(result.error).toContain("No skill registry found");
  });

  it("returns error when registry JSON is corrupted", () => {
    const skillsDir = path.join(tmpDir, ".claude", "skills");
    fs.mkdirSync(skillsDir, { recursive: true });
    fs.writeFileSync(
      path.join(skillsDir, "skill_registry.json"),
      "not valid json",
    );

    const result = clean(tmpDir);
    expect(result.error).toContain("Failed to parse");
  });

  it("returns error when registry has no skills array", () => {
    const skillsDir = path.join(tmpDir, ".claude", "skills");
    fs.mkdirSync(skillsDir, { recursive: true });
    fs.writeFileSync(
      path.join(skillsDir, "skill_registry.json"),
      JSON.stringify({ version: "1" }),
    );

    const result = clean(tmpDir);
    expect(result.error).toContain("Malformed");
  });

  it("removes entries whose skill directories are missing", () => {
    const skillsDir = path.join(tmpDir, ".claude", "skills");
    // Only create dir for one of two registered skills
    fs.mkdirSync(path.join(skillsDir, "alive-skill"), { recursive: true });
    fs.writeFileSync(
      path.join(skillsDir, "alive-skill", "SKILL.md"),
      "---\nname: alive-skill\n---",
    );

    fs.writeFileSync(
      path.join(skillsDir, "skill_registry.json"),
      JSON.stringify({
        version: "1",
        skills: [
          { name: "alive-skill", version: "1.0.0" },
          { name: "dead-skill", version: "1.0.0" },
        ],
      }),
    );

    const result = clean(tmpDir);
    expect(result.removed).toEqual(["dead-skill"]);
    expect(result.kept).toEqual(["alive-skill"]);

    // Verify registry was actually rewritten
    const registry = JSON.parse(
      fs.readFileSync(path.join(skillsDir, "skill_registry.json"), "utf-8"),
    );
    expect(registry.skills).toHaveLength(1);
    expect(registry.skills[0].name).toBe("alive-skill");
  });

  it("reports nothing removed when all skills have directories", () => {
    const skillsDir = path.join(tmpDir, ".claude", "skills");
    fs.mkdirSync(path.join(skillsDir, "my-skill"), { recursive: true });
    fs.writeFileSync(
      path.join(skillsDir, "skill_registry.json"),
      JSON.stringify({
        version: "1",
        skills: [{ name: "my-skill", version: "1.0.0" }],
      }),
    );

    const result = clean(tmpDir);
    expect(result.removed).toEqual([]);
    expect(result.kept).toEqual(["my-skill"]);
  });

  it("handles empty skills array without writing", () => {
    const skillsDir = path.join(tmpDir, ".claude", "skills");
    fs.mkdirSync(skillsDir, { recursive: true });
    const regPath = path.join(skillsDir, "skill_registry.json");
    const content = JSON.stringify({ version: "1", skills: [] });
    fs.writeFileSync(regPath, content);

    const result = clean(tmpDir);
    expect(result.removed).toEqual([]);
    expect(result.kept).toEqual([]);

    // File unchanged — no unnecessary write
    expect(fs.readFileSync(regPath, "utf-8")).toBe(content);
  });
});
