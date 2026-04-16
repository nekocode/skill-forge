// Uninstall skill-forge: resolve scope, detect embed vs plugin, clean accordingly.

import { execSync } from "node:child_process";
import { PLUGIN_NAME, resolveRoot } from "../types.js";
import { detectEmbedInstall, removeEmbedFiles } from "./embed.js";

export function run(cwd: string): void {
  const { root, scope } = resolveRoot(cwd);

  if (detectEmbedInstall(root)) {
    console.log(`Removing embedded skill-forge files... [${scope}]`);
    removeEmbedFiles(root);
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
