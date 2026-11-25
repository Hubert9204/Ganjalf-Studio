# SPDX-License-Identifier: AGPL-3.0-only
# Copyright 2026-present the Unsloth AI Inc. team. All rights reserved. See /studio/LICENSE.AGPL-3.0
"""Import skills from bare Markdown files or a loose set of files.

``import_skill_archive`` only understands ZIP files. A single ``SKILL.md``, several
files picked together, or a whole folder are turned into a ZIP in memory, so every
existing check (name, frontmatter, size, shadowing, duplicates) still runs through
the one import path.
"""

from __future__ import annotations

import io
import zipfile
from typing import Optional, Sequence

from core.inference.skills import (
    MAX_SKILL_ARCHIVE_BYTES,
    SkillError,
    _parse_skill_markdown,
)

_MARKDOWN_SUFFIXES = (".md", ".markdown")
_ZIP_SIGNATURES = (b"PK\x03\x04", b"PK\x05\x06")
_MANIFEST = "SKILL.md"
MAX_UPLOAD_FILES = 500


def looks_like_markdown_upload(filename: Optional[str], data: bytes) -> bool:
    """True for a Markdown file; a ZIP signature always wins over the file name."""
    if data[:4] in _ZIP_SIGNATURES:
        return False
    if (filename or "").lower().endswith(_MARKDOWN_SUFFIXES):
        return True
    # Extensionless uploads: the YAML frontmatter fence is the tell.
    return data.removeprefix(b"\xef\xbb\xbf")[:3] == b"---"


def _clean_path(raw: str) -> str:
    """Relative POSIX path for an uploaded name; anything that could escape is refused."""
    normalized = (raw or "").replace("\\", "/")
    parts = [part for part in normalized.split("/") if part not in ("", ".")]
    drive = bool(parts) and len(parts[0]) >= 2 and parts[0][1] == ":"
    if not parts or normalized.startswith("/") or drive or ".." in parts or "\x00" in normalized:
        raise SkillError(f"Unsafe file path: {raw!r}")
    return "/".join(parts)


def files_to_archive(items: Sequence[tuple[str, bytes]]) -> bytes:
    """ZIP with one folder per skill from ``(path, content)`` pairs.

    A skill is the folder holding a ``SKILL.md`` (folder uploads keep sub-folders).
    Loose files with no folder form one skill; the folder is named after the
    ``name`` in the manifest, not after the upload. Raises SkillError otherwise.
    """
    if not items:
        raise SkillError("No files were provided.")
    if len(items) > MAX_UPLOAD_FILES:
        raise SkillError(f"Too many files; the limit is {MAX_UPLOAD_FILES}.")
    if sum(len(data) for _, data in items) > MAX_SKILL_ARCHIVE_BYTES:
        raise SkillError("Skill files exceed the 20 MB limit.")

    files: dict[str, bytes] = {}
    for raw, data in items:
        path = _clean_path(raw)
        if path in files:
            raise SkillError(f"Duplicate file path: {path}")
        files[path] = data

    roots = sorted(
        path[: -len(_MANIFEST)]
        for path in files
        if path == _MANIFEST or path.endswith("/" + _MANIFEST)
    )
    if not roots:
        raise SkillError("No SKILL.md found among the selected files.")
    if "" in roots and len(roots) > 1:
        raise SkillError(
            "Several SKILL.md files without folders cannot be told apart; choose a folder or a ZIP."
        )

    names: dict[str, str] = {}
    for root in roots:
        name = _parse_skill_markdown(files[root + _MANIFEST])["name"]
        if name in names.values():
            raise SkillError(f"Two selected skills are both named {name!r}.")
        names[root] = name

    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, data in files.items():
            # Nested skills: the deepest folder holding a manifest owns the file.
            owner = max((root for root in roots if path.startswith(root)), key = len, default = None)
            if owner is None:
                continue
            info = zipfile.ZipInfo(f"{names[owner]}/{path[len(owner):]}")
            info.external_attr = 0o644 << 16
            archive.writestr(info, data, compress_type = zipfile.ZIP_DEFLATED)
    return output.getvalue()


def markdown_to_archive(data: bytes) -> bytes:
    """One-skill ZIP for a bare manifest; raises SkillError when it is not valid."""
    return files_to_archive([(_MANIFEST, data)])
