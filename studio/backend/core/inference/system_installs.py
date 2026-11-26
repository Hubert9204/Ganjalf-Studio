# SPDX-License-Identifier: AGPL-3.0-only
"""Ganjalf: before a system install runs, look whether the tools are already on this computer.

A model that wants curl tends to install it whatever the machine has. A command that is only an
install (``sudo dnf install -y curl``, ``apt-get install wget``, ``pacman -S git``...) is not run
when every name in it is already a command on PATH or an installed package; the model is told
where it is instead, and no password is asked for.
"""

from __future__ import annotations

import shlex
import shutil
import subprocess
import time
from typing import Optional

_MANAGERS = {
    "dnf": ("install",),
    "dnf5": ("install",),
    "yum": ("install",),
    "microdnf": ("install",),
    "apt": ("install",),
    "apt-get": ("install",),
    "zypper": ("install", "in"),
    "apk": ("add",),
}
_SHELL_MARKS = set(";&|`$()<>\n")
_CACHE: dict[str, tuple[float, str]] = {}
_CACHE_S = 30.0


def install_targets(command) -> Optional[list[str]]:
    """The package names when the whole command is one install, else None."""
    if not isinstance(command, str) or any(mark in command for mark in _SHELL_MARKS):
        return None
    try:
        words = shlex.split(command)
    except ValueError:
        return None
    while words and words[0] in ("sudo", "doas", "run0"):
        words = words[1:]
        while words and words[0].startswith("-"):
            words = words[1:]
    if len(words) < 2:
        return None
    manager, rest = words[0].rsplit("/", 1)[-1], words[1:]
    if manager == "pacman":
        short = [w for w in rest if w.startswith("-") and not w.startswith("--")]
        if not short or not all(
            f.startswith("-S") and not set(f[2:]) & set("sicglp") for f in short
        ):
            return None
        names = [w for w in rest if not w.startswith("-")]
    elif manager in _MANAGERS:
        verbs = [w for w in rest if not w.startswith("-")]
        if not verbs or verbs[0] not in _MANAGERS[manager]:
            return None
        names = verbs[1:]
    else:
        return None
    if not names or any(name.startswith("@") or "/" in name for name in names):
        return None
    return names


def _package_installed(name: str) -> bool:
    for argv in (
        ["rpm", "-q", "--whatprovides", name],
        ["dpkg-query", "-W", "-f=${Status}", name],
        ["pacman", "-Q", name],
        ["apk", "info", "-e", name],
    ):
        if shutil.which(argv[0]) is None:
            continue
        try:
            done = subprocess.run(
                argv, capture_output = True, text = True, timeout = 10, stdin = subprocess.DEVNULL
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if done.returncode == 0 and (
            argv[0] != "dpkg-query" or "install ok installed" in done.stdout
        ):
            return True
    return False


def already_installed_note(command) -> str:
    """A model message when nothing in the install is missing, else ""."""
    names = install_targets(command)
    if not names:
        return ""
    key = " ".join(names)
    now = time.monotonic()
    cached = _CACHE.get(key)
    if cached and now - cached[0] < _CACHE_S:
        return cached[1]
    found: list[str] = []
    for name in names:
        path = shutil.which(name)
        if path:
            found.append(f"{name} ({path})")
        elif _package_installed(name):
            found.append(f"{name} (installed package)")
        else:
            found = []
            break
    note = (
        "Not run: already installed on this computer, nothing to install -- "
        + ", ".join(found)
        + ". Use it and carry on with the task."
        if found
        else ""
    )
    if len(_CACHE) > 200:
        _CACHE.clear()
    _CACHE[key] = (now, note)
    return note
