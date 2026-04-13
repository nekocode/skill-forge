import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("node:child_process", () => ({
  execSync: vi.fn(),
}));

import { execSync } from "node:child_process";
import { run } from "../src/commands/upgrade.js";

const mockExecSync = vi.mocked(execSync);

describe("upgrade command", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("runs npm update -g skill-forge", () => {
    mockExecSync.mockReturnValue("");

    run();

    expect(mockExecSync).toHaveBeenCalledWith(
      "npm update -g skill-forge",
      expect.objectContaining({ stdio: "inherit" }),
    );
  });

  it("exits with friendly message on failure", () => {
    mockExecSync.mockImplementation(() => {
      throw new Error("npm error");
    });

    const exitSpy = vi.spyOn(process, "exit").mockImplementation(() => {
      throw new Error("process.exit");
    });
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    expect(() => run()).toThrow("process.exit");
    expect(errorSpy).toHaveBeenCalledWith(
      expect.stringContaining("Failed"),
    );

    exitSpy.mockRestore();
    errorSpy.mockRestore();
  });
});
