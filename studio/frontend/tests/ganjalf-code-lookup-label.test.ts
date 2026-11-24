// SPDX-License-Identifier: AGPL-3.0-only
import assert from "node:assert/strict";
import test from "node:test";
import { codeLookupDetail, codeLookupLabel } from "../src/components/assistant-ui/code-lookup-label.ts";

test("code-agent tool cards read like Claude Code's", () => {
  assert.equal(codeLookupLabel("read_file", { path: "src/a.ts", offset: 120, limit: 40 }, false), "Read src/a.ts (from line 120, 40 lines)");
  assert.equal(codeLookupLabel("read_file", { path: 42 }, true), "Reading 42");
  assert.equal(codeLookupLabel("grep", { pattern: "class Engine", glob: "*.ts" }, false), "Searched /class Engine/ in *.ts");
  assert.equal(codeLookupLabel("glob", {}, false), "Listed **/*");
  assert.equal(codeLookupLabel("terminal_output", { id: "bg2" }, false), "Read output of bg2");
  assert.equal(codeLookupLabel("terminal_kill", undefined, true), "Stopping job");
});

test("the detail summarises the result", () => {
  assert.equal(codeLookupDetail("grep", "12 match(es) in 3 file(s):\na:1:x"), "12 in 3 files");
  assert.equal(codeLookupDetail("grep", "No matches for /x/."), "no matches");
  assert.equal(codeLookupDetail("glob", "5 file(s), newest first:\na"), "5 files");
  assert.equal(codeLookupDetail("read_file", "...\n\n(lines 1-400 of 602; continue with offset=401)"), "400 of 602 lines");
  assert.equal(codeLookupDetail("terminal_output", "Background job bg1: x\nStatus: running for 4 s."), "running for 4 s");
  assert.equal(codeLookupDetail("read_file", "Error: nope"), "error");
});
