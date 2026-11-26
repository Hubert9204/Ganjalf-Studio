// SPDX-License-Identifier: AGPL-3.0-only
import assert from "node:assert/strict";
import test from "node:test";
import { parseSudoPrompt } from "../src/features/chat/sudo-prompt-store.ts";

test("a sudo password request is read off the stream, and a stale one is dropped", () => {
  const now = 1_000_000;
  assert.deepEqual(
    parseSudoPrompt(
      { id: "p1", session_id: "chat", command: "sudo dnf install curl", wrong: 1, expires_at: now + 5000 },
      now,
    ),
    { id: "p1", sessionId: "chat", command: "sudo dnf install curl", wrong: 1, expiresAt: now + 5000 },
  );
  assert.equal(parseSudoPrompt({ id: "p1", expires_at: now - 1 }, now), null);
  assert.equal(parseSudoPrompt({ command: "x" }, now), null);
  assert.equal(parseSudoPrompt(null, now), null);
});
