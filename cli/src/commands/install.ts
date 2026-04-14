// Install skill-forge plugin via claude CLI.
// Wraps: `claude plugin marketplace add nekocode/skill-forge && claude plugin install skill-forge --scope <scope>`
// Prompts for scope interactively unless --scope flag is provided.

import { execSync } from "node:child_process";
import { createInterface } from "node:readline";
import { PLUGIN_NAME, MARKETPLACE_SOURCE } from "../types.js";

const VALID_SCOPES = ["user", "project", "local"] as const;
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
    console.log("  1) user     — available in all projects");
    console.log("  2) project  — this project only");
    console.log("  3) local    — this project, not committed");
    rl.question("\nChoose [1/2/3] (default: 2): ", (answer) => {
      rl.close();
      const trimmed = answer.trim();
      if (trimmed === "" || trimmed === "2" || trimmed === "project") resolve("project");
      else if (trimmed === "1" || trimmed === "user") resolve("user");
      else if (trimmed === "3" || trimmed === "local") resolve("local");
      else {
        console.error(`Invalid choice: ${trimmed}`);
        process.exit(1);
      }
    });
  });
}

export async function run(args: string[]): Promise<void> {
  const scope = parseScope(args) ?? (await promptScope());

  try {
    console.log("Adding skill-forge to marketplace...");
    execSync(`claude plugin marketplace add ${MARKETPLACE_SOURCE}`, {
      stdio: "inherit",
    });

    console.log(`Installing skill-forge plugin (${scope} scope)...`);
    execSync(`claude plugin install ${PLUGIN_NAME} --scope ${scope}`, {
      stdio: "inherit",
    });

    console.log("Done. Run `skill-forge doctor` to verify.");
  } catch {
    console.error("Failed. Is `claude` CLI installed and in PATH?");
    process.exit(1);
  }
}
