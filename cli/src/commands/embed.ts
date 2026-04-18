// Core embed module: download tarball from GitHub release, extract,
// install files into .claude/, convert hook paths, merge settings,
// manage version.json, detect and remove embed install.

import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import { execSync } from "node:child_process";

import {
  GITHUB_REPO,
  EMBED_VERSION_FILE,
  EMBED_HOOKS_DIR,
  EMBED_COMMANDS,
  embedCommandName,
} from "../types.js";

// ── Types ────────────────────────────────────────────────────────────────

export interface EmbedVersion {
  version: string;
  installed: string;
}

// ── Path rewrite constants ───────────────────────────────────────────────

const PLUGIN_ROOT_HOOKS = "${CLAUDE_PLUGIN_ROOT}/hooks/";
const PLUGIN_ROOT_SKILLS = "${CLAUDE_PLUGIN_ROOT}/skills/";

// _ENV form: expanded by hook processes, which Claude Code launches with
// CLAUDE_PROJECT_DIR set. Used in hooks.json entries.
const EMBED_HOOKS_PATH_ENV = "${CLAUDE_PROJECT_DIR}/.claude/hooks/skill-forge/";
const EMBED_SKILLS_PATH_ENV = "${CLAUDE_PROJECT_DIR}/.claude/skills/";

// _REL form: Bash tool runs with CWD = project root but does NOT receive
// CLAUDE_PROJECT_DIR. Used in SKILL.md body and command markdown.
const EMBED_HOOKS_PATH_REL = ".claude/hooks/skill-forge/";
const EMBED_SKILLS_PATH_REL = ".claude/skills/";

/** True if a settings.json hook entry belongs to skill-forge. */
function isSkillForgeEntry(entry: any): boolean {
  return JSON.stringify(entry).includes(EMBED_HOOKS_PATH_REL);
}

// ── rewriteHooksJsonPaths ────────────────────────────────────────────────

/** Rewrite plugin paths for hooks.json entries (expanded by hook process). */
export function rewriteHooksJsonPaths(text: string): string {
  return text
    .split(PLUGIN_ROOT_HOOKS).join(EMBED_HOOKS_PATH_ENV)
    .split(PLUGIN_ROOT_SKILLS).join(EMBED_SKILLS_PATH_ENV);
}

// ── rewriteContentPaths ──────────────────────────────────────────────────

/** Rewrite plugin paths for markdown bodies (run via Bash tool, CWD-based). */
export function rewriteContentPaths(text: string): string {
  return text
    .split(PLUGIN_ROOT_HOOKS).join(EMBED_HOOKS_PATH_REL)
    .split(PLUGIN_ROOT_SKILLS).join(EMBED_SKILLS_PATH_REL);
}

// ── convertHooksForEmbed ─────────────────────────────────────────────────

/** Rewrite hook command paths from plugin-mode variables to embed-mode. */
export function convertHooksForEmbed(pluginHooks: any): any {
  return JSON.parse(rewriteHooksJsonPaths(JSON.stringify(pluginHooks)));
}

// ── rewriteCommandContent ────────────────────────────────────────────────

/** Strip plugin namespace and rewrite paths in command markdown. */
export function rewriteCommandContent(text: string): string {
  return rewriteContentPaths(
    text.split("skill-forge:skill-forge").join("skill-forge"),
  );
}

// ── mergeHooksIntoSettings ───────────────────────────────────────────────

/**
 * Merge embed hook entries into existing settings.json content.
 * - Removes any existing skill-forge entries (identified by path marker)
 * - Appends new embed entries per event
 * - Preserves all non-hook settings
 */
export function mergeHooksIntoSettings(existing: any, embedHooks: any): any {
  const result = { ...existing };
  const existingHooks: Record<string, any[]> = { ...(result.hooks ?? {}) };

  // Strip all existing SF entries from every event
  for (const event of Object.keys(existingHooks)) {
    existingHooks[event] = (existingHooks[event] ?? []).filter(
      (entry: any) => !isSkillForgeEntry(entry),
    );
  }

  // Append new SF entries
  const newHooks: Record<string, any[]> = embedHooks.hooks ?? {};
  for (const [event, entries] of Object.entries(newHooks)) {
    existingHooks[event] = [...(existingHooks[event] ?? []), ...entries];
  }

  result.hooks = existingHooks;
  return result;
}

// ── writeVersionFile ─────────────────────────────────────────────────────

/** Write version.json with version + ISO timestamp. Auto-creates parent dirs. */
export function writeVersionFile(filePath: string, version: string): void {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  const data: EmbedVersion = {
    version,
    installed: new Date().toISOString(),
  };
  fs.writeFileSync(filePath, JSON.stringify(data, null, 2));
}

// ── readVersionFile ──────────────────────────────────────────────────────

