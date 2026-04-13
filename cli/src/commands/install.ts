// Install skill-forge plugin via claude CLI.
// Wraps: `claude plugin marketplace add nekocode/skill-forge && claude plugin install skill-forge`
// No unit test — pure execSync delegation, testing would only verify Node child_process.

import { execSync } from "node:child_process";
import { PLUGIN_NAME, MARKETPLACE_SOURCE } from "../types.js";

export function run(): void {
  try {
    console.log("Adding skill-forge to marketplace...");
    execSync(`claude plugin marketplace add ${MARKETPLACE_SOURCE}`, {
      stdio: "inherit",
    });

    console.log("Installing skill-forge plugin...");
    execSync(`claude plugin install ${PLUGIN_NAME}`, { stdio: "inherit" });

    console.log("Done. Run `skill-forge doctor` to verify.");
  } catch {
    console.error("Failed. Is `claude` CLI installed and in PATH?");
    process.exit(1);
  }
}
