// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026-present the Unsloth AI Inc. team. All rights reserved. See /studio/LICENSE.AGPL-3.0

// Plugins in Claude Code's format (backend routes/plugins.py): preview, install, switch, update.

import { authFetch } from "@/features/auth";
import { listSkills } from "./skills-api";

import type { InstalledPlugin, Marketplace, PluginContents, PluginPreview } from "./plugins-types";

export type { InstalledPlugin, Marketplace, PluginContents, PluginHookGroup, PluginPreview } from "./plugins-types";
export { pluginCommands } from "./plugins-types";

async function parse<T>(response: Response): Promise<T> {
  if (response.status === 204) return undefined as T;
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const detail =
      body && typeof body === "object" && "detail" in body ? String(body.detail) : `Request failed (${response.status})`;
    throw new Error(detail);
  }
  return body as T;
}

function json(method: string, body?: unknown): RequestInit {
  return body === undefined
    ? { method }
    : { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
}

// Skills, commands and agents come and go with plugins: refresh the skill catalog after a change.
async function changed<T>(value: Promise<T>): Promise<T> {
  const result = await value;
  void listSkills(true).catch(() => undefined);
  return result;
}

export async function listPlugins(): Promise<{ plugins: InstalledPlugin[]; marketplaces: Marketplace[] }> {
  return parse(await authFetch("/api/plugins"));
}

export async function previewPlugin(source: string): Promise<PluginPreview> {
  return parse(await authFetch("/api/plugins/preview", json("POST", { source })));
}

export async function uploadPlugin(file: File): Promise<PluginPreview> {
  const form = new FormData();
  form.append("file", file);
  return parse(await authFetch("/api/plugins/upload", { method: "POST", body: form }));
}

export function installPlugin(token: string, enableHooks: boolean): Promise<InstalledPlugin> {
  return changed(authFetch("/api/plugins/install", json("POST", { token, enable_hooks: enableHooks })).then(parse<InstalledPlugin>));
}

export function setPluginEnabled(name: string, enabled: boolean): Promise<InstalledPlugin> {
  return changed(authFetch(`/api/plugins/${encodeURIComponent(name)}/enabled`, json("PUT", { enabled })).then(parse<InstalledPlugin>));
}

export async function setPluginHooks(name: string, enabled: boolean): Promise<InstalledPlugin> {
  return parse(await authFetch(`/api/plugins/${encodeURIComponent(name)}/hooks`, json("PUT", { enabled })));
}

export function updatePlugin(name: string): Promise<InstalledPlugin> {
  return changed(authFetch(`/api/plugins/${encodeURIComponent(name)}/update`, json("POST")).then(parse<InstalledPlugin>));
}

export function removePlugin(name: string): Promise<void> {
  return changed(authFetch(`/api/plugins/${encodeURIComponent(name)}`, json("DELETE")).then(parse<void>));
}

export async function pluginDetails(name: string): Promise<InstalledPlugin & { contents: PluginContents }> {
  return parse(await authFetch(`/api/plugins/${encodeURIComponent(name)}`));
}

export async function checkPluginUpdates(): Promise<Record<string, boolean>> {
  return parse(await authFetch("/api/plugins/updates"));
}

export async function addMarketplace(source: string): Promise<Marketplace> {
  return parse(await authFetch("/api/plugins/marketplaces", json("POST", { source })));
}

export async function refreshMarketplace(name: string): Promise<Marketplace> {
  return parse(await authFetch(`/api/plugins/marketplaces/${encodeURIComponent(name)}/refresh`, json("POST")));
}

export async function removeMarketplace(name: string): Promise<void> {
  return parse(await authFetch(`/api/plugins/marketplaces/${encodeURIComponent(name)}`, json("DELETE")));
}
