// SPDX-License-Identifier: AGPL-3.0-only
// Ganjalf: "always allow" rules per project (backend core/inference/permission_rules.py).

import { authFetch } from "@/features/auth";

export type ProjectRules = { commands: string[]; tools: string[] };

export type RuleSuggestion = ProjectRules & { project: string; suggested_prefix: string };

export async function suggestPermissionRule(
  sessionId: string,
  command: string,
): Promise<RuleSuggestion | null> {
  const query = new URLSearchParams({ session_id: sessionId, command });
  const response = await authFetch(`/api/inference/permission-rules?${query}`);
  if (!response.ok) return null;
  return (await response.json().catch(() => null)) as RuleSuggestion | null;
}

export async function addPermissionRule(
  sessionId: string,
  rule: { command_prefix?: string; tool?: string },
): Promise<void> {
  const response = await authFetch("/api/inference/permission-rules", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, ...rule }),
  });
  if (!response.ok) throw new Error(`Could not save the rule (${response.status})`);
}

export async function listAllPermissionRules(): Promise<Record<string, ProjectRules>> {
  const response = await authFetch("/api/inference/permission-rules/all");
  if (!response.ok) return {};
  const body = (await response.json().catch(() => null)) as { projects?: unknown } | null;
  return body && typeof body.projects === "object" && body.projects !== null
    ? (body.projects as Record<string, ProjectRules>)
    : {};
}

export async function removePermissionRule(
  project: string,
  rule: { command_prefix?: string; tool?: string },
): Promise<void> {
  const response = await authFetch("/api/inference/permission-rules/remove", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ project, ...rule }),
  });
  if (!response.ok) throw new Error(`Could not remove the rule (${response.status})`);
}

export { commandOf, projectLabel } from "../utils/permission-rule-labels.ts";
