# SPDX-License-Identifier: AGPL-3.0-only
# Copyright 2026-present the Unsloth AI Inc. team. All rights reserved. See /studio/LICENSE.AGPL-3.0

"""Where Ganjalf Studio looks for updates: its own GitHub repository, never Unsloth's PyPI package.

A Ganjalf install is a source tree (the launcher's checkout, or the Docker image's copy of it), so
"is there an update" means "is the branch on GitHub ahead of the commit this tree was built from".
That commit comes from GANJALF_STUDIO_REVISION, else the .ganjalf-revision file the Docker build and
unsloth-studio-update write (the image strips .git), else `git rev-parse HEAD`.

Environment:
  GANJALF_UPDATE_SOURCE=ganjalf  (default) check the Ganjalf repository
  GANJALF_UPDATE_SOURCE=unsloth  Unsloth's own PyPI check, as upstream Studio does
  GANJALF_UPDATE_SOURCE=off      no check (UNSLOTH_DISABLE_UPDATE_CHECK=1 also turns it off)
  GANJALF_UPDATE_REPO            owner/name or a github.com URL (default UNSLOTH_STUDIO_REPO, then
                                 Hubert9204/Ganjalf-Studio)
  GANJALF_UPDATE_BRANCH          branch to follow (default main)
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

DEFAULT_REPO = "Hubert9204/Ganjalf-Studio"
DEFAULT_BRANCH = "main"
REVISION_FILE = ".ganjalf-revision"
TIMEOUT_SECONDS = 4
SUCCESS_TTL_SECONDS = 6 * 60 * 60
FAILURE_TTL_SECONDS = 60 * 60
RESPONSE_MAX_BYTES = 2 * 1024 * 1024
# Folders only this fork has: they tell a Ganjalf tree from an upstream Unsloth checkout.
_MARKERS = ("studio/ganjalf_prompts", "studio/ganjalf_skills")
_SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")
_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_BRANCH_RE = re.compile(r"^[A-Za-z0-9._/-]{1,200}$")


def update_source() -> str:
    value = (os.environ.get("GANJALF_UPDATE_SOURCE") or "ganjalf").strip().lower()
    return value if value in ("ganjalf", "unsloth", "off") else "ganjalf"


def update_repo() -> str:
    """owner/name, from GANJALF_UPDATE_REPO (a github.com URL is accepted too)."""
    # The Docker image keeps the repo it was built from in UNSLOTH_STUDIO_REPO.
    raw = (os.environ.get("GANJALF_UPDATE_REPO") or os.environ.get("UNSLOTH_STUDIO_REPO") or "").strip()
    raw = re.sub(r"^(?:https?://)?(?:www\.)?github\.com/", "", raw).removesuffix(".git").strip("/")
    return raw if _REPO_RE.match(raw) else DEFAULT_REPO


def update_branch() -> str:
    raw = (os.environ.get("GANJALF_UPDATE_BRANCH") or "").strip()
    return raw if _BRANCH_RE.match(raw) and ".." not in raw else DEFAULT_BRANCH


def repo_url() -> str:
    return f"https://github.com/{update_repo()}"


def repo_root() -> Path:
    # ganjalf_update.py -> utils -> backend -> studio -> repo root
    return Path(__file__).resolve().parents[3]


def is_ganjalf_install(root: Optional[Path] = None) -> bool:
    base = root or repo_root()
    return any((base / marker).is_dir() for marker in _MARKERS)


def local_revision(root: Optional[Path] = None) -> Optional[str]:
    """The full commit this tree was built from, or None when nothing records it."""
    base = root or repo_root()
    candidates = [os.environ.get("GANJALF_STUDIO_REVISION") or ""]
    try:
        candidates.append((base / REVISION_FILE).read_text(encoding = "utf-8"))
    except OSError:
        pass
    for value in candidates:
        value = value.strip().lower()
        if _SHA_RE.match(value):
            return value
    if not (base / ".git").exists():
        return None
    try:
        out = subprocess.run(
            ["git", "-C", str(base), "rev-parse", "HEAD"],
            capture_output = True,
            text = True,
            timeout = 3,
            check = False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = out.stdout.strip().lower()
    return value if out.returncode == 0 and _SHA_RE.match(value) else None


def in_container() -> bool:
    return Path("/.dockerenv").exists() or bool(os.environ.get("UNSLOTH_STUDIO_APP"))


def update_command() -> str:
    """What to run to update this kind of install."""
    if in_container():
        return "docker exec <container> unsloth-studio-update"
    return "git pull && bash scripts/ganjalf-launch.sh"


@dataclass(frozen = True)
class GanjalfComparison:
    """How far the followed branch is ahead of this install. ahead_by None means unknown."""

    head: Optional[str]
    ahead_by: Optional[int]
    reason: Optional[str] = None
    error: Optional[str] = None


_cache_lock = threading.Lock()
_cache: dict[tuple[str, str, str], tuple[float, GanjalfComparison]] = {}


def reset_cache() -> None:
    with _cache_lock:
        _cache.clear()


def compare_with_branch(local: str) -> GanjalfComparison:
    """GitHub's compare of this install's commit with the followed branch, cached per triple."""
    key = (update_repo(), update_branch(), local)
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and hit[0] > now:
            return hit[1]
    try:
        result = _fetch_comparison(*key)
    except Exception:  # noqa: BLE001 -- offline is a state, not a failed request
        result = GanjalfComparison(
            head = None,
            ahead_by = None,
            reason = "offline",
            error = "Could not reach GitHub for Ganjalf updates.",
        )
    ttl = SUCCESS_TTL_SECONDS if result.ahead_by is not None else FAILURE_TTL_SECONDS
    with _cache_lock:
        _cache[key] = (time.monotonic() + ttl, result)
    return result


def compare_url(local: str) -> str:
    return f"{repo_url()}/compare/{local[:12]}...{update_branch()}"


def _fetch_comparison(repo: str, branch: str, local: str) -> GanjalfComparison:
    url = f"https://api.github.com/repos/{repo}/compare/{local}...{urllib.parse.quote(branch, safe = '/')}"
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "ganjalf-studio-update-check"}
    token = (os.environ.get("GITHUB_TOKEN") or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers = headers)
    try:
        with urllib.request.urlopen(request, timeout = TIMEOUT_SECONDS) as response:
            body = response.read(RESPONSE_MAX_BYTES + 1)
    except urllib.error.HTTPError as exc:
        # 404: the commit is not on GitHub (a local, unpushed one) or the repo/branch is wrong.
        reason = "unknown_revision" if exc.code == 404 else "offline"
        return GanjalfComparison(head = None, ahead_by = None, reason = reason, error = f"GitHub answered {exc.code}.")
    if len(body) > RESPONSE_MAX_BYTES:
        return GanjalfComparison(head = None, ahead_by = None, reason = "offline", error = "GitHub answer too large.")
    payload = json.loads(body.decode("utf-8"))
    ahead = payload.get("ahead_by") if isinstance(payload, dict) else None
    commits = payload.get("commits") if isinstance(payload, dict) else None
    head = None
    if isinstance(commits, list) and commits and isinstance(commits[-1], dict):
        head = commits[-1].get("sha")
    if not isinstance(ahead, int) or ahead < 0:
        return GanjalfComparison(head = None, ahead_by = None, reason = "offline", error = "Unexpected GitHub answer.")
    return GanjalfComparison(head = head if isinstance(head, str) else None, ahead_by = ahead)
