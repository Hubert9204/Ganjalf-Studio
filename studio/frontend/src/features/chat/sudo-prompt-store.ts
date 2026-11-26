// SPDX-License-Identifier: AGPL-3.0-only
// Ganjalf: a sudo password box asked for by an agent command (a `sudo_prompt` tool_output event).
import { create } from "zustand";

export type SudoPrompt = {
  id: string;
  sessionId: string;
  command: string;
  wrong: number;
  expiresAt: number;
};

/** The event as it comes off the chat stream, checked; stale or malformed requests are dropped. */
export function parseSudoPrompt(raw: unknown, now = Date.now()): SudoPrompt | null {
  if (!raw || typeof raw !== "object") return null;
  const value = raw as Record<string, unknown>;
  if (typeof value.id !== "string" || !value.id) return null;
  const expiresAt =
    typeof value.expires_at === "number" ? value.expires_at : now + 180_000;
  if (expiresAt <= now) return null;
  return {
    id: value.id,
    sessionId: typeof value.session_id === "string" ? value.session_id : "",
    command: typeof value.command === "string" ? value.command : "",
    wrong: typeof value.wrong === "number" ? value.wrong : 0,
    expiresAt,
  };
}

type SudoPromptState = {
  prompt: SudoPrompt | null;
  open: (prompt: SudoPrompt) => void;
  close: (id: string) => void;
};

export const useSudoPromptStore = create<SudoPromptState>((set) => ({
  prompt: null,
  open: (prompt) => set({ prompt }),
  close: (id) => set((state) => (state.prompt?.id === id ? { prompt: null } : state)),
}));
