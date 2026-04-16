import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("node:child_process", () => ({
  execSync: vi.fn(),
}));

vi.mock("../src/commands/embed.js", () => ({
  detectEmbedInstall: vi.fn(),
  removeEmbedFiles: vi.fn(),
}));

vi.mock("../src/types.js", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/types.js")>();
  return {
    ...actual,
    resolveRoot: vi.fn(),
  };
});

import { execSync } from "node:child_process";
import { detectEmbedInstall, removeEmbedFiles } from "../src/commands/embed.js";
import { resolveRoot } from "../src/types.js";
import { run } from "../src/commands/uninstall.js";

const mockExecSync = vi.mocked(execSync);
const mockDetect = vi.mocked(detectEmbedInstall);
const mockRemove = vi.mocked(removeEmbedFiles);
const mockResolveRoot = vi.mocked(resolveRoot);

describe("uninstall command", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("removes embed files at resolved project root", () => {
    mockResolveRoot.mockReturnValue({ root: "/proj", scope: "project" });
    mockDetect.mockReturnValue(true);
    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    run("/proj");

    expect(mockResolveRoot).toHaveBeenCalledWith("/proj");
    expect(mockDetect).toHaveBeenCalledWith("/proj");
    expect(mockRemove).toHaveBeenCalledWith("/proj");
    expect(mockExecSync).not.toHaveBeenCalled();
    logSpy.mockRestore();
  });

  it("removes embed files at resolved user root when not in project dir", () => {
    mockResolveRoot.mockReturnValue({ root: "/home/user", scope: "user" });
    mockDetect.mockReturnValue(true);
    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    run("/tmp/random");

    expect(mockResolveRoot).toHaveBeenCalledWith("/tmp/random");
    expect(mockDetect).toHaveBeenCalledWith("/home/user");
    expect(mockRemove).toHaveBeenCalledWith("/home/user");
    logSpy.mockRestore();
  });

  it("runs claude plugin uninstall when no embed install at resolved root", () => {
    mockResolveRoot.mockReturnValue({ root: "/proj", scope: "project" });
    mockDetect.mockReturnValue(false);
    mockExecSync.mockReturnValue("");
    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    run("/proj");

    expect(mockExecSync).toHaveBeenCalledWith(
      "claude plugin uninstall skill-forge",
      expect.objectContaining({ stdio: "inherit" }),
    );
    expect(mockRemove).not.toHaveBeenCalled();
    logSpy.mockRestore();
  });

  it("exits with friendly message on plugin uninstall failure", () => {
    mockResolveRoot.mockReturnValue({ root: "/proj", scope: "project" });
    mockDetect.mockReturnValue(false);
    mockExecSync.mockImplementation(() => {
      throw new Error("command failed");
    });

    const exitSpy = vi.spyOn(process, "exit").mockImplementation(() => {
      throw new Error("process.exit");
    });
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    expect(() => run("/proj")).toThrow("process.exit");
    expect(errorSpy).toHaveBeenCalledWith(
      expect.stringContaining("Failed"),
    );

    exitSpy.mockRestore();
    errorSpy.mockRestore();
  });

  it("shows scope tag in embed removal log", () => {
    mockResolveRoot.mockReturnValue({ root: "/home/user", scope: "user" });
    mockDetect.mockReturnValue(true);
    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    run("/tmp/random");

    expect(logSpy).toHaveBeenCalledWith(
      expect.stringContaining("[user]"),
    );
    logSpy.mockRestore();
  });
});
