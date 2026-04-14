// Upgrade skill-forge CLI to latest version via npm.
// Uses `npm install@latest` instead of `npm update` to allow cross-major upgrades.

import { execSync } from "node:child_process";

export function run(): void {
  try {
    console.log("Upgrading skill-forge...");
    execSync("npm install -g @nekocode/skill-forge@latest", { stdio: "inherit" });
    console.log("Done.");
  } catch {
    console.error("Failed to upgrade. Try manually: npm install -g @nekocode/skill-forge@latest");
    process.exit(1);
  }
}
