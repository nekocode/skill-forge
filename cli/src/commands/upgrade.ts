// Upgrade skill-forge CLI to latest version via npm.
// Wraps: `npm update -g @nekocode/skill-forge`

import { execSync } from "node:child_process";

export function run(): void {
  try {
    console.log("Upgrading skill-forge...");
    execSync("npm update -g @nekocode/skill-forge", { stdio: "inherit" });
    console.log("Done.");
  } catch {
    console.error("Failed to upgrade. Try manually: npm update -g @nekocode/skill-forge");
    process.exit(1);
  }
}
