// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026-present the Unsloth AI Inc. team. All rights reserved. See /studio/LICENSE.AGPL-3.0

import { getAuthToken } from "@/features/auth";
import { apiUrl, isTauri } from "@/lib/api-base";
import { useCallback, useEffect, useState } from "react";

// Once per launch, no polling.
const WEB_UPDATE_CHECK_DELAY_MS = 5000;

// End-to-end override, absent in real browsers, so the banner layout suite need not wait the delay
// per boot. Read at mount, and deliberately not an env var baked into a build.
const E2E_DELAY_GLOBAL = "__unslothE2EWebUpdateDelayMs";

function overriddenDelayMs(): number | null {
  if (typeof window === "undefined") return null;
  const raw = (window as unknown as Record<string, unknown>)[E2E_DELAY_GLOBAL];
  const value = typeof raw === "number" ? raw : Number.NaN;
  return Number.isFinite(value) && value >= 0 ? value : null;
}
const DISMISS_PREFIX = "unsloth_web_update_dismissed";
const CAN_SHOW_KEY = "can_show_web_notification";
const UPDATE_AVAILABLE_KEY = "update_available";
const INSTALL_SOURCE_KEY = "install_source";
const LATEST_VERSION_KEY = "latest_version";
const CURRENT_VERSION_KEY = "current_version";
const CHECKED_AT_KEY = "checked_at";

type ApiObject = Record<string, unknown>;

export type WebUpdateInstallSource =
  | "pypi"
  | "ganjalf"
  | "editable"
  | "local_path"
  | "vcs"
  | "local_repo"
  | "unknown";

export interface WebUpdateStatus {
  currentVersion: string;
  latestVersion: string;
  /** "ganjalf": a source install following the Ganjalf-Studio repository, never Unsloth's PyPI. */
  installSource: "pypi" | "ganjalf";
  checkedAt: string;
  /** Ganjalf only: what to run, the GitHub page listing the new commits, how many there are. */
  updateCommand?: string;
  changesUrl?: string;
  commitsBehind?: number;
  branch?: string;
}

interface UseWebUpdateCheckOptions {
  enabled?: boolean;
  delayMs?: number;
}

function stringField(value: ApiObject, key: string): string | null {
  const field = value[key];
  return typeof field === "string" ? field : null;
}

export function toDisplayableUpdateStatus(
  value: unknown,
): WebUpdateStatus | null {
  if (!value || typeof value !== "object") {
    return null;
  }

  const status = value as ApiObject;
  const latestVersion = stringField(status, LATEST_VERSION_KEY);
  const currentVersion = stringField(status, CURRENT_VERSION_KEY);
  const checkedAt = stringField(status, CHECKED_AT_KEY);
  if (
    status[CAN_SHOW_KEY] !== true ||
    status[UPDATE_AVAILABLE_KEY] !== true ||
    (status[INSTALL_SOURCE_KEY] !== "pypi" &&
      status[INSTALL_SOURCE_KEY] !== "ganjalf") ||
    !latestVersion ||
    !currentVersion ||
    !checkedAt
  ) {
    return null;
  }

  if (status[INSTALL_SOURCE_KEY] === "ganjalf") {
    const updateCommand = stringField(status, "update_command");
    const changesUrl = stringField(status, "release_notes_url");
    const behind = status.commits_behind;
    return {
      currentVersion,
      latestVersion,
      installSource: "ganjalf",
      checkedAt,
      updateCommand: updateCommand ?? undefined,
      // Only a github.com page: the link opens in a new tab from the banner.
      changesUrl: changesUrl?.startsWith("https://github.com/") ? changesUrl : undefined,
      commitsBehind: typeof behind === "number" && behind > 0 ? behind : undefined,
      branch: stringField(status, "update_branch") ?? undefined,
    };
  }

  return {
    currentVersion,
    latestVersion,
    installSource: "pypi",
    checkedAt,
  };
}

function dismissalKey(status: WebUpdateStatus): string {
  return `${DISMISS_PREFIX}:${status.installSource}:${status.latestVersion}`;
}

function isDismissed(status: WebUpdateStatus): boolean {
  if (typeof window === "undefined") {
    return true;
  }
  try {
    return window.localStorage.getItem(dismissalKey(status)) !== null;
  } catch {
    return false;
  }
}

function markDismissed(status: WebUpdateStatus): void {
  if (typeof window === "undefined") {
    return;
  }
  try {
    window.localStorage.setItem(dismissalKey(status), String(Date.now()));
  } catch {
    // Ignore storage failures; the banner can still be dismissed in-memory.
  }
}

async function fetchDisplayableUpdateStatus(): Promise<WebUpdateStatus | null> {
  const token = getAuthToken();
  if (!token) {
    return null;
  }

  const headers = new Headers();
  headers.set("Authorization", `Bearer ${token}`);
  const res = await fetch(apiUrl("/api/studio/update-status"), { headers });
  if (!res.ok) {
    return null;
  }

  return toDisplayableUpdateStatus(await res.json());
}

export function useWebUpdateCheck({
  enabled = true,
  delayMs = WEB_UPDATE_CHECK_DELAY_MS,
}: UseWebUpdateCheckOptions = {}) {
  const [status, setStatus] = useState<WebUpdateStatus | null>(null);

  useEffect(() => {
    if (isTauri || !enabled || !getAuthToken()) {
      setStatus(null);
      return;
    }

    let canceled = false;
    const timer = window.setTimeout(() => {
      fetchDisplayableUpdateStatus()
        .then((next) => {
          if (!canceled && next && !isDismissed(next)) {
            setStatus(next);
          }
        })
        .catch(() => {});
      // Wins over delayMs too; the only caller passing one is a unit test not setting the global.
    }, overriddenDelayMs() ?? delayMs);

    return () => {
      canceled = true;
      window.clearTimeout(timer);
    };
  }, [delayMs, enabled]);

  // Silence this version for good.
  const dismiss = useCallback(() => {
    setStatus((current) => {
      if (current) {
        markDismissed(current);
      }
      return null;
    });
  }, []);

  // Hide without persisting: copying the command is not the same as having updated.
  const snooze = useCallback(() => {
    setStatus(null);
  }, []);

  return { status: enabled && !isTauri ? status : null, dismiss, snooze };
}
