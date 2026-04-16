// Uninstall skill-forge: detect embed vs plugin install and clean accordingly.

import { execSync } from "node:child_process";
import { PLUGIN_NAME } from "../types.js";
import { detectEmbedInstall, removeEmbedFiles } from "./embed.js";

export function run(projectRoot: string): void {
  if (detectEmbedInstall(projectRoot)) {
    console.log("Removing embedded skill-forge files...");
    removeEmbedFiles(projectRoot);
    console.log("Done. Embed files removed from .claude/.");
    return;
  }

  // Plugin mode
  try {
    console.log("Uninstalling skill-forge plugin...");
    execSync(`claude plugin uninstall ${PLUGIN_NAME}`, { stdio: "inherit" });
    console.log("Done.");
  } catch {
    console.error("Failed. Is `claude` CLI installed and in PATH?");
    process.exit(1);
  }
}
