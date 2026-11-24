// SPDX-License-Identifier: AGPL-3.0-only
// Ganjalf: background terminal jobs the agent started (backend core/inference/background_jobs.py).

import { authFetch } from "@/features/auth";

export type BackgroundJob = {
  id: string;
  command: string;
  running: boolean;
  seconds: number;
  addresses: string[];
  status: string;
};

export async function listBackgroundJobs(): Promise<BackgroundJob[]> {
  const response = await authFetch("/api/inference/background-jobs");
  if (!response.ok) return [];
  const body = (await response.json().catch(() => null)) as { jobs?: unknown } | null;
  return Array.isArray(body?.jobs) ? (body.jobs as BackgroundJob[]) : [];
}

export async function stopBackgroundJob(id: string): Promise<void> {
  const response = await authFetch(`/api/inference/background-jobs/${encodeURIComponent(id)}/stop`, {
    method: "POST",
  });
  if (!response.ok) throw new Error(`Stop failed (${response.status})`);
}

/** "2 min", "1 h 5 min": how long a job has been running. */
export function jobAge(seconds: number): string {
  if (seconds < 60) return `${Math.max(0, Math.floor(seconds))} s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  return `${hours} h ${minutes % 60} min`;
}
