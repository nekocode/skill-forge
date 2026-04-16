// Remove one or more skills: delete directory + registry entry.
// Default: interactive confirmation. --force skips prompt.

import fs from "node:fs";
import path from "node:path";
import { createInterface } from "node:readline";
import {
  loadRegistry,
  saveRegistry,
  resolveRoot,
  skillsDir,
  type SkillRegistry,
} from "../types.js";

/** Extract --force flag from args. */
export function parseForce(args: string[]): boolean {
  return args.includes("--force");
}

/** Extract positional skill names (strip flag tokens, deduplicate). */
export function parseNames(args: string[]): string[] {
  return [...new Set(args.filter((a) => !a.startsWith("--")))];
}

/** Prompt user to confirm deletion. Default (empty) = cancel. */
export function promptConfirm(names: string[]): Promise<boolean> {
  return new Promise((resolve) => {
    const rl = createInterface({ input: process.stdin, output: process.stdout });
    console.log(`\nWill delete: ${names.join(", ")}`);
    rl.question("Confirm? [y/N]: ", (answer) => {
      rl.close();
      resolve(answer.trim().toLowerCase() === "y");
    });
  });
}

/** Delete validated skills from disk and registry. */
export function removeSkills(
  root: string,
  registry: SkillRegistry,
  names: string[],
): void {
  const dir = skillsDir(root);
  for (const name of names) {
    fs.rmSync(path.join(dir, name), { recursive: true, force: true });
    console.log(`Removed: ${name}`);
  }
  registry.skills = registry.skills.filter((s) => !names.includes(s.name));
  saveRegistry(root, registry);
}

export async function run(cwd: string, args: string[]): Promise<void> {
  const force = parseForce(args);
  const names = parseNames(args);

  if (names.length === 0) {
    console.error("Usage: skill-forge rm <name> [name2...] [--force]");
    process.exit(1);
  }

  const { root } = resolveRoot(cwd);
  const result = loadRegistry(root);
  if (!result.ok) {
    console.error(result.error);
    process.exit(1);
  }

  const { registry } = result;
  const registered = new Set(registry.skills.map((s) => s.name));

  const found: string[] = [];
  const notFound: string[] = [];
  for (const name of names) {
    if (registered.has(name)) {
      found.push(name);
    } else {
      notFound.push(name);
    }
  }

  for (const name of notFound) {
    console.error(`Skill not found: ${name}`);
  }

  if (found.length === 0) {
    process.exit(1);
  }

  if (!force) {
    const confirmed = await promptConfirm(found);
    if (!confirmed) {
      console.log("Aborted.");
      return;
    }
  }

  removeSkills(root, registry, found);

  if (notFound.length > 0) {
    process.exit(1);
  }
}
