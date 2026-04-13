// Read .claude/skills/skill_registry.json and pretty-print as aligned table.
// Returns the formatted string (for testability) and prints to stdout when called from CLI.

import { loadRegistry } from "../types.js";

export function run(projectRoot: string): string {
  const result = loadRegistry(projectRoot);
  if (!result.ok) return result.error;

  const { registry } = result;
  if (registry.skills.length === 0) {
    return "No skills registered. Run /scan or /create inside Claude Code.";
  }

  // Sort by most recently updated
  const sorted = [...registry.skills].sort((a, b) =>
    b.updated.localeCompare(a.updated),
  );

  const headers = ["Name", "Ver", "Scope", "Score", "Trigger", "Updated"];
  const rows = sorted.map((s) => [
    s.name,
    s.version,
    s.scope,
    `${s.eval_score}/8`,
    // Loose equality handles both null (Python JSON) and undefined (missing field)
    s.trigger_score != null ? `${s.trigger_score}%` : "\u2014",
    s.updated,
  ]);

  return (
    `skill-forge registry (.claude/skills/)\n\n` + formatTable(headers, rows)
  );
}

/**
 * Format headers and rows into an aligned table with dynamic column widths.
 * Separator uses unicode box-drawing character.
 */
export function formatTable(headers: string[], rows: string[][]): string {
  if (rows.length === 0) return "";

  const colWidths = headers.map((h, i) => {
    const dataMax = rows.reduce((max, r) => Math.max(max, (r[i] ?? "").length), 0);
    return Math.max(h.length, dataMax);
  });

  const pad = (str: string, width: number) => str.padEnd(width);

  const headerLine = headers.map((h, i) => pad(h, colWidths[i]!)).join("  ");
  const separator = colWidths.map((w) => "\u2500".repeat(w)).join("\u2500\u2500");
  const dataLines = rows.map((row) =>
    row.map((cell, i) => pad(cell, colWidths[i]!)).join("  "),
  );

  return [headerLine, separator, ...dataLines].join("\n");
}
