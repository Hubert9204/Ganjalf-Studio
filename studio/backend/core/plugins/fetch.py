# SPDX-License-Identifier: AGPL-3.0-only
# Copyright 2026-present the Unsloth AI Inc. team. All rights reserved. See /studio/LICENSE.AGPL-3.0

"""Getting a plugin or marketplace onto disk: GitHub archives, zip/tar URLs, git, local folders.

Archives are unpacked by hand: no links, devices, absolute paths or `..`, and size and count caps,
so a hostile archive can only fail to install.
"""

from __future__ import annotations

import io
import os
import re
import shutil
import stat
import subprocess
import tarfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Optional

MAX_ARCHIVE_BYTES = 200 * 1024 * 1024
MAX_UNPACKED_BYTES = 400 * 1024 * 1024
MAX_FILES = 20_000
DOWNLOAD_TIMEOUT_S = 120

_GITHUB_SHORT = re.compile(
    r"^(?P<owner>[A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))/(?P<repo>[A-Za-z0-9._-]{1,100})"
    r"(?P<path>(?:/[^@#\s]+)*?)(?:[@#](?P<ref>[^\s]+))?$"
)
_GITHUB_URL = re.compile(
    r"^https?://(?:www\.)?github\.com/(?P<owner>[A-Za-z0-9-]+)/(?P<repo>[A-Za-z0-9._-]+?)(?:\.git)?"
    r"(?:/(?:tree|blob)/(?P<ref>[^/#?]+)(?P<path>/[^#?]*)?)?/?(?:[#@](?P<fragment>[^\s]+))?$"
)


class FetchError(ValueError):
    pass


@dataclass
class Source:
    """Where a plugin or marketplace comes from; stored so it can be fetched again to update."""

    kind: str  # github | url | git | local
    owner: str = ""
    repo: str = ""
    ref: str = ""
    path: str = ""
    url: str = ""
    extra: dict = field(default_factory = dict)

    def to_dict(self) -> dict:
        data = {"kind": self.kind}
        for key in ("owner", "repo", "ref", "path", "url"):
            value = getattr(self, key)
            if value:
                data[key] = value
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "Source":
        return cls(
            **{
                key: str(data.get(key) or "")
                for key in ("kind", "owner", "repo", "ref", "path", "url")
            }
        )

    def label(self) -> str:
        if self.kind == "github":
            text = f"{self.owner}/{self.repo}{self.path and '/' + self.path.strip('/')}"
            return text + (f"@{self.ref}" if self.ref else "")
        return self.url


def _clean_subpath(path: str) -> str:
    parts = [part for part in PurePosixPath(path.strip("/")).parts if part not in ("", ".")]
    if any(part == ".." for part in parts):
        raise FetchError("The path inside the repository may not contain '..'.")
    return "/".join(parts)


def parse_source(text: str) -> Source:
    """`owner/repo`, `owner/repo/sub/dir@ref`, a github.com URL (also /tree/<ref>/<dir>), another
    git URL, a .zip/.tar.gz URL, or a folder on this machine."""
    value = (text or "").strip()
    if not value:
        raise FetchError("Give a GitHub repository (owner/repo), a URL or a folder.")
    match = _GITHUB_URL.match(value)
    if match:
        return Source(
            "github",
            owner = match["owner"],
            repo = match["repo"],
            ref = match["ref"] or match["fragment"] or "",
            path = _clean_subpath(match["path"] or ""),
        )
    lowered = value.lower()
    if lowered.startswith(("http://", "https://")):
        if lowered.split("?")[0].endswith((".zip", ".tar.gz", ".tgz", ".tar")):
            return Source("url", url = value)
        return Source("git", url = value)
    if lowered.startswith(("git@", "ssh://", "git://")):
        return Source("git", url = value)
    expanded = os.path.expanduser(value)
    if os.path.isabs(expanded) or value.startswith(("./", "../", "~")):
        return Source("local", url = os.path.realpath(expanded))
    match = _GITHUB_SHORT.match(value)
    if match:
        return Source(
            "github",
            owner = match["owner"],
            repo = match["repo"].removesuffix(".git"),
            ref = match["ref"] or "",
            path = _clean_subpath(match["path"] or ""),
        )
    raise FetchError(f"Not a GitHub repository, URL or folder: {value}")


