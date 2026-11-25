// SPDX-License-Identifier: AGPL-3.0-only
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { commandOf, projectLabel } from "../src/features/chat/utils/permission-rule-labels.ts";

test("a project shows by its last two folders", () => {
  assert.equal(projectLabel("/home/hubert/Scrivania/Test Game"), "Scrivania/Test Game");
  assert.equal(projectLabel("C:\\Users\\h\\proj"), "h/proj");
});

test("only a terminal command string is read from the arguments", () => {
  assert.equal(commandOf({ command: "npm run build" }), "npm run build");
  assert.equal(commandOf({ command: 3 }), "");
  assert.equal(commandOf(null), "");
});

test("the card offers the project rules and still allows the call when saving fails", () => {
  const card = readFileSync(
    new URL("../src/components/assistant-ui/tool-confirmation-controls.tsx", import.meta.url),
    "utf8",
  );
  assert.match(card, /await addPermissionRule\(ruleSession, rule\)\.catch\(\(\) => undefined\);\n\s*await resolve\("allow"\);/);
  assert.match(card, /allowWithRule\(\{ command_prefix: rulePrefix \}\)/);
  assert.match(card, /allowWithRule\(\{ tool: "edit_file" \}\)/);
});
