vi.mock("node:readline", () => ({
  createInterface: vi.fn(),
}));

import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import { createInterface } from "node:readline";
import {
  parseForce,
  parseNames,
  promptConfirm,
  removeSkills,
  run,
} from "../src/commands/rm.js";

// ── parseForce ─────────────────────────────────────────────────────────

describe("parseForce", () => {
  it("returns false when no flag", () => {
    expect(parseForce(["foo"])).toBe(false);
    expect(parseForce([])).toBe(false);
  });

  it("returns true when --force present", () => {
    expect(parseForce(["--force"])).toBe(true);
    expect(parseForce(["foo", "--force", "bar"])).toBe(true);
  });
});

// ── parseNames ─────────────────────────────────────────────────────────

describe("parseNames", () => {
  it("strips flag tokens", () => {
    expect(parseNames(["foo", "--force", "bar"])).toEqual(["foo", "bar"]);
  });

  it("returns all when no flags", () => {
    expect(parseNames(["a", "b"])).toEqual(["a", "b"]);
  });

  it("returns empty for flags only", () => {
    expect(parseNames(["--force"])).toEqual([]);
  });

  it("deduplicates names", () => {
    expect(parseNames(["foo", "foo", "bar"])).toEqual(["foo", "bar"]);
  });
});

// ── promptConfirm ──────────────────────────────────────────────────────

function mockReadline(answer: string) {
  const closeFn = vi.fn();
  const questionFn = vi.fn((_prompt: string, cb: (a: string) => void) => {
    cb(answer);
  });
  vi.mocked(createInterface).mockReturnValue({
    question: questionFn,
    close: closeFn,
  } as unknown as ReturnType<typeof createInterface>);
}

describe("promptConfirm", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("returns true on 'y'", async () => {
    mockReadline("y");
    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    expect(await promptConfirm(["foo"])).toBe(true);
    logSpy.mockRestore();
  });

  it("returns true on 'Y'", async () => {
    mockReadline("Y");
    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    expect(await promptConfirm(["foo"])).toBe(true);
    logSpy.mockRestore();
  });

  it("returns false on empty input", async () => {
    mockReadline("");
    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    expect(await promptConfirm(["foo"])).toBe(false);
    logSpy.mockRestore();
  });

  it("returns false on 'n'", async () => {
    mockReadline("n");
    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    expect(await promptConfirm(["foo"])).toBe(false);
    logSpy.mockRestore();
  });

  it("prints names in prompt message", async () => {
    mockReadline("n");
    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    await promptConfirm(["alpha", "beta"]);
    expect(logSpy).toHaveBeenCalledWith(
      expect.stringContaining("alpha, beta"),
    );
    logSpy.mockRestore();
  });
});

// ── removeSkills ───────────────────────────────────────────────────────

describe("removeSkills", () => {
  let tmpDir: string;

  beforeEach(() => {
    tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "sf-rm-"));
  });

  afterEach(() => {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  });

  it("deletes directories and filters registry", () => {
    const skills = path.join(tmpDir, ".claude", "skills");
    fs.mkdirSync(path.join(skills, "foo"), { recursive: true });
    fs.mkdirSync(path.join(skills, "bar"), { recursive: true });
    fs.mkdirSync(path.join(skills, "keep"), { recursive: true });

    const registry = {
      version: "1",
      skills: [
        { name: "foo", version: "1.0.0", scope: "project", created: "2026-01-01", updated: "2026-01-01", auto_trigger: true, description_chars: 100, eval_score: 6, trigger_score: null, usage_count: 0 },
        { name: "bar", version: "1.0.0", scope: "project", created: "2026-01-01", updated: "2026-01-01", auto_trigger: true, description_chars: 80, eval_score: 5, trigger_score: null, usage_count: 0 },
        { name: "keep", version: "1.0.0", scope: "project", created: "2026-01-01", updated: "2026-01-01", auto_trigger: true, description_chars: 90, eval_score: 7, trigger_score: null, usage_count: 0 },
      ],
    };

    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    removeSkills(tmpDir, registry, ["foo", "bar"]);
    logSpy.mockRestore();

    expect(fs.existsSync(path.join(skills, "foo"))).toBe(false);
    expect(fs.existsSync(path.join(skills, "bar"))).toBe(false);
    expect(fs.existsSync(path.join(skills, "keep"))).toBe(true);
    expect(registry.skills).toHaveLength(1);
    expect(registry.skills[0]!.name).toBe("keep");

    // Registry file written
    const saved = JSON.parse(
      fs.readFileSync(path.join(skills, "skill_registry.json"), "utf-8"),
    );
    expect(saved.skills).toHaveLength(1);
  });
});

// ── run (integration) ──────────────────────────────────────────────────

