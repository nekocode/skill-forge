#!/usr/bin/env node

// Entry point for skill-forge CLI.
// Routes argv to command handlers. No framework — commands are few, args are positional.

import { createRequire } from "node:module";
import { run as initRun } from "./commands/init.js";
import { run as installRun } from "./commands/install.js";
import { run as uninstallRun } from "./commands/uninstall.js";
import { run as listRun } from "./commands/list.js";
import { runDoctor, formatResults } from "./commands/doctor.js";
import { run as rmRun } from "./commands/rm.js";
import { run as syncRun } from "./commands/sync.js";
import { run as upgradeRun } from "./commands/upgrade.js";

// Single source of truth — reads version from package.json
const require = createRequire(import.meta.url);
const VERSION: string = (require("../package.json") as { version: string }).version;

// Synced by bump-version.sh when plugin version changes.
// Cannot read .claude-plugin/plugin.json at runtime — it's outside the npm package.
export const PLUGIN_VERSION = "0.8.1";

const KNOWN_COMMANDS = new Set([
  "install",
  "uninstall",
  "list",
  "rm",
  "doctor",
  "init",
  "sync",
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

export function printVersion(): void {
  console.log(`cli:    ${VERSION}`);
  console.log(`plugin: ${PLUGIN_VERSION}`);
}

function printHelp(): void {
  console.log(`skill-forge v${VERSION}

Usage: skill-forge <command>

Commands:
  install [--scope <project|user>]  Install plugin (prompts if no scope)
  uninstall        Uninstall skill-forge (project scope first, fallback to user)
  list             Print skill registry (project scope first, fallback to user)
  rm <name> [...]  Remove skills (--force to skip confirmation)
  doctor           Diagnose environment health
  init             Initialize .claude/skills/ (project scope if .git/.claude exists, else user scope)
  sync             Sync embedded plugin to latest release (project scope)
  upgrade          Upgrade CLI to latest npm version

Options:
  --help, -h       Show this help
  --version, -v    Show version`);
}

async function main(): Promise<void> {
  const { command, args } = parseCommand(process.argv);
  const cwd = process.cwd();

  switch (command) {
    case "help":
      printHelp();
      break;

    case "version":
      printVersion();
      break;

    case "install":
      await installRun(args);
      break;

    case "uninstall":
      uninstallRun(cwd);
      break;

    case "list":
      console.log(listRun(cwd));
      break;

    case "rm":
      await rmRun(cwd, args);
      break;

    case "doctor": {
      const results = runDoctor(cwd);
      console.log(formatResults(results));
      if (results.some((r) => r.status === "fail")) process.exit(1);
      break;
    }

    case "init":
      initRun(cwd);
      break;

    case "sync":
      syncRun(cwd);
      break;

    case "upgrade":
      upgradeRun();
      break;

    default:
      console.error(`Unknown command: ${args[0]}. Run skill-forge --help.`);
      process.exit(1);
  }
}

main().catch((error: unknown) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exit(1);
});
