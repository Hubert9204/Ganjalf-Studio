# SPDX-License-Identifier: AGPL-3.0-only
# Copyright 2026-present the Unsloth AI Inc. team. All rights reserved. See /studio/LICENSE.AGPL-3.0
"""Import a bare ``SKILL.md`` upload by wrapping it into the archive format.

``import_skill_archive`` only understands ZIP files. A single Markdown skill is turned
into a one-folder ZIP in memory, so every existing check (name, frontmatter, size,
shadowing, duplicate detection) still runs through the one import path.
"""

from __future__ import annotations

import io
import zipfile
from typing import Optional

from core.inference.skills import SkillError, _parse_skill_markdown

_MARKDOWN_SUFFIXES = (".md", ".markdown")
_ZIP_SIGNATURES = (b"PK\x03\x04", b"PK\x05\x06")


def looks_like_markdown_upload(filename: Optional[str], data: bytes) -> bool:
    """True for a Markdown file; a ZIP signature always wins over the file name."""
    if data[:4] in _ZIP_SIGNATURES:
        return False
    if (filename or "").lower().endswith(_MARKDOWN_SUFFIXES):
        return True
    # Extensionless uploads: the YAML frontmatter fence is the tell.
    return data.removeprefix(b"\xef\xbb\xbf")[:3] == b"---"


def markdown_to_archive(data: bytes) -> bytes:
    """One-skill ZIP for ``data``; raises SkillError when the manifest is not valid."""
    metadata = _parse_skill_markdown(data)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        info = zipfile.ZipInfo(f"{metadata['name']}/SKILL.md")
        info.external_attr = 0o644 << 16
        archive.writestr(info, data, compress_type = zipfile.ZIP_DEFLATED)
    return output.getvalue()
