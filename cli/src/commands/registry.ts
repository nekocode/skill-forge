// Registry subcommands. Currently: `clean` — remove orphaned entries.
// An orphan is a registry entry whose skill directory no longer exists under .claude/skills/.

import fs from "node:fs";
import { loadRegistry, saveRegistry, skillsDir } from "../types.js";
import path from "node:path";

interface CleanResult {
  removed: string[];
  kept: string[];
  error?: undefined;
}

interface CleanError {
  error: string;
  removed?: undefined;
  kept?: undefined;
}

export function clean(root: string): CleanResult | CleanError {
  const result = loadRegistry(root);
  if (!result.ok) return { error: result.error };

  const { registry } = result;
  const dir = skillsDir(root);
  const kept: typeof registry.skills = [];
  const removed: string[] = [];

  for (const entry of registry.skills) {
    const skillDir = path.join(dir, entry.name);
    if (fs.existsSync(skillDir)) {
      kept.push(entry);
    } else {
      removed.push(entry.name);
    }
  }

  if (removed.length > 0) {
    saveRegistry(root, { ...registry, skills: kept });
  }

  return {
    removed,
    kept: kept.map((e) => e.name),
  };
}
