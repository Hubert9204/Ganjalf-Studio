// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026-present the Unsloth AI Inc. team. All rights reserved. See /studio/LICENSE.AGPL-3.0

import type { ComponentProps } from "react";

const LEADING_SLASH = /^\//;

// Resolve against the deploy base (subpath mounts) and encode spaced filenames.
export function publicAssetUrl(path: string): string {
  return encodeURI(import.meta.env.BASE_URL + path.replace(LEADING_SLASH, ""));
}

// Ganjalf Studio's own mascot, a blue wizard hat with a grey pipe. Inline, so it can never 404.
const MASCOT_SVG = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><defs><linearGradient id="h" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#7aa5f5"/><stop offset="1" stop-color="#2f57b5"/></linearGradient></defs><path d="M33 7C35 21 42 33 47 45H17C22 33 29 21 33 7Z" fill="url(#h)"/><ellipse cx="32" cy="46" rx="21" ry="5.5" fill="#3f6bc9"/><path d="M23.5 38.5Q32 42 41 38.5L42.6 43Q32 46.5 21.8 43Z" fill="#cfd8e6"/><path d="M49.5 43C46.5 40 52.5 38 49.5 34C47.5 31 51.5 29 50.5 26" fill="none" stroke="#dbe4f3" stroke-opacity=".75" stroke-width="1.6" stroke-linecap="round"/><path d="M45.5 52.5Q40 58.5 32.5 58" fill="none" stroke="#aab4c3" stroke-width="2.3" stroke-linecap="round"/><path d="M34 58.1L32.5 58" fill="none" stroke="#6b778a" stroke-width="3" stroke-linecap="round"/><g transform="rotate(-16 50 54)"><path d="M44.5 45.5H56L55 54Q50.2 58 45.5 54Z" fill="#8b97a8"/><rect x="43.6" y="44" width="13.3" height="2.8" rx="1.4" fill="#6b778a"/><ellipse cx="50.2" cy="44.7" rx="4.6" ry="1" fill="#454f60"/></g></svg>`;
const MASCOT_SRC = `data:image/svg+xml;utf8,${encodeURIComponent(MASCOT_SVG)}`;

type MascotImgProps = { src: string } & Omit<
  ComponentProps<"img">,
  "src" | "onError"
>;

// Every place the app shows a mascot goes through this component, so one swap covers them all.
// Callers still pass the Unsloth sticker they used to show; that path is ignored. Empty alt by default.
export function MascotImg(props: MascotImgProps) {
  return (
    <img draggable={false} {...props} src={MASCOT_SRC} alt={props.alt ?? ""} />
  );
}
