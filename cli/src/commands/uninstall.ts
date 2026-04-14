// Uninstall skill-forge plugin via claude CLI.
// Wraps: `claude plugin uninstall skill-forge`
// Mirrors upgrade.ts pattern — tested via mocked execSync.

import { execSync } from "node:child_process";
import { PLUGIN_NAME } from "../types.js";

export function run(): void {
  try {
    console.log("Uninstalling skill-forge plugin...");
    execSync(`claude plugin uninstall ${PLUGIN_NAME}`, { stdio: "inherit" });
    console.log("Done.");
  } catch {
    console.error("Failed. Is `claude` CLI installed and in PATH?");
    process.exit(1);
  }
}