def _github_headers() -> dict:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "ganjalf-studio-plugins"}
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _download(url: str, headers: Optional[dict] = None) -> bytes:
    import httpx
    try:
        with httpx.Client(
            follow_redirects = True, timeout = DOWNLOAD_TIMEOUT_S, headers = headers
        ) as client:
            with client.stream("GET", url) as response:
                if response.status_code == 404:
                    raise FetchError(f"Not found: {url} (a private repository needs GITHUB_TOKEN).")
                if response.status_code >= 400:
                    raise FetchError(f"Download failed ({response.status_code}): {url}")
                chunks, size = [], 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > MAX_ARCHIVE_BYTES:
                        raise FetchError("The download is larger than 200 MB.")
                    chunks.append(chunk)
                return b"".join(chunks)
    except httpx.HTTPError as exc:
        raise FetchError(f"Download failed: {exc}") from exc


def github_commit(
    owner: str,
    repo: str,
    ref: str = "",
) -> Optional[str]:
    """The commit a ref points at now, or None when GitHub can't say (offline, rate limit)."""
    import httpx

    headers = {**_github_headers(), "Accept": "application/vnd.github.sha"}
    try:
        response = httpx.get(
            f"https://api.github.com/repos/{owner}/{repo}/commits/{ref or 'HEAD'}",
            headers = headers,
            timeout = 20,
            follow_redirects = True,
        )
    except httpx.HTTPError:
        return None
    text = response.text.strip()
    return text if response.status_code == 200 and re.fullmatch(r"[0-9a-f]{40}", text) else None


def _safe_member(name: str) -> Optional[PurePosixPath]:
    path = PurePosixPath(name.replace("\\", "/"))
    if path.is_absolute() or any(part == ".." for part in path.parts):
        return None
    parts = [part for part in path.parts if part not in ("", ".")]
    return PurePosixPath(*parts) if parts else None


class _Budget:
    def __init__(self) -> None:
        self.files = 0
        self.bytes = 0

    def take(self, size: int) -> None:
        self.files += 1
        self.bytes += max(0, size)
        if self.files > MAX_FILES:
            raise FetchError(f"The archive has more than {MAX_FILES} files.")
        if self.bytes > MAX_UNPACKED_BYTES:
            raise FetchError("The archive unpacks to more than 400 MB.")


def _write(dest: Path, relative: PurePosixPath, data: bytes, executable: bool) -> None:
    target = dest.joinpath(*relative.parts)
    target.parent.mkdir(parents = True, exist_ok = True)
    target.write_bytes(data)
    if executable:
        target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def unpack(data: bytes, dest: Path) -> None:
    """A zip or (gzipped) tar into an empty `dest`; regular files and folders only."""
    dest.mkdir(parents = True, exist_ok = True)
    budget = _Budget()
    if data[:4] == b"PK\x03\x04":
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for info in archive.infolist():
                relative = _safe_member(info.filename)
                mode = (info.external_attr >> 16) & 0o170000
                if relative is None or info.is_dir() or mode in (stat.S_IFLNK,):
                    continue
                budget.take(info.file_size)
                _write(dest, relative, archive.read(info), bool((info.external_attr >> 16) & 0o111))
        return
    try:
        archive = tarfile.open(fileobj = io.BytesIO(data), mode = "r:*")
    except tarfile.TarError as exc:
        raise FetchError("The download is not a zip or tar archive.") from exc
    with archive:
        for member in archive:
            if not member.isfile():
                continue
            relative = _safe_member(member.name)
            if relative is None:
                continue
            budget.take(member.size)
            handle = archive.extractfile(member)
            if handle is None:
                continue
            _write(dest, relative, handle.read(), bool(member.mode & 0o111))


