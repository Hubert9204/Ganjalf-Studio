// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026-present the Unsloth AI Inc. team. All rights reserved. See /studio/LICENSE.AGPL-3.0

/**
 * A legacy (subscriber-owned) stream - a turn with an attachment, a browser tool, an incognito
 * thread - persists only through the owning tab's periodic checkpoints, and every streamed yield
 * carries the provisional `interrupted` stamp so a closed tab still reads as interrupted. Another
 * device opening the chat mid-run used to read that stamp as a failure: red "An error occurred"
 * box, Retry and Continue, which start a second generation over the live one.
 *
 * The owning tab now stamps each checkpoint with `streamHeartbeatAt`. A reader that finds the
 * `interrupted` stamp next to a fresh heartbeat shows the reply as generating on another device
 * (`liveElsewhere`) instead. The marker is view-only: it is swapped back to the original stamp
 * before any save, so storage never holds it.
 */

export const STREAM_HEARTBEAT_KEY = "streamHeartbeatAt";
export const LIVE_ELSEWHERE_KEY = "liveElsewhere";

/** Checkpoints land every few seconds; a hidden owner tab is throttled to about one a minute. */
export const STREAM_HEARTBEAT_FRESH_MS = 90_000;

type Custom = Record<string, unknown>;

export function streamHeartbeatAt(custom: Custom | undefined): number | null {
  const at = custom?.[STREAM_HEARTBEAT_KEY];
  return typeof at === "number" && Number.isFinite(at) ? at : null;
}

/** Fresh in both directions: the stamp comes from another device's clock. */
export function streamHeartbeatIsFresh(
  custom: Custom | undefined,
  now: number = Date.now(),
): boolean {
  const at = streamHeartbeatAt(custom);
  return at !== null && Math.abs(now - at) < STREAM_HEARTBEAT_FRESH_MS;
}

/** A stored reply another tab is still streaming on the legacy path. Durable runs have their own
 *  follower (generationRunId), so they never match. */
export function isLiveElsewhere(
  custom: Custom | undefined,
  now: number = Date.now(),
): boolean {
  if (!custom || typeof custom.generationRunId === "string") return false;
  const incomplete = custom.incomplete as { reason?: unknown } | undefined;
  return incomplete?.reason === "interrupted" && streamHeartbeatIsFresh(custom, now);
}

/** View copy: drops the provisional stamp (no error box, no Continue) and flags the reply. */
export function markLiveElsewhere(custom: Custom): Custom {
  const view: Custom = { ...custom, [LIVE_ELSEWHERE_KEY]: true };
  delete view.incomplete;
  return view;
}

/** Storage copy: restores the stamp the owning tab wrote, so a save from this view changes nothing. */
export function unmarkLiveElsewhere(custom: Custom): Custom {
  if (custom[LIVE_ELSEWHERE_KEY] !== true) return custom;
  const stored: Custom = { ...custom, incomplete: { reason: "interrupted" } };
  delete stored[LIVE_ELSEWHERE_KEY];
  return stored;
}

export function withStreamHeartbeat(custom: Custom, now: number = Date.now()): Custom {
  return { ...custom, [STREAM_HEARTBEAT_KEY]: now };
}

/** A stored reply's metadata as the view shows it: the same mapping toThreadMessage applies. */
export function liveViewOfStored(stored: Custom | undefined, now: number = Date.now()): Custom {
  const custom = stored ?? {};
  return isLiveElsewhere(custom, now) ? markLiveElsewhere(custom) : custom;
}

/** Carries the stored reply's live-elsewhere state and heartbeat onto the view's metadata. */
export function carryLiveElsewhere(view: Custom, storedView: Custom): Custom {
  const next: Custom = { ...view };
  if (storedView[LIVE_ELSEWHERE_KEY] === true) {
    next[LIVE_ELSEWHERE_KEY] = true;
    delete next.incomplete;
  } else {
    delete next[LIVE_ELSEWHERE_KEY];
  }
  const at = streamHeartbeatAt(storedView);
  if (at !== null) next[STREAM_HEARTBEAT_KEY] = at;
  return next;
}