/** Read version.json. Returns null on any error (missing, bad JSON, etc). */
export function readVersionFile(filePath: string): EmbedVersion | null {
  try {
    const raw = fs.readFileSync(filePath, "utf-8");
    return JSON.parse(raw) as EmbedVersion;
  } catch {
    return null;
  }
}

// ── detectEmbedInstall ───────────────────────────────────────────────────

/** Returns true if .claude/hooks/skill-forge/version.json exists. */
export function detectEmbedInstall(projectRoot: string): boolean {
  return fs.existsSync(path.join(projectRoot, EMBED_VERSION_FILE));
}

// ── removeEmbedFiles ─────────────────────────────────────────────────────

/**
 * Remove all skill-forge embed files from a project root.
 * - Removes SF command files (prefixed + legacy bare forms)
 * - Removes .claude/skills/skill-forge/
 * - Removes .claude/hooks/skill-forge/
 * - Strips SF hooks from .claude/settings.json
 * - Cleans up empty event arrays and empty hooks object
 */
export function removeEmbedFiles(projectRoot: string): void {
  const commandsDir = path.join(projectRoot, ".claude", "commands");
  for (const file of EMBED_COMMANDS) {
    fs.rmSync(path.join(commandsDir, embedCommandName(file)), { force: true });
  }

  // Remove SF skills dir
  const sfSkillsDir = path.join(projectRoot, ".claude", "skills", "skill-forge");
  fs.rmSync(sfSkillsDir, { recursive: true, force: true });

  // Remove SF hooks dir
  const sfHooksDir = path.join(projectRoot, EMBED_HOOKS_DIR);
  fs.rmSync(sfHooksDir, { recursive: true, force: true });

  // Update settings.json — strip SF hooks
  const settingsPath = path.join(projectRoot, ".claude", "settings.json");
  if (!fs.existsSync(settingsPath)) return;

  let settings: any;
  try {
    settings = JSON.parse(fs.readFileSync(settingsPath, "utf-8"));
  } catch {
    return; // Corrupted settings — leave it alone
  }

  if (!settings.hooks) {
    return;
  }

  const hooks: Record<string, any[]> = settings.hooks;

  // Strip SF entries from each event
  for (const event of Object.keys(hooks)) {
    hooks[event] = (hooks[event] ?? []).filter(
      (entry: any) => !isSkillForgeEntry(entry),
    );
    // Delete empty event arrays
    if (hooks[event]!.length === 0) {
      delete hooks[event];
    }
  }

  // Delete empty hooks object
  if (Object.keys(hooks).length === 0) {
    delete settings.hooks;
  }

  fs.writeFileSync(settingsPath, JSON.stringify(settings, null, 2));
}

// ── copyDirRecursive (internal) ───────────────────────────────────────────

/** Recursively copy src directory into dest. Creates dest if missing. */
function copyDirRecursive(src: string, dest: string): void {
  fs.mkdirSync(dest, { recursive: true });
  for (const entry of fs.readdirSync(src, { withFileTypes: true })) {
    const srcPath = path.join(src, entry.name);
    const destPath = path.join(dest, entry.name);
    if (entry.isDirectory()) {
      copyDirRecursive(srcPath, destPath);
    } else {
      fs.copyFileSync(srcPath, destPath);
    }
  }
}

// ── embedInstall ─────────────────────────────────────────────────────────

/**
 * Full embed install flow:
 * 1. Fetch latest release tag via gh CLI
 * 2. Download tarball to temp dir
 * 3. Extract tarball
 * 4. Copy files into .claude/
 * 5. Convert hooks + merge into settings.json
 * 6. Write version.json
 * 7. Clean up temp dir (always, via finally)
 * Returns installed version string.
 */
