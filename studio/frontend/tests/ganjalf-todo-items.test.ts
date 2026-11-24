// SPDX-License-Identifier: AGPL-3.0-only
import assert from "node:assert/strict";
import test from "node:test";
import { todoItems, todoSummary } from "../src/components/assistant-ui/todo-items.ts";

test("the task list card reads the model's list and summarises progress", () => {
  const items = todoItems([
    { content: "Scene", status: "completed" },
    { content: "Camera", status: "in_progress", activeForm: "Adding the camera" },
    { content: "HUD", status: "pending" },
    { content: "  ", status: "pending" },
    "junk",
  ]);
  assert.equal(items.length, 3);
  assert.equal(todoSummary(items), "1/3 · Adding the camera");
  assert.deepEqual(todoItems('[{"content":"a","status":"pending"}]'), [
    { content: "a", status: "pending", activeForm: undefined },
  ]);
  assert.deepEqual(todoItems("not json"), []);
  assert.equal(todoSummary(todoItems([{ content: "a", status: "completed" }])), "1/1");
});

test("plan mode is sent only with the code tools", async () => {
  const { planModeField, usePlanModeStore } = await import("../src/features/chat/stores/plan-mode-store.ts");
  assert.deepEqual(planModeField(true, true), { plan_mode: true });
  assert.deepEqual(planModeField(true, false), {});
  assert.deepEqual(planModeField(false, true), {});
  usePlanModeStore.getState().setPlanMode(true);
  assert.equal(usePlanModeStore.getState().planMode, true);
});
