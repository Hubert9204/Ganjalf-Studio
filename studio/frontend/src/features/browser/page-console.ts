// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026-present the Unsloth AI Inc. team. All rights reserved. See /studio/LICENSE.AGPL-3.0

// What a tab's page reported since it loaded (uncaught errors, console.error, requests the preview
// blocked), kept so the browser agent can show it to the model beside the page it reads. The page
// writes these, so the agent passes them on inside the untrusted-content fence.

export const PAGE_REPORTS_SHOWN = 12;
export const PAGE_REPORT_MAX_CHARS = 400;

type Reports = { load: string; lines: string[]; dropped: number; blocked: string[] };

const byTab = new Map<string, Reports>();

function clip(text: string): string {
  const flat = text.replace(/\s+/g, " ").trim();
  return flat.length > PAGE_REPORT_MAX_CHARS ? `${flat.slice(0, PAGE_REPORT_MAX_CHARS - 1)}…` : flat;
}

function reportsFor(tabId: string, load: string): Reports {
  const current = byTab.get(tabId);
  if (current && current.load === load) return current;
  const fresh: Reports = { load, lines: [], dropped: 0, blocked: [] };
  byTab.set(tabId, fresh);
  return fresh;
}

/** A new document in the tab: what the old one reported no longer applies. */
export function resetPageReports(tabId: string, load: string): void {
  byTab.set(tabId, { load, lines: [], dropped: 0, blocked: [] });
}

/** One report from the document `load` names; a report from a document already replaced is dropped. */
export function recordPageReport(tabId: string, load: string, line: string): void {
  const current = byTab.get(tabId);
  if (current && current.load !== load) return;
  const reports = reportsFor(tabId, load);
  const text = clip(line);
  if (!text) return;
  // A game loop throws the same error every frame; once is enough.
  if (reports.lines.includes(text)) return;
  if (reports.lines.length >= PAGE_REPORTS_SHOWN) {
    reports.dropped += 1;
    return;
  }
  reports.lines.push(text);
}

/** The whole set for a document, replacing what was kept (a preview recounts its own console). */
export function setPageReports(tabId: string, load: string, lines: readonly string[], blocked: readonly string[] = []): void {
  const unique = [...new Set(lines.map(clip).filter(Boolean))];
  byTab.set(tabId, {
    load,
    lines: unique.slice(0, PAGE_REPORTS_SHOWN),
    dropped: Math.max(0, unique.length - PAGE_REPORTS_SHOWN),
    blocked: [...new Set(blocked)].slice(0, PAGE_REPORTS_SHOWN),
  });
}

export function recordBlockedRequest(tabId: string, load: string, host: string): void {
  const current = byTab.get(tabId);
  if (current && current.load !== load) return;
  const reports = reportsFor(tabId, load);
  const name = clip(host);
  if (name && !reports.blocked.includes(name) && reports.blocked.length < PAGE_REPORTS_SHOWN) reports.blocked.push(name);
}

/** Lines for the model, or [] when the page reported nothing. */
export function pageReports(tabId: string): string[] {
  const reports = byTab.get(tabId);
  if (!reports) return [];
  const lines = [...reports.lines];
  if (reports.dropped > 0) lines.push(`(${reports.dropped} more not shown)`);
  if (reports.blocked.length > 0) lines.push(`Blocked requests (the preview has no network until the user allows it): ${reports.blocked.join(", ")}`);
  return lines;
}

export function forgetPageReports(tabId: string): void {
  byTab.delete(tabId);
}
