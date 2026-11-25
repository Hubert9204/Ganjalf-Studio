// SPDX-License-Identifier: AGPL-3.0-only
// Ganjalf: plan mode switches itself off once a plan card has just been presented.

import assert from "node:assert/strict";
import test from "node:test";
import {
  planJustPresented,
  planModeField,
  usePlanModeStore,
} from "../src/features/chat/stores/plan-mode-store.ts";

test("a card that finishes on screen ends plan mode; an old complete card does not", () => {
  assert.equal(planJustPresented("running", "complete"), true);
  assert.equal(planJustPresented("requires-action", "complete"), true);
  assert.equal(planJustPresented(undefined, "complete"), false); // loaded from history
  assert.equal(planJustPresented("complete", "complete"), false);
  assert.equal(planJustPresented("running", "running"), false);
  assert.equal(planJustPresented("running", "incomplete"), false);
});

test("after it switches off, the next request asks for no plan mode", () => {
  usePlanModeStore.getState().setPlanMode(true);
  assert.deepEqual(planModeField(usePlanModeStore.getState().planMode, true), { plan_mode: true });
  if (planJustPresented("running", "complete")) usePlanModeStore.getState().setPlanMode(false);
  assert.deepEqual(planModeField(usePlanModeStore.getState().planMode, true), {});
});
