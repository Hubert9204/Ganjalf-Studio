// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026-present the Unsloth AI Inc. team. All rights reserved. See /studio/LICENSE.AGPL-3.0

// Ganjalf: how many tokens a local GGUF model may think before it must answer, sent as
// thinking_budget_tokens (Anthropic's thinking.budget_tokens). 0 keeps the model's load-time budget.

import { create } from "zustand";
import { persist } from "zustand/middleware";

export const THINKING_BUDGET_MAX = 32768;

export interface ThinkingBudgetState {
  thinkingBudgetTokens: number;
  setThinkingBudgetTokens: (tokens: number) => void;
}

export const useThinkingBudgetStore = create<ThinkingBudgetState>()(
  persist(
    (set) => ({
      thinkingBudgetTokens: 0,
      setThinkingBudgetTokens: (tokens) =>
        set({ thinkingBudgetTokens: Math.max(0, Math.min(THINKING_BUDGET_MAX, Math.round(tokens) || 0)) }),
    }),
    { name: "ganjalf_thinking_budget_tokens" },
  ),
);

/** The request field for a local model that thinks, or nothing when the budget is left to the model. */
export function thinkingBudgetField(thinking: boolean, tokens: number): { thinking_budget_tokens?: number } {
  return thinking && tokens > 0 ? { thinking_budget_tokens: tokens } : {};
}
