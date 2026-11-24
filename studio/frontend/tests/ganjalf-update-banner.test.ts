// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026-present the Unsloth AI Inc. team. All rights reserved. See /studio/LICENSE.AGPL-3.0

// A Ganjalf install is offered updates from the Ganjalf-Studio repository, with its own command.

import assert from "node:assert/strict";
import test from "node:test";

import { installLocalStorageFake, readSrc, registerBundlerResolver } from "./helpers/kit.ts";
import { loadWithStubs } from "./helpers/module-stubs.ts";

registerBundlerResolver();
installLocalStorageFake();
const { toDisplayableUpdateStatus } = loadWithStubs<{
  toDisplayableUpdateStatus: (value: unknown) => Record<string, unknown> | null;
}>(new URL("../src/hooks/use-web-update-check.ts", import.meta.url), {
  "@/features/auth": { getAuthToken: () => null },
  "@/lib/api-base": { apiUrl: (path: string) => path, isTauri: false },
  react: { useCallback: (fn: unknown) => fn, useEffect: () => undefined, useState: (v: unknown) => [v, () => undefined] },
});

const ganjalf = {
  can_show_web_notification: true,
  update_available: true,
  install_source: "ganjalf",
  current_version: "aaaaaaa",
  latest_version: "bbbbbbb",
  checked_at: "2026-11-24T00:00:00Z",
  update_command: "docker exec <container> unsloth-studio-update",
  release_notes_url: "https://github.com/Hubert9204/Ganjalf-Studio/compare/aaaaaaaaaaaa...main",
  commits_behind: 4,
  update_branch: "main",
};

test("a Ganjalf status carries its command, its changes page and the commit count", () => {
  assert.deepEqual(toDisplayableUpdateStatus(ganjalf), {
    currentVersion: "aaaaaaa",
    latestVersion: "bbbbbbb",
    installSource: "ganjalf",
    checkedAt: "2026-11-24T00:00:00Z",
    updateCommand: "docker exec <container> unsloth-studio-update",
    changesUrl: "https://github.com/Hubert9204/Ganjalf-Studio/compare/aaaaaaaaaaaa...main",
    commitsBehind: 4,
    branch: "main",
  });
});

test("only a github.com page becomes the changes link", () => {
  const status = toDisplayableUpdateStatus({ ...ganjalf, release_notes_url: "https://evil.example/x" });
  assert.equal(status?.changesUrl, undefined);
});

test("nothing shows when the branch has no new commits", () => {
  assert.equal(
    toDisplayableUpdateStatus({ ...ganjalf, update_available: false, can_show_web_notification: false }),
    null,
  );
});

test("the banner copies the Ganjalf command and links the changes instead of Unsloth's notes", () => {
  const banner = readSrc("components/web/update-banner.tsx");
  assert.match(banner, /isGanjalf && status\?\.updateCommand\s*\?\s*status\.updateCommand/);
  assert.match(banner, /\{isGanjalf \? null : \(\s*<ReleaseNotesPanel/);
  assert.match(banner, /data-testid="web-update-changes-link"/);
});
