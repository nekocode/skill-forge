// Sync embedded skill-forge files from latest GitHub release.
// Only works for project-embed installs. For CLI upgrades, use `upgrade`.

import { execSync } from "node:child_process";
import {
  detectEmbedInstall,
  readVersionFile,
  embedInstall,
} from "./embed.js";
import { GITHUB_REPO, EMBED_VERSION_FILE } from "../types.js";
import path from "node:path";

export function run(projectRoot: string): void {
  if (!detectEmbedInstall(projectRoot)) {
    console.error(
      "No embedded install found. Run `skill-forge install --scope project` first.",
    );
    process.exit(1);
  }

  const versionPath = path.join(projectRoot, EMBED_VERSION_FILE);
  const current = readVersionFile(versionPath);
  const currentVersion = current?.version ?? "unknown";

  let latestTag: string;
  try {
    latestTag = execSync(
      `gh api repos/${GITHUB_REPO}/releases/latest --jq '.tag_name'`,
      { encoding: "utf-8" },
    ).trim();
  } catch {
    console.error("Failed to check latest release. Is `gh` CLI installed and authenticated?");
    process.exit(1);
  }

  const latestVersion = latestTag.replace(/^v/, "");

  if (currentVersion === latestVersion) {
    console.log(`Already up to date (${currentVersion}).`);
    return;
  }

  console.log(`Syncing: ${currentVersion} → ${latestVersion}`);
  const installed = embedInstall(projectRoot, latestTag);
  console.log(`Done. Synced to ${installed}.`);
}
