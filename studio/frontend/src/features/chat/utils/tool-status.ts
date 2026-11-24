// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026-present the Unsloth AI Inc. team. All rights reserved. See /studio/LICENSE.AGPL-3.0

/** Mirrors NUDGE_TOOL_CALLS_STATUS in backend core/inference/tool_call_parser.py; keep in sync. */
export const NUDGE_TOOL_CALLS_STATUS = "Nudging tool calls";

export type ToolStatusKind = "nudge" | "terminal" | "web";

export function toolStatusKind(status: string): ToolStatusKind {
  if (status === NUDGE_TOOL_CALLS_STATUS) {
    return "nudge";
  }
  // edit_file reports "Editing: name" and check_page "Checking page: name"; both are local, so no globe.
  return status.startsWith("Running") || status.startsWith("Editing") || status.startsWith("Checking page")
    ? "terminal"
    : "web";
}
