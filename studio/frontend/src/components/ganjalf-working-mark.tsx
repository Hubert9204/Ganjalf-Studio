// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026-present the Unsloth AI Inc. team. All rights reserved. See /studio/LICENSE.AGPL-3.0

import { cn } from "@/lib/utils";
import { useId } from "react";

export type GanjalfWorkingMode = "thinking" | "generating" | "agent";

type GanjalfWorkingMarkProps = {
  /** Thinking turns pages slowly, generating quickly; agent work puffs the pipe harder. */
  mode: GanjalfWorkingMode;
  className?: string;
  /** Announced as a status (like Spinner's label); without it the mark is decorative. */
  label?: string;
};

/**
 * Ganjalf's busy mark: an open book whose pages turn beside a smoking pipe, in the colours of
 * the hat-and-pipe logo (public/favicon.svg). Pure SVG + CSS (ganjalf-theme.css), so it costs
 * no script per frame; prefers-reduced-motion shows a still frame.
 */
export function GanjalfWorkingMark({
  mode,
  className,
  label,
}: GanjalfWorkingMarkProps) {
  // Gradient ids must be unique per instance: several marks can be on screen at once.
  const cover = `gw-cover-${useId().replace(/[^a-zA-Z0-9_-]/g, "")}`;
  return (
    <svg
      viewBox="0 0 48 32"
      data-slot="ganjalf-working"
      data-mode={mode}
      className={cn("ganjalf-working", className)}
      focusable="false"
      role={label ? "status" : "img"}
      aria-label={label}
      aria-hidden={label ? undefined : true}
    >
      {label ? <title>{label}</title> : null}
      <defs>
        <linearGradient id={cover} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#3f6bc9" />
          <stop offset="1" stopColor="#2f57b5" />
        </linearGradient>
      </defs>
      {/* Book: cover, the two resting pages with their lines, the spine. */}
      <path
        d="M2 10.5Q10 8 18 11Q26 8 34 10.5V27.2Q26 24.7 18 27.7Q10 24.7 2 27.2Z"
        fill={`url(#${cover})`}
      />
      <path className="gw-page" d="M18 10Q11 6.8 3.5 8.6V25Q11 23.3 18 26Z" />
      <path className="gw-page" d="M18 10Q25 6.8 32.5 8.6V25Q25 23.3 18 26Z" />
      <path
        className="gw-lines"
        d="M6.2 12.6Q10.5 11.4 15.2 12.9M6.2 15.6Q10.5 14.4 15.2 15.9M6.2 18.6Q10.5 17.4 15.2 18.9M20.8 12.9Q25.5 11.4 29.8 12.6M20.8 15.9Q25.5 14.4 29.8 15.6M20.8 18.9Q25.5 17.4 29.8 18.6"
      />
      {/* Two printed leaves turning half a cycle apart, hinged on the spine. A leaf mirrored
          onto the left matches the resting left page, so the loop has no visible seam. */}
      {["gw-turn", "gw-turn gw-turn-late"].map((turn) => (
        <g key={turn} className={turn}>
          <path
            className="gw-page gw-leaf"
            d="M18 10Q25 6.8 32.5 8.6V25Q25 23.3 18 26Z"
          />
          <path
            className="gw-lines"
            d="M20.8 12.9Q25.5 11.4 29.8 12.6M20.8 15.9Q25.5 14.4 29.8 15.6M20.8 18.9Q25.5 17.4 29.8 18.6"
          />
        </g>
      ))}
      <path className="gw-spine" d="M18 10V26" />
      {/* Pipe resting against the book, as in the logo: stem, bowl, rim, glowing tobacco. */}
      <path className="gw-stem" d="M38.8 23.4Q35.6 27.6 30.6 28.3" />
      <path className="gw-mouthpiece" d="M31.8 28.2L30.4 28.3" />
      <path d="M37.6 17.6H45.4L44.7 24.4Q41.5 27.4 38.3 24.4Z" fill="#8b97a8" />
      <rect x="37" y="16.4" width="9" height="2.1" rx="1.05" fill="#6b778a" />
      <ellipse cx="41.5" cy="17" rx="3.3" ry="0.75" fill="#454f60" />
      <ellipse className="gw-ember" cx="41.5" cy="17" rx="2.2" ry="0.45" />
      {/* Smoke: a drifting wisp and three puffs rising one after another. */}
      <path
        className="gw-wisp"
        d="M41.6 15.2C39.6 12.7 43.6 11.2 41.6 8.7C40.3 7 42.7 5.7 42.1 3.6"
      />
      <circle className="gw-puff gw-puff-1" cx="41.6" cy="14.4" r="1.7" />
      <circle className="gw-puff gw-puff-2" cx="41.6" cy="14.4" r="2.1" />
      <circle className="gw-puff gw-puff-3" cx="41.6" cy="14.4" r="1.5" />
    </svg>
  );
}
