// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026-present the Unsloth AI Inc. team. All rights reserved. See /studio/LICENSE.AGPL-3.0

// Ganjalf's name in the UI, and its busy mark in the thinking, generating and tool-running states.

import assert from "node:assert/strict";
import test from "node:test";

import {
  installLocalStorageFake,
  readSrc,
  registerBundlerResolver,
} from "./helpers/kit.ts";

registerBundlerResolver();
installLocalStorageFake();
const { rebrand } = await import("../src/i18n/messages.ts");

test("catalog text says Ganjalf, with the article fixed where Unsloth was elided", () => {
  assert.equal(rebrand("chat.x", "Open Unsloth Studio"), "Open Ganjalf Studio");
  assert.equal(rebrand("chat.x", "an Unsloth server"), "a Ganjalf server");
  assert.equal(rebrand("chat.x", "An Unsloth install"), "A Ganjalf install");
  assert.equal(
    rebrand("chat.x", "les réglages d'Unsloth"),
    "les réglages de Ganjalf",
  );
  assert.equal(
    rebrand("chat.x", "les réglages d’Unsloth"),
    "les réglages de Ganjalf",
  );
  assert.equal(
    rebrand("chat.x", "pendant qu'Unsloth démarre"),
    "pendant que Ganjalf démarre",
  );
});

test("credit lines keep the upstream name", () => {
  assert.equal(
    rebrand("chat.x", "made by the Unsloth team at Unsloth AI"),
    "made by the Unsloth team at Unsloth AI",
  );
  assert.equal(
    rebrand("chat.x", "an Unsloth AI project"),
    "an Unsloth AI project",
  );
  assert.equal(
    rebrand("settings.about.license", "Unsloth Studio is AGPL"),
    "Unsloth Studio is AGPL",
  );
});

test("the sidebar and desktop splash show the Ganjalf badge and word", () => {
  const sidebar = readSrc("components/app-sidebar.tsx");
  assert.match(sidebar, /src="\/favicon\.svg"\s+alt="Ganjalf"/);
  assert.match(sidebar, />\s*ganjalf\s*<\/span>/);
  assert.doesNotMatch(sidebar, /circle-logo-small\.png/);
  for (const file of [
    "components/tauri/startup-screen.tsx",
    "components/tauri/update-screen.tsx",
  ]) {
    const screen = readSrc(file);
    assert.match(screen, /src="\/favicon\.svg"/, file);
    assert.match(screen, />\s*ganjalf\s*<\/span>/, file);
  }
});

test("hardcoded status text names Ganjalf, while protocol and publisher names stay", () => {
  assert.match(readSrc("components/shutdown-dialog.tsx"), /Stop Ganjalf\?/);
  assert.match(readSrc("features/auth/api.ts"), /"X-Unsloth-Timezone"/);
  assert.match(readSrc("features/hub/lib/channels.ts"), /"Unsloth Trending"/);
  assert.match(readSrc("features/images/lib/image-metadata.ts"), /"Unsloth"/);
});

test("the busy mark is a book turning pages beside a smoking pipe, still under reduced motion", () => {
  const mark = readSrc("components/ganjalf-working-mark.tsx");
  assert.match(
    mark,
    /export type GanjalfWorkingMode = "thinking" \| "generating" \| "agent";/,
  );
  assert.match(mark, /className="gw-page gw-leaf"/);
  assert.match(mark, /\["gw-turn", "gw-turn gw-turn-late"\]/);
  assert.match(mark, /gw-puff gw-puff-3/);
  // Several marks can be on screen at once, so gradient ids are per instance.
  assert.match(mark, /useId\(\)/);
  const css = readSrc("ganjalf-theme.css");
  assert.match(css, /@keyframes gw-turn/);
  assert.match(css, /@keyframes gw-puff/);
  assert.match(
    css,
    /prefers-reduced-motion: reduce\)\s*\{\s*\.ganjalf-working \* \{\s*animation: none !important;/,
  );
});

test("thinking, generating and tool work all show the busy mark", () => {
  assert.match(
    readSrc("components/assistant-ui/reasoning.tsx"),
    /active \? <GanjalfWorkingMark mode="thinking"/,
  );
  assert.match(
    readSrc("components/assistant-ui/tool-group.tsx"),
    /<GanjalfWorkingMark mode="agent" label="Loading"/,
  );
  assert.match(
    readSrc("components/assistant-ui/tool-fallback.tsx"),
    /isRunning \? \(\s*<GanjalfWorkingMark mode="agent" label="Loading"/,
  );
  const thread = readSrc("components/assistant-ui/thread.tsx");
  const status = thread.slice(
    thread.indexOf("const GeneratingStatus"),
    thread.indexOf("const GeneratingStatusLabel"),
  );
  assert.match(
    status,
    /<GanjalfWorkingMark mode=\{agentic \? "agent" : "generating"\} \/>/,
  );
  assert.match(status, /part\.type === "tool-call"/);
});
