#!/usr/bin/env node

// Entry point for skill-forge CLI.
// Routes argv to command handlers. No framework — commands are few, args are positional.

import { createRequire } from "node:module";
import { run as initRun } from "./commands/init.js";
import { run as installRun } from "./commands/install.js";
import { run as uninstallRun } from "./commands/uninstall.js";
import { run as listRun } from "./commands/list.js";
import { clean as registryClean } from "./commands/registry.js";
import { runDoctor, formatResults } from "./commands/doctor.js";
import { run as upgradeRun } from "./commands/upgrade.js";

// Single source of truth — reads version from package.json
const require = createRequire(import.meta.url);
const VERSION: string = (require("../package.json") as { version: string }).version;

const KNOWN_COMMANDS = new Set([
  "install",
  "uninstall",
  "list",
  "registry",
  "doctor",
  "init",
  "upgrade",
]);

interface ParsedCommand {
  command: string;
  args: string[];
}

export function parseCommand(argv: string[]): ParsedCommand {
  const raw = argv.slice(2);

  if (raw.length === 0) return { command: "help", args: [] };

  const first = raw[0]!;
  if (first === "--help" || first === "-h") return { command: "help", args: [] };
  if (first === "--version" || first === "-v")
    return { command: "version", args: [] };

  if (KNOWN_COMMANDS.has(first)) {
    return { command: first, args: raw.slice(1) };
  }

  return { command: "unknown", args: [first] };
}

function printHelp(): void {
  console.log(`skill-forge v${VERSION}

Usage: skill-forge <command>

Commands:
  install          Install skill-forge plugin via claude CLI
  uninstall        Uninstall skill-forge plugin
  list             Print skill registry for current project
  registry clean   Remove orphaned registry entries
  doctor           Diagnose environment health
  init             Initialize .claude/skills/ in current project
  upgrade          Upgrade CLI to latest version

Options:
  --help, -h       Show this help
  --version, -v    Show version`);
}

function main(): void {
  const { command, args } = parseCommand(process.argv);
  const cwd = process.cwd();

  switch (command) {
    case "help":
      printHelp();
      break;

    case "version":
      console.log(VERSION);
      break;

    case "install":
      installRun();
      break;

    case "uninstall":
      uninstallRun();
      break;

    case "list":
      console.log(listRun(cwd));
      break;

    case "registry": {
      const sub = args[0];
      if (sub !== "clean") {
        console.error(
          `Unknown registry subcommand: ${sub ?? "(none)"}. Available: clean`,
        );
        process.exit(1);
      }
      const result = registryClean(cwd);
      if ("error" in result) {
        console.error(result.error);
        process.exit(1);
      }
      if (result.removed.length === 0) {
        console.log("Registry is clean. No orphaned entries.");
      } else {
        console.log(
          `Removed ${result.removed.length} stale entries: ${result.removed.join(", ")}`,
        );
      }
      break;
    }

    case "doctor": {
      const results = runDoctor(cwd);
      console.log(formatResults(results));
      if (results.some((r) => r.status === "fail")) process.exit(1);
      break;
    }

    case "init":
      initRun(cwd);
      console.log("Initialized .claude/skills/ with empty registry.");
      break;

    case "upgrade":
      upgradeRun();
      break;

    default:
      console.error(`Unknown command: ${args[0]}. Run skill-forge --help.`);
      process.exit(1);
  }
}

main();
