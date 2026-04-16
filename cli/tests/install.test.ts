vi.mock("../src/commands/embed.js", () => ({
  embedInstall: vi.fn(),
}));

vi.mock("node:child_process", () => ({
  execSync: vi.fn(),
}));

vi.mock("node:readline", () => ({
  createInterface: vi.fn(),
}));

import { describe, it, expect, vi, beforeEach } from "vitest";
import { parseScope, promptScope } from "../src/commands/install.js";
import { createInterface } from "node:readline";
import { embedInstall } from "../src/commands/embed.js";

const mockEmbedInstall = vi.mocked(embedInstall);

// ── parseScope ──────────────────────────────────────────────────────────

describe("parseScope", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("returns undefined when no --scope flag", () => {
    expect(parseScope([])).toBeUndefined();
    expect(parseScope(["--other"])).toBeUndefined();
  });

  it("returns undefined when --scope has no value", () => {
    expect(parseScope(["--scope"])).toBeUndefined();
  });

  it("parses valid scopes", () => {
    expect(parseScope(["--scope", "project"])).toBe("project");
    expect(parseScope(["--scope", "user"])).toBe("user");
  });

  it("exits on invalid scope", () => {
    const exitSpy = vi.spyOn(process, "exit").mockImplementation(() => {
      throw new Error("exit");
    });
    expect(() => parseScope(["--scope", "bad"])).toThrow("exit");
    expect(exitSpy).toHaveBeenCalledWith(1);
  });
});

// ── promptScope ─────────────────────────────────────────────────────────

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

describe("promptScope", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("defaults to project on empty input", async () => {
    mockReadline("");
    expect(await promptScope()).toBe("project");
  });

  it("selects project by number", async () => {
    mockReadline("1");
    expect(await promptScope()).toBe("project");
  });

  it("selects user by number", async () => {
    mockReadline("2");
    expect(await promptScope()).toBe("user");
  });

  it("selects project by name", async () => {
    mockReadline("project");
    expect(await promptScope()).toBe("project");
  });

  it("selects user by name", async () => {
    mockReadline("user");
    expect(await promptScope()).toBe("user");
  });

  it("exits on invalid input", async () => {
    mockReadline("bad");
    const exitSpy = vi.spyOn(process, "exit").mockImplementation(() => {
      throw new Error("exit");
    });
    await expect(promptScope()).rejects.toThrow("exit");
    expect(exitSpy).toHaveBeenCalledWith(1);
  });
});

// ── install run ─────────────────────────────────────────────────────────

describe("install run", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.clearAllMocks();
  });

  it("calls embedInstall for project scope", async () => {
    mockEmbedInstall.mockReturnValue("0.5.0");
    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    // Dynamic import to get the run function with mocks active
    const { run } = await import("../src/commands/install.js");
    await run(["--scope", "project"]);

    expect(mockEmbedInstall).toHaveBeenCalled();
    expect(logSpy).toHaveBeenCalledWith(expect.stringContaining("Embedded skill-forge 0.5.0"));
    logSpy.mockRestore();
  });
});
