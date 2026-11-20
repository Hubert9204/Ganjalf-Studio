// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026-present the Unsloth AI Inc. team. All rights reserved. See /studio/LICENSE.AGPL-3.0

export type DroppedFile = { file: File; path: string };

// One more than the server accepts, so an oversized folder is refused rather than silently cut.
const MAX_DROPPED_FILES = 501;
const SKIPPED_FOLDERS = new Set(["node_modules", "__pycache__"]);

function skipped(name: string): boolean {
  return name.startsWith(".") || SKIPPED_FOLDERS.has(name);
}

async function readAllEntries(reader: FileSystemDirectoryReader): Promise<FileSystemEntry[]> {
  const all: FileSystemEntry[] = [];
  for (;;) {
    // readEntries returns the folder in batches until it yields an empty one.
    const batch = await new Promise<FileSystemEntry[]>((resolve, reject) =>
      reader.readEntries(resolve, reject),
    );
    if (batch.length === 0) return all;
    all.push(...batch);
  }
}

async function walk(entry: FileSystemEntry, out: DroppedFile[]): Promise<void> {
  if (out.length >= MAX_DROPPED_FILES || skipped(entry.name)) return;
  if (entry.isFile) {
    const file = await new Promise<File>((resolve, reject) =>
      (entry as FileSystemFileEntry).file(resolve, reject),
    );
    out.push({ file, path: entry.fullPath.replace(/^\/+/, "") });
    return;
  }
  if (entry.isDirectory) {
    const children = await readAllEntries((entry as FileSystemDirectoryEntry).createReader());
    for (const child of children) await walk(child, out);
  }
}

/**
 * Files from a drop, folders expanded with their relative paths ("skill/agents/a.md").
 * Call before the first await: the browser empties the DataTransfer once the event ends.
 */
export async function collectDroppedFiles(transfer: DataTransfer): Promise<DroppedFile[]> {
  const entries = Array.from(transfer.items ?? []).map((item) =>
    item.kind === "file" ? (item.webkitGetAsEntry?.() ?? null) : null,
  );
  if (!entries.some((entry) => entry !== null)) {
    return Array.from(transfer.files).map((file) => ({ file, path: file.name }));
  }
  const out: DroppedFile[] = [];
  for (const entry of entries) if (entry) await walk(entry, out);
  return out;
}
