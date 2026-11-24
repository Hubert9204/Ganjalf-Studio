// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026-present the Unsloth AI Inc. team. All rights reserved. See /studio/LICENSE.AGPL-3.0

// Plugins: their commands are called with /name, the preview spells out what runs on the machine,
// and the Skills window has a section and a way into the Plugins window.

import assert from "node:assert/strict";
import test from "node:test";

import { readSrc, registerBundlerResolver } from "./helpers/kit.ts";

registerBundlerResolver();
const { skillToolNames } = await import("../src/features/chat/api/skill-tools.ts");
const { pluginCommands } = await import("../src/features/chat/api/plugins-types.ts");

const command = { name: "demo-hello", valid: true, shadowed: false, enabled: true };

test("a /command typed first reads its skill even with Code off", () => {
  assert.deepEqual(skillToolNames([command], false, ["/demo-hello Ann"]), ["read_skill"]);
  assert.deepEqual(skillToolNames([command], false, ["say /demo-hello"]), []);
  assert.deepEqual(skillToolNames([command], false, ["/demo-hello/x"]), []);
});

test("the preview lists every command a hook or a local MCP server would run", () => {
  const lines = pluginCommands({
    name: "demo",
    display_name: "demo",
    version: "",
    description: "",
    author: "",
    homepage: "",
    license: "",
    skills: [],
    commands: [],
    agents: [],
    hooks: { PreToolUse: [{ matcher: "Bash", hooks: [{ command: "python3 guard.py" }] }] },
    mcp_servers: { local: { command: "npx", args: ["-y", "server"] }, remote: { url: "https://example.com/mcp" } },
    unsupported: [],
    warnings: [],
  });
  assert.deepEqual(lines, ["PreToolUse (Bash): python3 guard.py", "MCP local: npx -y server"]);
});

test("the Skills window shows plugin skills and opens Plugins", () => {
  const dialog = readSrc("features/chat/components/chat-skills-dialog.tsx");
  assert.match(dialog, /\["agents", "claude", "plugin", "bundled"\]/);
  assert.match(dialog, /<PluginsDialog open=\{pluginsOpen\} onOpenChange=\{setPluginsOpen\} \/>/);
  const plugins = readSrc("features/chat/components/plugins-dialog.tsx");
  assert.match(plugins, /t\("plugins\.runsCommands"\)/);
  assert.match(plugins, /t\("plugins\.enableHooksNow"\)/);
});
