// SPDX-License-Identifier: AGPL-3.0-only
// Ganjalf: one-line labels for the code-agent tools, like Claude Code's "Read file.ts (lines 1-80)".

import { toolArgText } from "./tool-arg-text.ts";

type Args = Record<string, unknown> | undefined;

/** Text for the collapsed card of read_file, grep, glob, terminal_output and terminal_kill. */
export function codeLookupLabel(toolName: string, args: Args, running: boolean): string {
  const path = toolArgText(args?.path);
  const pattern = toolArgText(args?.pattern);
  const id = toolArgText(args?.id);
  switch (toolName) {
    case "read_file": {
      const offset = Number(args?.offset);
      const limit = Number(args?.limit);
      const range =
        Number.isFinite(offset) && offset > 0
          ? ` (from line ${offset}${Number.isFinite(limit) && limit > 0 ? `, ${limit} lines` : ""})`
          : "";
      return `${running ? "Reading" : "Read"} ${path || "file"}${range}`;
    }
    case "grep": {
      const where = toolArgText(args?.glob) || path;
      return `${running ? "Searching" : "Searched"} /${pattern}/${where ? ` in ${where}` : ""}`;
    }
    case "glob":
      return `${running ? "Listing" : "Listed"} ${pattern || "**/*"}${path ? ` in ${path}` : ""}`;
    case "terminal_output":
      return `${running ? "Reading" : "Read"} output of ${id || "job"}`;
    case "terminal_kill":
      return `${running ? "Stopping" : "Stopped"} ${id || "job"}`;
    default:
      return toolName;
  }
}

/** "12 matches in 3 files", "240 lines", "5 files": what the result held, from its first line. */
export function codeLookupDetail(toolName: string, result: string): string {
  const first = result.split("\n", 1)[0] ?? "";
  if (result.startsWith("Error")) return "error";
  if (toolName === "grep") {
    const match = first.match(/^(\d+) match\(es\) in (\d+) file/);
    if (match) return `${match[1]} in ${match[2]} file${match[2] === "1" ? "" : "s"}`;
    const files = first.match(/^(\d+) file\(s\) match/);
    if (files) return `${files[1]} files`;
    return first.startsWith("No matches") ? "no matches" : "";
  }
  if (toolName === "glob") {
    const files = first.match(/^(\d+) file\(s\)/);
    return files ? `${files[1]} files` : first.startsWith("No files") ? "none" : "";
  }
  if (toolName === "read_file") {
    const lines = result.match(/\(lines (\d+)-(\d+) of (\d+)/);
    return lines ? `${Number(lines[2]) - Number(lines[1]) + 1} of ${lines[3]} lines` : "";
  }
  if (toolName === "terminal_output") {
    const status = result.match(/Status: ([^\n.]+)/);
    return status ? status[1] : "";
  }
  return "";
}
