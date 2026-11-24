// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026-present the Unsloth AI Inc. team. All rights reserved. See /studio/LICENSE.AGPL-3.0

// The Thinking Budget slider: sent as thinking_budget_tokens to local models that think, never when
// left on Auto or when thinking is off.

import assert from "node:assert/strict";
import test from "node:test";

import { installLocalStorageFake, readSrc, registerBundlerResolver } from "./helpers/kit.ts";

registerBundlerResolver();
installLocalStorageFake();
const store = await import("../src/features/chat/stores/thinking-budget-store.ts");

test("Auto (0) and thinking off send nothing; a budget is sent as is", () => {
  assert.deepEqual(store.thinkingBudgetField(true, 0), {});
  assert.deepEqual(store.thinkingBudgetField(false, 4096), {});
  assert.deepEqual(store.thinkingBudgetField(true, 4096), { thinking_budget_tokens: 4096 });
});

test("the stored budget is clamped to the slider's range", () => {
  const { setThinkingBudgetTokens } = store.useThinkingBudgetStore.getState();
  setThinkingBudgetTokens(-5);
  assert.equal(store.useThinkingBudgetStore.getState().thinkingBudgetTokens, 0);
  setThinkingBudgetTokens(10_000_000);
  assert.equal(store.useThinkingBudgetStore.getState().thinkingBudgetTokens, store.THINKING_BUDGET_MAX);
});

test("local requests and the settings sheet use it", () => {
  assert.match(readSrc("features/chat/api/chat-adapter.ts"), /\.\.\.thinkingBudgetField\(\n\s*supportsReasoning && \(reasoningEnabled \|\| reasoningAlwaysOn\),/);
  assert.match(readSrc("features/chat/chat-settings-sheet.tsx"), /\{!isExternalModel && supportsReasoning \? <ThinkingBudgetSlider \/> : null\}/);
});
