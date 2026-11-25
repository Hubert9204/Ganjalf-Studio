"""Ganjalf: plugin monitors, Claude Code's background watchers.

A monitor is a command a plugin declares (``monitors/monitors.json``) that runs for the whole
chat, from the first message ("always") or from the first time one of its skills is used
("on-skill-invoke:<skill>"). Ganjalf runs it as a background job of the chat: the model reads
its output with terminal_output and the job panel shows it with a Stop button.

A monitor runs a command, so it starts only for plugins whose hooks the user switched on: the
same consent as the plugin's hook commands.
"""

from __future__ import annotations

import logging
import threading
from typing import Optional

logger = logging.getLogger(__name__)

_lock = threading.Lock()
# (session, plugin:monitor) -> job id
_started: dict[tuple[str, str], str] = {}


def _hooks_on(plugin: str) -> bool:
    from .manager import load_registry
    record = load_registry()["plugins"].get(plugin) or {}
    return bool(record.get("enabled") and record.get("hooks_enabled"))


def start(session_id: Optional[str], trigger: str = "always") -> list[dict]:
    """Start the monitors for ``trigger`` that are not running in this chat yet; returns all running ones."""
    from core.inference import background_jobs
    from core.inference.tools import _bash_exec, _session_in_flight

    from .manager import monitors_for

    session = session_id or ""
    try:
        wanted = [m for m in monitors_for(trigger) if _hooks_on(m["plugin"])]
    except Exception:  # noqa: BLE001 -- a plugin problem must never break a chat
        logger.debug("monitor lookup failed", exc_info = True)
        wanted = []
    for monitor in wanted:
        key = (session, f"{monitor['plugin']}:{monitor['name']}")
        with _lock:
            job_id = _started.get(key)
        if job_id and background_jobs.is_running(job_id):
            continue
        command = monitor["command"]

        def run(
            job_cancel,
            append,
            timeout,
            command = command,
        ):
            with _session_in_flight(session_id):
                return _bash_exec(command, job_cancel, timeout, session_id, output_callback = append)

        label = f"monitor {key[1]}: {monitor['description'] or command[:60]}"
        reply = background_jobs.start(label, session_id, run)
        if reply.startswith(("Started background job ", "Background job ")):
            new_id = reply.split("job ", 1)[1].split(":", 1)[0].split(" ", 1)[0]
            with _lock:
                _started[key] = new_id
    return running(session_id)


def running(session_id: Optional[str]) -> list[dict]:
    from core.inference import background_jobs

    session = session_id or ""
    with _lock:
        items = [(name, job_id) for (s, name), job_id in _started.items() if s == session]
    return [
        {"monitor": name, "job": job_id}
        for name, job_id in items
        if background_jobs.is_running(job_id)
    ]


def note(session_id: Optional[str]) -> str:
    """The system-prompt line that tells the model which monitors run and how to read them."""
    found = running(session_id)
    if not found:
        return ""
    listed = ", ".join(f"{item['monitor']} (job {item['job']})" for item in found)
    return (
        "Plugin monitors are running in the background for this chat: "
        f"{listed}. Read what they report with terminal_output when it matters to the task."
    )
