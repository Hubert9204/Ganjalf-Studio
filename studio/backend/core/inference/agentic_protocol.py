# SPDX-License-Identifier: AGPL-3.0-only
# Copyright 2026-present the Unsloth AI Inc. team. All rights reserved. See /studio/LICENSE.AGPL-3.0

"""Ganjalf's agentic protocol: how to plan, call tools, handle failures and verify.

The text lives in studio/ganjalf_prompts/sections (core.md plus one addendum per model family), the
same files the copy-paste prompts there are built from. When local tools are on, the tool nudge
starts with it, so a chat needs no preset to get it.

Environment:
  GANJALF_AGENT_PROTOCOL=auto  (default) Qwen, Nemotron and Gemma models of 9B or more
  GANJALF_AGENT_PROTOCOL=all   every model of 9B or more, with the generic text for other families
  GANJALF_AGENT_PROTOCOL=off   never
  GANJALF_AGENT_PROTOCOL_DIR   another folder holding core.md and the addenda
"""

from __future__ import annotations

import logging
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# The first line of core.md; a system prompt that already holds it got the protocol from a preset.
PROTOCOL_MARKER = "# How you work"
# Small models get the compact tool nudge already, and this text would take a large share of it.
MIN_MODEL_SIZE_B = 9.0

_DEFAULT_PARTS_DIR = Path(__file__).resolve().parents[3] / "ganjalf_prompts" / "sections"
# Boundary-anchored so a path segment like "notqwen" or "gemmatic" does not match.
_FAMILY_PATTERNS = (
    ("qwen", re.compile(r"(?:^|[^a-z0-9])(?:qwen|qwq)")),
    ("nemotron", re.compile(r"(?:^|[^a-z0-9])nemotron")),
    ("gemma", re.compile(r"(?:^|[^a-z0-9])(?:med)?gemma")),
)
# Not chat models: speech, embedding and reranking checkpoints share these family names.
_NOT_CHAT_RE = re.compile(r"asr|tts|parakeet|embed|rerank|guard", re.IGNORECASE)


def protocol_mode() -> str:
    mode = (os.environ.get("GANJALF_AGENT_PROTOCOL") or "auto").strip().lower()
    if mode in ("0", "false", "no", "off", "none"):
        return "off"
    return mode if mode in ("auto", "all") else "auto"


def model_family(model_name: Optional[str]) -> Optional[str]:
    name = (model_name or "").lower()
    if not name or _NOT_CHAT_RE.search(name):
        return None
    for family, pattern in _FAMILY_PATTERNS:
        if pattern.search(name):
            return family
    return None


def _parts_dir() -> Path:
    override = (os.environ.get("GANJALF_AGENT_PROTOCOL_DIR") or "").strip()
    return Path(override).expanduser() if override else _DEFAULT_PARTS_DIR


@lru_cache(maxsize = 16)
def _render(parts_dir: str, family: Optional[str]) -> str:
    base = Path(parts_dir)
    try:
        pieces = [(base / "core.md").read_text(encoding = "utf-8").strip()]
        if family:
            addendum = base / f"{family}.md"
            if addendum.is_file():
                pieces.append(addendum.read_text(encoding = "utf-8").strip())
    except OSError as exc:
        # An install without the prompts folder keeps the plain nudge rather than failing the chat.
        logger.debug("Agentic protocol unavailable in %s: %s", base, exc)
        return ""
    return "\n\n".join(piece for piece in pieces if piece)


def agentic_protocol(model_name: Optional[str], model_size_b: Optional[float] = None) -> str:
    """The protocol text for this model, or "" when it does not apply."""
    mode = protocol_mode()
    if mode == "off":
        return ""
    if model_size_b is not None and model_size_b < MIN_MODEL_SIZE_B:
        return ""
    family = model_family(model_name)
    if family is None and mode != "all":
        return ""
    return _render(str(_parts_dir()), family)


def drop_repeated_protocol(system_prompt: Optional[str], nudge: str) -> str:
    """``nudge`` without the protocol when ``system_prompt`` already carries it (a pasted preset)."""
    if not nudge or not system_prompt or PROTOCOL_MARKER not in system_prompt:
        return nudge
    if not nudge.startswith(PROTOCOL_MARKER):
        return nudge
    # The protocol heads the nudge and holds no rule line, so the first one ends it (see with_protocol).
    _protocol, separator, rest = nudge.partition(_PROTOCOL_END)
    return rest if separator else ""


# A Markdown rule between the protocol and the tool tips: reads naturally and marks where to cut.
_PROTOCOL_END = "\n\n---\n\n"


def with_protocol(protocol: str, nudge: str) -> str:
    if not protocol:
        return nudge
    if not nudge:
        return protocol
    return protocol + _PROTOCOL_END + nudge
