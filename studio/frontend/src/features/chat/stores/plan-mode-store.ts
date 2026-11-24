// SPDX-License-Identifier: AGPL-3.0-only
// Ganjalf: plan mode (Claude Code's): the model explores read-only and presents a plan with
// exit_plan_mode before it changes anything. Sent as plan_mode with the local code tools.

import { create } from "zustand";

export interface PlanModeState {
  planMode: boolean;
  setPlanMode: (on: boolean) => void;
}

export const usePlanModeStore = create<PlanModeState>()((set) => ({
  planMode: false,
  setPlanMode: (on) => set({ planMode: on }),
}));

/** The request field: only while plan mode is on and the code tools are offered. */
export function planModeField(planMode: boolean, codeTools: boolean): { plan_mode?: true } {
  return planMode && codeTools ? { plan_mode: true } : {};
}

/** What the approve button puts in the composer. */
export const PLAN_APPROVED_TEXT = "Piano approvato: procedi con l'implementazione.";
