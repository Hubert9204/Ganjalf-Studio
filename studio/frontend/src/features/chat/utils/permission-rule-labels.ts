// SPDX-License-Identifier: AGPL-3.0-only
// Ganjalf: pure helpers for the project permission rules (no imports, so node tests load them).

/** The last two folders of a project path: enough to tell projects apart in a menu. */
export function projectLabel(path: string): string {
  const parts = path.split(/[\\/]+/).filter(Boolean);
  return parts.slice(-2).join("/") || path;
}

/** The command of a terminal card's arguments, or "". */
export function commandOf(args: unknown): string {
  if (!args || typeof args !== "object") return "";
  const value = (args as { command?: unknown }).command;
  return typeof value === "string" ? value : "";
}
