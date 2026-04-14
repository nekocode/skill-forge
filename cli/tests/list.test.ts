import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import { run, formatTable } from "../src/commands/list.js";

describe("list command", () => {
  let tmpDir: string;

  beforeEach(() => {
    tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "sf-list-"));
  });

  afterEach(() => {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  });

  it("writes error to stderr when no registry exists", () => {
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const output = run(tmpDir);
    expect(output).toBe("");
    expect(errorSpy).toHaveBeenCalledWith(
      expect.stringContaining("No skill registry found"),
    );
    errorSpy.mockRestore();
  });

  it("prints empty message when registry has no skills", () => {
    const skillsDir = path.join(tmpDir, ".claude", "skills");
    fs.mkdirSync(skillsDir, { recursive: true });
    fs.writeFileSync(
      path.join(skillsDir, "skill_registry.json"),
      JSON.stringify({ version: "1", skills: [] }),
    );

    const output = run(tmpDir);
    expect(output).toContain("No skills registered");
  });

  it("writes error to stderr for corrupted JSON", () => {
    const skillsDir = path.join(tmpDir, ".claude", "skills");
    fs.mkdirSync(skillsDir, { recursive: true });
    fs.writeFileSync(
      path.join(skillsDir, "skill_registry.json"),
      "not valid json",
    );

    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const output = run(tmpDir);
    expect(output).toBe("");
    expect(errorSpy).toHaveBeenCalledWith(
      expect.stringContaining("Failed to parse"),
    );
    errorSpy.mockRestore();
  });

  it("writes error to stderr for malformed registry without skills array", () => {
    const skillsDir = path.join(tmpDir, ".claude", "skills");
    fs.mkdirSync(skillsDir, { recursive: true });
    fs.writeFileSync(
      path.join(skillsDir, "skill_registry.json"),
      JSON.stringify({ version: "1" }),
    );

    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const output = run(tmpDir);
    expect(output).toBe("");
    expect(errorSpy).toHaveBeenCalledWith(
      expect.stringContaining("Malformed"),
    );
    errorSpy.mockRestore();
  });

  it("prints formatted table for skills", () => {
    const skillsDir = path.join(tmpDir, ".claude", "skills");
    fs.mkdirSync(skillsDir, { recursive: true });
    fs.writeFileSync(
      path.join(skillsDir, "skill_registry.json"),
      JSON.stringify({
        version: "1",
        skills: [
          {
            name: "generate-endpoint",
            version: "1.2.0",
            scope: "project",
            created: "2026-04-01",
            updated: "2026-04-08",
            auto_trigger: true,
            description_chars: 187,
            eval_score: 7,
            trigger_score: 89,
            usage_count: 3,
          },
          {
            name: "seed-database",
            version: "1.0.1",
            scope: "project",
            created: "2026-03-21",
            updated: "2026-03-21",
            auto_trigger: false,
            description_chars: 120,
            eval_score: 6,
            trigger_score: null,
            usage_count: 0,
          },
        ],
      }),
    );

    const output = run(tmpDir);
    expect(output).toContain("[project]");
    expect(output).toContain("generate-endpoint");
    expect(output).toContain("1.2.0");
    expect(output).toContain("89%");
    expect(output).toContain("seed-database");
    expect(output).toContain("1.0.1");
    // null trigger_score renders as em-dash
    expect(output).toContain("\u2014");
  });
});

describe("formatTable", () => {
  it("aligns columns with dynamic widths", () => {
    const headers = ["Name", "Ver"];
    const rows = [
      ["short", "1.0"],
      ["much-longer-name", "2.0"],
    ];
    const output = formatTable(headers, rows);
    const lines = output.split("\n");

    // header and all rows should have same visual width
    const headerLen = lines[0]!.length;
    const separatorLen = lines[1]!.length;
    const row1Len = lines[2]!.length;
    const row2Len = lines[3]!.length;

    expect(headerLen).toBe(separatorLen);
    expect(headerLen).toBe(row1Len);
    expect(headerLen).toBe(row2Len);
  });

  it("returns empty string for empty rows", () => {
    expect(formatTable(["Name"], [])).toBe("");
  });
});
