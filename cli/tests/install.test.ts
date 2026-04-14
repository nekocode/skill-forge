import { describe, it, expect, vi, beforeEach } from "vitest";
import { parseScope, promptScope } from "../src/commands/install.js";
import { createInterface } from "node:readline";

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
    expect(parseScope(["--scope", "user"])).toBe("user");
    expect(parseScope(["--scope", "project"])).toBe("project");
    expect(parseScope(["--scope", "local"])).toBe("local");
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

vi.mock("node:readline", () => ({
  createInterface: vi.fn(),
}));

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

  it("selects user by number", async () => {
    mockReadline("1");
    expect(await promptScope()).toBe("user");
  });

  it("selects project by number", async () => {
    mockReadline("2");
    expect(await promptScope()).toBe("project");
  });

  it("selects local by number", async () => {
    mockReadline("3");
    expect(await promptScope()).toBe("local");
  });

  it("selects by name", async () => {
    mockReadline("user");
    expect(await promptScope()).toBe("user");
  });

  it("selects project by name", async () => {
    mockReadline("project");
    expect(await promptScope()).toBe("project");
  });

  it("selects local by name", async () => {
    mockReadline("local");
    expect(await promptScope()).toBe("local");
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
