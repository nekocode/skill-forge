// Install skill-forge: project scope embeds files directly, user scope uses plugin system.

import { execSync } from "node:child_process";
import { createInterface } from "node:readline";
import { PLUGIN_NAME, MARKETPLACE_SOURCE } from "../types.js";
import { embedInstall } from "./embed.js";

const VALID_SCOPES = ["project", "user"] as const;
type Scope = (typeof VALID_SCOPES)[number];

/** Parse --scope <value> from args. Returns undefined if not provided. */
export function parseScope(args: string[]): Scope | undefined {
  const index = args.indexOf("--scope");
  if (index === -1 || index + 1 >= args.length) return undefined;
  const value = args[index + 1]!;
  if (!VALID_SCOPES.includes(value as Scope)) {
    console.error(`Invalid scope: ${value}. Valid: ${VALID_SCOPES.join(", ")}`);
    process.exit(1);
  }
  return value as Scope;
}

/** Interactive scope prompt. Returns selected scope. */
export function promptScope(): Promise<Scope> {
  return new Promise((resolve) => {
    const rl = createInterface({ input: process.stdin, output: process.stdout });
    console.log("\nInstall scope:");
    console.log("  1) project  — embed into this project (team gets it on clone)");
    console.log("  2) user     — install plugin globally");
    rl.question("\nChoose [1/2] (default: 1): ", (answer) => {
      rl.close();
      const trimmed = answer.trim();
      if (trimmed === "" || trimmed === "1" || trimmed === "project") resolve("project");
      else if (trimmed === "2" || trimmed === "user") resolve("user");
      else {
        console.error(`Invalid choice: ${trimmed}`);
        process.exit(1);
      }
    });
  });
}

export async function run(args: string[]): Promise<void> {
  const scope = parseScope(args) ?? (await promptScope());

  if (scope === "project") {
    try {
      const version = embedInstall(process.cwd());
      console.log(`Embedded skill-forge ${version} into .claude/. Run \`skill-forge doctor\` to verify.`);
    } catch (e: unknown) {
      console.error(`Embed failed: ${e instanceof Error ? e.message : String(e)}`);
      console.error("Is `gh` CLI installed and authenticated?");
      process.exit(1);
    }
    return;
  }

  // User scope: plugin system
  try {
    console.log("Adding skill-forge to marketplace...");
    execSync(`claude plugin marketplace add ${MARKETPLACE_SOURCE}`, {
      stdio: "inherit",
    });

    console.log("Installing skill-forge plugin (user scope)...");
    execSync(`claude plugin install ${PLUGIN_NAME} --scope user`, {
      stdio: "inherit",
    });

    console.log("Done. Run `skill-forge doctor` to verify.");
  } catch {
    console.error("Failed. Is `claude` CLI installed and in PATH?");
    process.exit(1);
  }
}