export function embedInstall(projectRoot: string, tag?: string): string {
  // Fetch latest release tag unless caller already resolved it
  if (!tag) {
    tag = execSync(
      `gh api repos/${GITHUB_REPO}/releases/latest --jq '.tag_name'`,
      { encoding: "utf-8" },
    ).trim();
  }

  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "sf-embed-install-"));

  try {
    // Download tarball
    execSync(
      `gh release download ${tag} --repo ${GITHUB_REPO} --pattern "skill-forge-*.tar.gz" --dir "${tmpDir}"`,
      { encoding: "utf-8" },
    );

    // Find the downloaded tarball
    const tarballs = fs.readdirSync(tmpDir).filter((f) => f.endsWith(".tar.gz"));
    if (tarballs.length === 0) {
      throw new Error("No tarball found after gh release download");
    }
    const tarball = path.join(tmpDir, tarballs[0]!);

    // Extract tarball into tmpDir
    execSync(`tar -xzf "${tarball}" -C "${tmpDir}"`, { encoding: "utf-8" });

    // Detect extraction root: prefer directory named after the tarball or just tmpDir
    // Release tarballs may extract into a subdirectory — find commands/
    const extractRoot = findExtractRoot(tmpDir);

    // Version derived from tag (tarball doesn't include .claude-plugin/)
    const version = tag.replace(/^v/, "");

    // Copy commands/*.md → .claude/commands/ (with plugin prefix)
    const srcCommandsDir = path.join(extractRoot, "commands");
    const destCommandsDir = path.join(projectRoot, ".claude", "commands");
    fs.mkdirSync(destCommandsDir, { recursive: true });
    if (fs.existsSync(srcCommandsDir)) {
      for (const file of EMBED_COMMANDS) {
        const src = path.join(srcCommandsDir, file);
        if (fs.existsSync(src)) {
          const dest = path.join(destCommandsDir, embedCommandName(file));
          const content = fs.readFileSync(src, "utf-8");
          fs.writeFileSync(dest, rewriteCommandContent(content));
        }
      }
    }

    // Copy skills/skill-forge/ → .claude/skills/skill-forge/
    const srcSkillsDir = path.join(extractRoot, "skills", "skill-forge");
    const destSkillsDir = path.join(projectRoot, ".claude", "skills", "skill-forge");
    if (fs.existsSync(srcSkillsDir)) {
      copyDirRecursive(srcSkillsDir, destSkillsDir);
      // Rewrite SKILL.md inline script paths for embed mode. Use content-mode
      // (relative) paths since body bash blocks run via Claude's Bash tool
      // which doesn't set CLAUDE_PROJECT_DIR.
      const skillMdPath = path.join(destSkillsDir, "SKILL.md");
      if (fs.existsSync(skillMdPath)) {
        const content = fs.readFileSync(skillMdPath, "utf-8");
        fs.writeFileSync(skillMdPath, rewriteContentPaths(content));
      }
    }

    // Copy hooks/*.py → .claude/hooks/skill-forge/
    const srcHooksDir = path.join(extractRoot, "hooks");
    const destHooksDir = path.join(projectRoot, EMBED_HOOKS_DIR);
    fs.mkdirSync(destHooksDir, { recursive: true });
    if (fs.existsSync(srcHooksDir)) {
      for (const entry of fs.readdirSync(srcHooksDir, { withFileTypes: true })) {
        if (!entry.isDirectory() && entry.name.endsWith(".py")) {
          fs.copyFileSync(
            path.join(srcHooksDir, entry.name),
            path.join(destHooksDir, entry.name),
          );
        }
      }
    }

    // Read hooks.json, convert paths, merge into settings.json
    const hooksJsonPath = path.join(srcHooksDir, "hooks.json");
    if (fs.existsSync(hooksJsonPath)) {
      const rawHooks = JSON.parse(fs.readFileSync(hooksJsonPath, "utf-8"));
      const embedHooks = convertHooksForEmbed(rawHooks);

      const settingsPath = path.join(projectRoot, ".claude", "settings.json");
      let existingSettings: any = {};
      if (fs.existsSync(settingsPath)) {
        try {
          existingSettings = JSON.parse(fs.readFileSync(settingsPath, "utf-8"));
        } catch {
          // Corrupted settings — start fresh
        }
      }

      const merged = mergeHooksIntoSettings(existingSettings, embedHooks);
      fs.mkdirSync(path.dirname(settingsPath), { recursive: true });
      fs.writeFileSync(settingsPath, JSON.stringify(merged, null, 2));
    }

    // Write version.json
    const versionFilePath = path.join(projectRoot, EMBED_VERSION_FILE);
    writeVersionFile(versionFilePath, version);

    return version;
  } finally {
    // Always clean up temp dir
    fs.rmSync(tmpDir, { recursive: true, force: true });
  }
}

// ── findExtractRoot (internal) ────────────────────────────────────────────

/**
 * Locate the root of extracted tarball content within tmpDir.
 * Tarballs may extract into a subdirectory (e.g., skill-forge-0.5.0/).
 * Looks for a directory containing "commands/" or "hooks/".
 * Falls back to tmpDir itself.
 */
function findExtractRoot(tmpDir: string): string {
  // Check tmpDir directly first
  if (
    fs.existsSync(path.join(tmpDir, "commands")) ||
    fs.existsSync(path.join(tmpDir, "hooks"))
  ) {
    return tmpDir;
  }

  // Check immediate subdirectories
  for (const entry of fs.readdirSync(tmpDir, { withFileTypes: true })) {
    if (!entry.isDirectory()) continue;
    const subDir = path.join(tmpDir, entry.name);
    if (
      fs.existsSync(path.join(subDir, "commands")) ||
      fs.existsSync(path.join(subDir, "hooks"))
    ) {
      return subDir;
    }
  }

  return tmpDir;
}
