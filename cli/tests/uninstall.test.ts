import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("node:child_process", () => ({
  execSync: vi.fn(),
}));

import { execSync } from "node:child_process";
import { run } from "../src/commands/uninstall.js";

const mockExecSync = vi.mocked(execSync);

describe("uninstall command", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("runs claude plugin uninstall skill-forge", () => {
    mockExecSync.mockReturnValue("");

    run();

    expect(mockExecSync).toHaveBeenCalledWith(
      "claude plugin uninstall skill-forge",
      expect.objectContaining({ stdio: "inherit" }),
    );
  });

  it("exits with friendly message on failure", () => {
    mockExecSync.mockImplementation(() => {
      throw new Error("command failed");
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
