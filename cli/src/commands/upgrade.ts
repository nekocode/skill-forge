// Upgrade skill-forge CLI to latest version via npm.
// Uses `npm install@latest` instead of `npm update` to allow cross-major upgrades.

import { execSync } from "node:child_process";

const NPM_INSTALL_CMD = "npm install -g @nekocode/skill-forge@latest";

export function run(): void {
  try {
    console.log("Upgrading skill-forge CLI...");
    execSync(NPM_INSTALL_CMD, { stdio: "inherit" });
    console.log("Done.");
  } catch {
    console.error(`Failed to upgrade. Try manually: ${NPM_INSTALL_CMD}`);
    process.exit(1);
  }
}