def _single_top_folder(root: Path) -> Path:
    """GitHub archives wrap everything in `owner-repo-sha/`."""
    entries = [
        entry
        for entry in root.iterdir()
        if not entry.name.startswith(".") or entry.name in (".claude-plugin",)
    ]
    if len(entries) == 1 and entries[0].is_dir() and entries[0].name != ".claude-plugin":
        return entries[0]
    return root


def copy_tree(source: Path, dest: Path) -> None:
    """A folder copied without links (a link could point anywhere), within the same caps."""
    budget = _Budget()
    source = source.resolve()
    for current, dirs, files in os.walk(source, followlinks = False):
        dirs[:] = [d for d in dirs if d != ".git" and not os.path.islink(os.path.join(current, d))]
        for name in files:
            path = os.path.join(current, name)
            if os.path.islink(path) or not os.path.isfile(path):
                continue
            relative = PurePosixPath(Path(path).relative_to(source).as_posix())
            size = os.path.getsize(path)
            budget.take(size)
            with open(path, "rb") as handle:
                _write(dest, relative, handle.read(), os.access(path, os.X_OK))


def _clone(url: str, ref: str, dest: Path) -> Optional[str]:
    command = ["git", "clone", "--depth", "1", "--quiet"]
    if ref and not re.fullmatch(r"[0-9a-f]{40}", ref):
        command += ["--branch", ref]
    try:
        subprocess.run(
            [*command, "--", url, str(dest)],
            check = True,
            capture_output = True,
            timeout = DOWNLOAD_TIMEOUT_S,
            env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
        return (
            subprocess.run(
                ["git", "-C", str(dest), "rev-parse", "HEAD"],
                capture_output = True,
                text = True,
                encoding = "utf-8",
                errors = "replace",
                timeout = 20,
            ).stdout.strip()
            or None
        )
    except (subprocess.SubprocessError, OSError) as exc:
        detail = getattr(exc, "stderr", b"") or b""
        raise FetchError(
            f"git clone failed: {detail.decode(errors = 'replace').strip() or exc}"
        ) from exc


def fetch(source: Source, dest: Path) -> dict:
    """Puts the source's files in `dest` (created, empty). Returns {"commit": sha or None}."""
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents = True)
    raw = dest / ".raw"
    commit: Optional[str] = None
    if source.kind == "github":
        try:
            if os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN"):
                ref = f"/{source.ref}" if source.ref else ""
                url = f"https://api.github.com/repos/{source.owner}/{source.repo}/tarball{ref}"
            else:
                # The archive link has no API rate limit.
                url = f"https://github.com/{source.owner}/{source.repo}/archive/{source.ref or 'HEAD'}.tar.gz"
            unpack(_download(url, _github_headers()), raw)
            top = _single_top_folder(raw)
            match = re.search(r"-([0-9a-f]{7,40})$", top.name)
            commit = github_commit(source.owner, source.repo, source.ref) or (
                match[1] if match else None
            )
        except FetchError:
            if not shutil.which("git"):
                raise
            shutil.rmtree(raw, ignore_errors = True)
            commit = _clone(f"https://github.com/{source.owner}/{source.repo}.git", source.ref, raw)
            top = raw
        root = top / source.path if source.path else top
    elif source.kind == "url":
        unpack(_download(source.url), raw)
        root = _single_top_folder(raw)
    elif source.kind == "git":
        if not shutil.which("git"):
            raise FetchError("This address needs git, which is not installed.")
        commit = _clone(source.url, source.ref, raw)
        root = raw / source.path if source.path else raw
    elif source.kind == "local":
        folder = Path(source.url)
        if not folder.is_dir():
            raise FetchError(f"No such folder: {source.url}")
        copy_tree(folder, raw)
        root = raw
    else:
        raise FetchError(f"Unknown source kind {source.kind!r}.")
    if not root.is_dir():
        raise FetchError(f"The repository has no folder {source.path!r}.")
    content = dest / "content"
    if root.resolve() == raw.resolve():
        raw.rename(content)
    else:
        root.rename(content)
        shutil.rmtree(raw, ignore_errors = True)
    shutil.rmtree(content / ".git", ignore_errors = True)
    return {"commit": commit}
