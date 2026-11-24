// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026-present the Unsloth AI Inc. team. All rights reserved. See /studio/LICENSE.AGPL-3.0

// What a page reports since it loaded (errors, blocked requests) reaches the browser agent; the
// web build's screenshots come from the page's own drawing; check_page travels with the code tools.

import assert from "node:assert/strict";
import test from "node:test";

import { readSrc, registerBundlerResolver } from "./helpers/kit.ts";

registerBundlerResolver();
const reports = await import("../src/features/browser/page-console.ts");
const { parseFrameMessage } = await import("../src/features/browser/frame-message.ts");
const { selectCodeToolNames } = await import("../src/features/chat/api/code-tool-placement.ts");

test("a page's errors are kept once each, for the document that reported them", () => {
  reports.resetPageReports("t1", "frame:1");
  reports.recordPageReport("t1", "frame:1", "Uncaught ReferenceError: player is not defined");
  reports.recordPageReport("t1", "frame:1", "Uncaught ReferenceError: player is not defined");
  reports.recordPageReport("t1", "frame:0", "from the page before");
  assert.deepEqual(reports.pageReports("t1"), ["Uncaught ReferenceError: player is not defined"]);
  reports.resetPageReports("t1", "frame:2");
  assert.deepEqual(reports.pageReports("t1"), []);
  reports.forgetPageReports("t1");
});

test("a game loop's flood is capped, and blocked hosts are named", () => {
  reports.setPageReports(
    "t2",
    "file:a",
    Array.from({ length: 30 }, (_, index) => `error ${index}`),
    ["cdn.jsdelivr.net", "cdn.jsdelivr.net"],
  );
  const lines = reports.pageReports("t2");
  assert.equal(lines.length, reports.PAGE_REPORTS_SHOWN + 2);
  assert.match(lines[reports.PAGE_REPORTS_SHOWN], /18 more not shown/);
  assert.match(lines.at(-1) ?? "", /Blocked requests .*: cdn\.jsdelivr\.net$/);
  reports.forgetPageReports("t2");
});

test("long reports are cut to one line", () => {
  reports.setPageReports("t3", "file:b", [`a\n${"x".repeat(2000)}`]);
  const [line] = reports.pageReports("t3");
  assert.ok(line.length <= reports.PAGE_REPORT_MAX_CHARS);
  assert.ok(!line.includes("\n"));
  reports.forgetPageReports("t3");
});

test("the frame relays a page error as text, and refuses anything else", () => {
  assert.deepEqual(parseFrameMessage({ source: "unsloth-browser", type: "pageError", text: "Uncaught boom" }), {
    type: "pageError",
    text: "Uncaught boom",
  });
  assert.equal(parseFrameMessage({ source: "unsloth-browser", type: "pageError", text: 42 }), null);
  assert.equal(parseFrameMessage({ source: "unsloth-browser", type: "pageError", text: "x".repeat(5000) }), null);
});

test("the page shell hooks errors before the page's scripts, and native views do too", () => {
  const shell = readSrc("../../backend/routes/browser.py");
  assert.match(shell, /type: "pageError"/);
  assert.match(shell, /addEventListener\("unhandledrejection"/);
  const native = readSrc("../../src-tauri/src/browser_webview.rs");
  assert.match(native, /\.initialization_script\(PAGE_ERRORS_SCRIPT\)/);
  assert.match(native, /Symbol\.for\("ganjalf\.browser\.errors"\)/);
  assert.match(readSrc("features/browser/agent/page-agent.ts"), /Symbol\.for\("ganjalf\.browser\.errors"\)/);
});

test("the web build screenshots through the page's own drawing", () => {
  const executor = readSrc("features/browser/agent/executor.ts");
  assert.match(executor, /if \(!isTauri\) \{[\s\S]*?return pageScreenshot\(tab, entry, context\);/);
  assert.doesNotMatch(executor, /screenshots of the browser panel need the desktop app/);
  const agent = readSrc("features/browser/agent/page-agent.ts");
  assert.match(agent, /case "render":/);
  assert.match(agent, /requestAnimationFrame\(grab\)/);
});

test("check_page is sent with the local code tools and shows its screenshot", () => {
  assert.deepEqual(
    selectCodeToolNames({ codeToolsEnabled: true, hostedCodeExecutionForThisTurn: false, providerHostsCodeExecution: false }).local,
    ["python", "terminal", "edit_file", "view_image", "check_page"],
  );
  assert.match(readSrc("features/chat/api/mcp-images.ts"), /name === "check_page"/);
  assert.match(readSrc("components/assistant-ui/tool-fallback.tsx"), /toolName === "check_page"/);
});
