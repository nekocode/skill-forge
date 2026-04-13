import { describe, it, expect } from "vitest";
import { parseCommand } from "../src/main.js";

describe("parseCommand", () => {
  it("parses top-level command", () => {
    const result = parseCommand(["node", "skill-forge", "list"]);
    expect(result).toEqual({ command: "list", args: [] });
  });

  it("parses command with subcommand", () => {
    const result = parseCommand(["node", "skill-forge", "registry", "clean"]);
    expect(result).toEqual({ command: "registry", args: ["clean"] });
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

  it("parses upgrade command", () => {
    const result = parseCommand(["node", "skill-forge", "upgrade"]);
    expect(result).toEqual({ command: "upgrade", args: [] });
  });

  it("returns unknown for unrecognized command", () => {
    const result = parseCommand(["node", "skill-forge", "foobar"]);
    expect(result).toEqual({ command: "unknown", args: ["foobar"] });
  });
});