describe("rm run", () => {
  let tmpDir: string;

  beforeEach(() => {
    tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "sf-rm-run-"));
    vi.restoreAllMocks();
  });

  afterEach(() => {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  });

  function setupRegistry(
    skills: Array<{ name: string }>,
  ) {
    const dir = path.join(tmpDir, ".claude", "skills");
    for (const s of skills) {
      fs.mkdirSync(path.join(dir, s.name), { recursive: true });
    }
    fs.writeFileSync(
      path.join(dir, "skill_registry.json"),
      JSON.stringify({
        version: "1",
        skills: skills.map((s) => ({
          name: s.name,
          version: "1.0.0",
          scope: "project",
          created: "2026-01-01",
          updated: "2026-01-01",
          auto_trigger: true,
          description_chars: 100,
          eval_score: 6,
          trigger_score: null,
          usage_count: 0,
        })),
      }),
    );
  }

  it("exits with usage error when no names provided", async () => {
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const exitSpy = vi.spyOn(process, "exit").mockImplementation(() => {
      throw new Error("exit");
    });
    await expect(run(tmpDir, [])).rejects.toThrow("exit");
    expect(exitSpy).toHaveBeenCalledWith(1);
    expect(errorSpy).toHaveBeenCalledWith(expect.stringContaining("Usage"));
    errorSpy.mockRestore();
    exitSpy.mockRestore();
  });

  it("exits when no registry exists", async () => {
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const exitSpy = vi.spyOn(process, "exit").mockImplementation(() => {
      throw new Error("exit");
    });
    await expect(run(tmpDir, ["foo", "--force"])).rejects.toThrow("exit");
    expect(errorSpy).toHaveBeenCalledWith(
      expect.stringContaining("No skill registry found"),
    );
    errorSpy.mockRestore();
    exitSpy.mockRestore();
  });

  it("exits when skill not found", async () => {
    setupRegistry([{ name: "real" }]);
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const exitSpy = vi.spyOn(process, "exit").mockImplementation(() => {
      throw new Error("exit");
    });
    await expect(run(tmpDir, ["ghost", "--force"])).rejects.toThrow("exit");
    expect(errorSpy).toHaveBeenCalledWith(
      expect.stringContaining("Skill not found: ghost"),
    );
    errorSpy.mockRestore();
    exitSpy.mockRestore();
  });

  it("removes skill with --force (no prompt)", async () => {
    setupRegistry([{ name: "target" }, { name: "keep" }]);
    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    await run(tmpDir, ["target", "--force"]);

    const dir = path.join(tmpDir, ".claude", "skills");
    expect(fs.existsSync(path.join(dir, "target"))).toBe(false);
    expect(fs.existsSync(path.join(dir, "keep"))).toBe(true);

    const saved = JSON.parse(
      fs.readFileSync(path.join(dir, "skill_registry.json"), "utf-8"),
    );
    expect(saved.skills).toHaveLength(1);
    expect(saved.skills[0].name).toBe("keep");
    logSpy.mockRestore();
  });

  it("removes multiple skills with --force", async () => {
    setupRegistry([{ name: "a" }, { name: "b" }, { name: "c" }]);
    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    await run(tmpDir, ["a", "b", "--force"]);

    const dir = path.join(tmpDir, ".claude", "skills");
    expect(fs.existsSync(path.join(dir, "a"))).toBe(false);
    expect(fs.existsSync(path.join(dir, "b"))).toBe(false);
    expect(fs.existsSync(path.join(dir, "c"))).toBe(true);
    logSpy.mockRestore();
  });

  it("deletes found skills and exits 1 when some not found", async () => {
    setupRegistry([{ name: "real" }]);
    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const exitSpy = vi.spyOn(process, "exit").mockImplementation(() => {
      throw new Error("exit");
    });

    await expect(run(tmpDir, ["real", "ghost", "--force"])).rejects.toThrow(
      "exit",
    );

    // real was deleted
    const dir = path.join(tmpDir, ".claude", "skills");
    expect(fs.existsSync(path.join(dir, "real"))).toBe(false);
    expect(errorSpy).toHaveBeenCalledWith(
      expect.stringContaining("Skill not found: ghost"),
    );
    logSpy.mockRestore();
    errorSpy.mockRestore();
    exitSpy.mockRestore();
  });

  it("aborts on interactive 'n'", async () => {
    setupRegistry([{ name: "target" }]);
    mockReadline("n");
    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    await run(tmpDir, ["target"]);

    // Not deleted
    const dir = path.join(tmpDir, ".claude", "skills");
    expect(fs.existsSync(path.join(dir, "target"))).toBe(true);
    expect(logSpy).toHaveBeenCalledWith("Aborted.");
    logSpy.mockRestore();
  });

  it("deletes on interactive 'y'", async () => {
    setupRegistry([{ name: "target" }]);
    mockReadline("y");
    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    await run(tmpDir, ["target"]);

    const dir = path.join(tmpDir, ".claude", "skills");
    expect(fs.existsSync(path.join(dir, "target"))).toBe(false);
    logSpy.mockRestore();
  });
});
