// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026-present the Unsloth AI Inc. team. All rights reserved. See /studio/LICENSE.AGPL-3.0

import assert from "node:assert/strict";
import test from "node:test";
import {
  LIVE_ELSEWHERE_KEY,
  STREAM_HEARTBEAT_FRESH_MS,
  STREAM_HEARTBEAT_KEY,
  isLiveElsewhere,
  markLiveElsewhere,
  unmarkLiveElsewhere,
  withStreamHeartbeat,
} from "../src/features/chat/utils/remote-live-stream.ts";

const NOW = 1_800_000_000_000;
const streaming = {
  incomplete: { reason: "interrupted" },
  [STREAM_HEARTBEAT_KEY]: NOW - 5_000,
};

test("a provisional interrupted stamp with a fresh heartbeat is live elsewhere", () => {
  assert.equal(isLiveElsewhere(streaming, NOW), true);
});

test("a stale heartbeat reads as the interruption it is", () => {
  const stale = { ...streaming, [STREAM_HEARTBEAT_KEY]: NOW - STREAM_HEARTBEAT_FRESH_MS - 1 };
  assert.equal(isLiveElsewhere(stale, NOW), false);
});

test("no heartbeat, another reason, or a durable run never match", () => {
  assert.equal(isLiveElsewhere({ incomplete: { reason: "interrupted" } }, NOW), false);
  assert.equal(isLiveElsewhere({ ...streaming, incomplete: { reason: "cancelled" } }, NOW), false);
  assert.equal(isLiveElsewhere({ ...streaming, generationRunId: "run-1" }, NOW), false);
  assert.equal(isLiveElsewhere({ [STREAM_HEARTBEAT_KEY]: NOW }, NOW), false);
});

test("a clock ahead of this device still counts as fresh", () => {
  assert.equal(isLiveElsewhere({ ...streaming, [STREAM_HEARTBEAT_KEY]: NOW + 20_000 }, NOW), true);
});

test("the view marker round-trips back to the stored stamp", () => {
  const view = markLiveElsewhere(streaming);
  assert.equal(view.incomplete, undefined);
  assert.equal(view[LIVE_ELSEWHERE_KEY], true);
  assert.deepEqual(unmarkLiveElsewhere(view), streaming);
});

test("unmark leaves ordinary metadata untouched", () => {
  const custom = { incomplete: { reason: "length" } };
  assert.equal(unmarkLiveElsewhere(custom), custom);
});

test("withStreamHeartbeat stamps without dropping fields", () => {
  assert.deepEqual(withStreamHeartbeat({ a: 1 }, NOW), { a: 1, [STREAM_HEARTBEAT_KEY]: NOW });
});
