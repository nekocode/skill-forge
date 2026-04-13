// Shared types, constants, and helpers for CLI commands.
// Mirrors the registry schema from Python's shared.py.

import fs from "node:fs";
import path from "node:path";

export interface SkillEntry {
  name: string;
  version: string;
  scope: string;
  created: string;
  updated: string;
  auto_trigger: boolean;
  description_chars: number;
  eval_score: number;
  trigger_score: number | null;
  usage_count: number;
}

export interface SkillRegistry {
  version: string;
  skills: SkillEntry[];
}

// Empty registry fallback — matches Python's shared.load_registry default
export const EMPTY_REGISTRY: SkillRegistry = { version: "1", skills: [] };

// ── Plugin identity ─────────────────────────────────────────────────────

export const PLUGIN_NAME = "skill-forge";
export const MARKETPLACE_SOURCE = "nekocode/skill-forge";

// ── Path helpers ────────────────────────────────────────────────────────

export function skillsDir(root: string): string {
  return path.join(root, ".claude", "skills");
}

export function registryPath(root: string): string {
  return path.join(skillsDir(root), "skill_registry.json");
}

// ── Registry I/O ────────────────────────────────────────────────────────

export type RegistryLoadResult =
  | { ok: true; registry: SkillRegistry }
  | { ok: false; error: string };

/**
 * Load and validate skill_registry.json.
 * Returns structured error on missing file, corrupted JSON, or invalid schema.
 */
export function loadRegistry(projectRoot: string): RegistryLoadResult {
  const regPath = registryPath(projectRoot);

  let content: string;
  try {
    content = fs.readFileSync(regPath, "utf-8");
  } catch (e: unknown) {
    // ENOENT = file not found; anything else is unexpected I/O error
    if ((e as NodeJS.ErrnoException).code === "ENOENT") {
      return { ok: false, error: "No skill registry found. Run `skill-forge init` first." };
    }
    return { ok: false, error: "Failed to read skill_registry.json — I/O error." };
  }

  let raw: unknown;
  try {
    raw = JSON.parse(content);
  } catch {
    return { ok: false, error: "Failed to parse skill_registry.json — file may be corrupted." };
  }

  const registry = raw as SkillRegistry;
  if (!Array.isArray(registry.skills)) {
    return { ok: false, error: "Malformed skill_registry.json — missing skills array." };
  }

  return { ok: true, registry };
}

export function saveRegistry(projectRoot: string, registry: SkillRegistry): void {
  fs.writeFileSync(registryPath(projectRoot), JSON.stringify(registry, null, 2));
}
