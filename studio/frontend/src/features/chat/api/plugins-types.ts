// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026-present the Unsloth AI Inc. team. All rights reserved. See /studio/LICENSE.AGPL-3.0

// Shapes of backend routes/plugins.py answers, and what a plugin would run on this machine.

export type PluginHookGroup = { matcher: string; hooks: { command: string; timeout?: number; if?: string }[] };

export type PluginContents = {
  name: string;
  display_name: string;
  version: string;
  description: string;
  author: string;
  homepage: string;
  license: string;
  skills: { name: string; path: string; description: string }[];
  commands: { name: string; description: string; argument_hint?: string }[];
  agents: { name: string; description: string; tools?: string[]; model?: string }[];
  hooks: Record<string, PluginHookGroup[]>;
  mcp_servers: Record<string, { command?: string; args?: string[]; url?: string; type?: string }>;
  unsupported: string[];
  warnings: string[];
  installed?: boolean;
  installed_version?: string | null;
};

export type InstalledPlugin = {
  name: string;
  display_name: string;
  version: string;
  description: string;
  author: string;
  homepage: string;
  source: { kind: string; owner?: string; repo?: string; ref?: string; path?: string; url?: string } | null;
  marketplace: string | null;
  enabled: boolean;
  hooks_enabled: boolean;
  skills: string[];
  commands: string[];
  agents: string[];
  hook_events: string[];
  mcp_servers: string[];
  mcp_server_count: number;
  unsupported: string[];
  warnings: string[];
  installed_at: string;
  updated_at: string;
};

export type Marketplace = {
  name: string;
  owner: string;
  description: string;
  plugins: { name: string; description: string; version: string; category: string; installed: boolean }[];
};

export type PluginPreview =
  | { kind: "plugin"; token: string; plugin: PluginContents }
  | { kind: "marketplace"; marketplace: Marketplace };

/** A hook or stdio MCP server runs commands on this machine: the preview spells them out. */
export function pluginCommands(contents: PluginContents): string[] {
  const commands: string[] = [];
  for (const [event, groups] of Object.entries(contents.hooks)) {
    for (const group of groups) {
      for (const hook of group.hooks) commands.push(`${event}${group.matcher ? ` (${group.matcher})` : ""}: ${hook.command}`);
    }
  }
  for (const [name, server] of Object.entries(contents.mcp_servers)) {
    if (server.command) commands.push(`MCP ${name}: ${[server.command, ...(server.args ?? [])].join(" ")}`);
  }
  return commands;
}
