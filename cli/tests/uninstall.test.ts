import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("node:child_process", () => ({
  execSync: vi.fn(),
}));

vi.mock("../src/commands/embed.js", () => ({
  detectEmbedInstall: vi.fn(),
  removeEmbedFiles: vi.fn(),
}));

import { execSync } from "node:child_process";
import { detectEmbedInstall, removeEmbedFiles } from "../src/commands/embed.js";
import { run } from "../src/commands/uninstall.js";

const mockExecSync = vi.mocked(execSync);
const mockDetect = vi.mocked(detectEmbedInstall);
const mockRemove = vi.mocked(removeEmbedFiles);

describe("uninstall command", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("removes embed files when embed install detected", () => {
    mockDetect.mockReturnValue(true);
    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    run(process.cwd());

    expect(mockRemove).toHaveBeenCalled();
    expect(mockExecSync).not.toHaveBeenCalled();
    logSpy.mockRestore();
  });

  it("runs claude plugin uninstall when no embed install", () => {
    mockDetect.mockReturnValue(false);
    mockExecSync.mockReturnValue("");
    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    run(process.cwd());

    expect(mockExecSync).toHaveBeenCalledWith(
      "claude plugin uninstall skill-forge",
      expect.objectContaining({ stdio: "inherit" }),
    );
    expect(mockRemove).not.toHaveBeenCalled();
    logSpy.mockRestore();
  });

  it("exits with friendly message on plugin uninstall failure", () => {
    mockDetect.mockReturnValue(false);
    mockExecSync.mockImplementation(() => {
      throw new Error("command failed");
    });

    const exitSpy = vi.spyOn(process, "exit").mockImplementation(() => {
      throw new Error("process.exit");
    });
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    expect(() => run(process.cwd())).toThrow("process.exit");
    expect(errorSpy).toHaveBeenCalledWith(
      expect.stringContaining("Failed"),
    );

    exitSpy.mockRestore();
    errorSpy.mockRestore();
  });
});
