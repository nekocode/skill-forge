// Initialize .claude/skills/ directory structure.
// Scope: walk up to find project root (.git/.claude), otherwise user (~).
// Idempotent — wx flag atomically skips if registry already exists.

import fs from "node:fs";
import { EMPTY_REGISTRY, skillsDir, registryPath, resolveTargetRoot } from "../types.js";

export function run(cwd: string): void {
  const { root, scope } = resolveTargetRoot(cwd);
  const dir = skillsDir(root);
  fs.mkdirSync(dir, { recursive: true });

  try {
    fs.writeFileSync(
      registryPath(root),
      JSON.stringify(EMPTY_REGISTRY, null, 2),
      { flag: "wx" },
    );
  } catch (e: unknown) {
    if ((e as NodeJS.ErrnoException).code !== "EEXIST") throw e;
  }

  console.log(`Initialized .claude/skills/ with empty registry. [${scope}]`);
}
