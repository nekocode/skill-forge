import { createRequire } from "node:module";
import { describe, it, expect, vi } from "vitest";
import { parseCommand, PLUGIN_VERSION, printVersion } from "../src/main.js";

const require = createRequire(import.meta.url);

describe("parseCommand", () => {
  it("parses top-level command", () => {
    const result = parseCommand(["node", "skill-forge", "list"]);
    expect(result).toEqual({ command: "list", args: [] });
  });

  it("returns help for no arguments", () => {
    const result = parseCommand(["node", "skill-forge"]);
    expect(result).toEqual({ command: "help", args: [] });
  });

  it("returns help for --help flag", () => {
    const result = parseCommand(["node", "skill-forge", "--help"]);
    expect(result).toEqual({ command: "help", args: [] });
  });

  it("returns help for -h short flag", () => {
    const result = parseCommand(["node", "skill-forge", "-h"]);
    expect(result).toEqual({ command: "help", args: [] });
  });

  it("returns version for --version flag", () => {
    const result = parseCommand(["node", "skill-forge", "--version"]);
    expect(result).toEqual({ command: "version", args: [] });
  });

  it("returns version for -v short flag", () => {
    const result = parseCommand(["node", "skill-forge", "-v"]);
    expect(result).toEqual({ command: "version", args: [] });
  });

  it("parses rm command with args", () => {
    const result = parseCommand(["node", "skill-forge", "rm", "foo", "--force"]);
    expect(result).toEqual({ command: "rm", args: ["foo", "--force"] });
  });

  it("parses sync command", () => {
    const result = parseCommand(["node", "skill-forge", "sync"]);
    expect(result).toEqual({ command: "sync", args: [] });
  });

  it("parses upgrade command", () => {
    const result = parseCommand(["node", "skill-forge", "upgrade"]);
    expect(result).toEqual({ command: "upgrade", args: [] });
  });

  it("returns unknown for unrecognized command", () => {
    const result = parseCommand(["node", "skill-forge", "foobar"]);
    expect(result).toEqual({ command: "unknown", args: ["foobar"] });
  });
});

describe("PLUGIN_VERSION", () => {
  it("is a valid semver string", () => {
    expect(PLUGIN_VERSION).toMatch(/^\d+\.\d+\.\d+/);
  });

  it("matches .claude-plugin/plugin.json", () => {
    const pluginJson = require("../../.claude-plugin/plugin.json") as { version: string };
    expect(PLUGIN_VERSION).toBe(pluginJson.version);
  });
});

describe("printVersion", () => {
  it("prints cli and plugin versions on separate labeled lines", () => {
    const cliVersion = (require("../package.json") as { version: string }).version;

    const logs: string[] = [];
    const spy = vi.spyOn(console, "log").mockImplementation((...args: unknown[]) => {
      logs.push(String(args[0]));
    });

    printVersion();

    expect(logs).toEqual([
      `cli:    ${cliVersion}`,
      `plugin: ${PLUGIN_VERSION}`,
    ]);

    spy.mockRestore();
  });
});
