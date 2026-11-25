"""Ganjalf: the folders outside a project's own folder where its chats wrote files.

Chats in one project share the project folder, but a request can name another place ("build it
in /tmp/expense-split"). The next chat in the project then finds an empty project folder and
asks the user for "the code". Each file edit_file writes outside the project folder records its
folder here, and every chat of the project is told where the earlier work is.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from typing import Optional

logger = logging.getLogger(__name__)

STORE = os.path.join(".ganjalf", "places.json")
MAX_PLACES = 8
_lock = threading.Lock()


def _project_folder(session_id: Optional[str]) -> Optional[str]:
    from .tools import _PROJECT_SESSION_PREFIX, _get_workdir
    if not session_id or not str(session_id).startswith(_PROJECT_SESSION_PREFIX):
        return None
    try:
        return os.path.realpath(_get_workdir(session_id))
    except Exception:  # noqa: BLE001 -- no project folder: nothing to remember
        return None


def _inside(path: str, folder: str) -> bool:
    return path == folder or path.startswith(folder.rstrip(os.sep) + os.sep)


def _load(project: str) -> list[str]:
    try:
        with open(os.path.join(project, STORE), encoding = "utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return []
    return [str(p) for p in data if isinstance(p, str)] if isinstance(data, list) else []


def _merge(places: list[str], folder: str) -> list[str]:
    """Newest first; a folder inside a known one is the same place, one around it replaces it."""
    if any(_inside(folder, known) for known in places):
        return [p for p in places if _inside(folder, p)] + [
            p for p in places if not _inside(folder, p)
        ]
    kept = [p for p in places if not _inside(p, folder)]
    return [folder, *kept][:MAX_PLACES]


def note_write(session_id: Optional[str], path: str) -> None:
    """Remember the folder of a file this project's chat wrote outside the project folder."""
    project = _project_folder(session_id)
    if not project or not path:
        return
    folder = os.path.dirname(os.path.realpath(path))
    if _inside(folder, project) or folder in ("/", os.path.expanduser("~")):
        return
    with _lock:
        places = _load(project)
        merged = _merge(places, folder)
        if merged == places:
            return
        target = os.path.join(project, STORE)
        try:
            os.makedirs(os.path.dirname(target), exist_ok = True)
            tmp = target + ".tmp"
            with open(tmp, "w", encoding = "utf-8") as handle:
                json.dump(merged, handle)
            os.replace(tmp, target)
        except OSError:
            logger.debug("project places not saved", exc_info = True)


def places_note(session_id: Optional[str]) -> str:
    """The sentence for the system prompt, or "" when the project has no outside places."""
    project = _project_folder(session_id)
    if not project:
        return ""
    places = [p for p in _load(project) if os.path.isdir(p)]
    if not places:
        return ""
    listed = ", ".join(places)
    return (
        "Earlier chats in this project also created or changed files outside the project folder, "
        f'in: {listed}. When the user talks about "the code", "the app" or earlier work and the '
        "project folder does not have it, look there first (with absolute paths) before asking."
    )
