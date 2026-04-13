// Initialize .claude/skills/ directory structure in a project.
// Idempotent — wx flag atomically skips if registry already exists.

import fs from "node:fs";
import { EMPTY_REGISTRY, skillsDir, registryPath } from "../types.js";

export function run(projectRoot: string): void {
  const dir = skillsDir(projectRoot);
  fs.mkdirSync(dir, { recursive: true });

  try {
    fs.writeFileSync(
      registryPath(projectRoot),
      JSON.stringify(EMPTY_REGISTRY, null, 2),
      { flag: "wx" },
    );
  } catch (e: unknown) {
    if ((e as NodeJS.ErrnoException).code !== "EEXIST") throw e;
  }
}
