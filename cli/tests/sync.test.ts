import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("node:child_process", () => ({
  execSync: vi.fn(),
}));

vi.mock("../src/commands/embed.js", () => ({
  detectEmbedInstall: vi.fn(),
  readVersionFile: vi.fn(),
  embedInstall: vi.fn(),
}));

import { execSync } from "node:child_process";
import { detectEmbedInstall, readVersionFile, embedInstall } from "../src/commands/embed.js";
import { run } from "../src/commands/sync.js";

const mockExecSync = vi.mocked(execSync);
const mockDetect = vi.mocked(detectEmbedInstall);
const mockReadVersion = vi.mocked(readVersionFile);
const mockEmbedInstall = vi.mocked(embedInstall);

describe("sync command", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("exits with message when no embed install detected", () => {
    mockDetect.mockReturnValue(false);

    const exitSpy = vi.spyOn(process, "exit").mockImplementation(() => {
      throw new Error("process.exit");
    });
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    expect(() => run(process.cwd())).toThrow("process.exit");
    expect(errorSpy).toHaveBeenCalledWith(
      expect.stringContaining("No embedded install found"),
    );

    exitSpy.mockRestore();
    errorSpy.mockRestore();
  });

  it("reports up to date when versions match", () => {
    mockDetect.mockReturnValue(true);
    mockReadVersion.mockReturnValue({ version: "0.5.0", installed: "2026-04-15T00:00:00Z" });
    mockExecSync.mockReturnValue("v0.5.0" as any);

    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    run(process.cwd());

    expect(logSpy).toHaveBeenCalledWith(expect.stringContaining("up to date"));
    logSpy.mockRestore();
  });

  it("exits on gh api failure", () => {
    mockDetect.mockReturnValue(true);
    mockReadVersion.mockReturnValue({ version: "0.4.0", installed: "2026-04-15T00:00:00Z" });
    mockExecSync.mockImplementation(() => {
      throw new Error("network error");
    });

    const exitSpy = vi.spyOn(process, "exit").mockImplementation(() => {
      throw new Error("process.exit");
    });
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    expect(() => run(process.cwd())).toThrow("process.exit");
    expect(errorSpy).toHaveBeenCalledWith(
      expect.stringContaining("Failed to check latest release"),
    );

    exitSpy.mockRestore();
    errorSpy.mockRestore();
  });

  it("calls embedInstall when newer version available", () => {
    mockDetect.mockReturnValue(true);
    mockReadVersion.mockReturnValue({ version: "0.4.0", installed: "2026-04-15T00:00:00Z" });
    mockExecSync.mockReturnValue("v0.5.0" as any);
    mockEmbedInstall.mockReturnValue("0.5.0");

    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    run(process.cwd());

    expect(mockEmbedInstall).toHaveBeenCalledWith(expect.any(String), "v0.5.0");
    logSpy.mockRestore();
  });
});
