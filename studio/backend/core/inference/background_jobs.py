"""Ganjalf: background terminal jobs owned by the backend, like Claude Code's background shells.

A sandboxed terminal call cannot leave a process behind: bubblewrap runs it in its own PID
namespace with --die-with-parent, so `cmd &` or `nohup cmd &` dies when the call returns. A
background job instead runs the ordinary terminal path (same sandbox, blocklist, approval and
limits) on a worker thread with its own cancel event and a long timeout, and keeps its output in
memory. The model starts it with ``terminal`` + ``run_in_background``, reads new output with
``terminal_output`` and stops it with ``terminal_kill``. A chat's Stop does not end it (as in
Claude Code); ``terminal_kill``, the timeout or the server's exit do.
"""

from __future__ import annotations

import contextvars
import itertools
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

DEFAULT_TIMEOUT_S = 4 * 3600
MAX_JOBS_PER_SESSION = 6
MAX_BUFFER_CHARS = 2_000_000
READ_CHARS = 12_000
START_WAIT_S = 3.0
MAX_WAIT_S = 30.0

_counter = itertools.count(1)
_lock = threading.Lock()
_jobs: dict[str, "Job"] = {}


def background_timeout() -> int:
    """GANJALF_BACKGROUND_TIMEOUT seconds (default 4 h)."""
    try:
        return max(60, int(os.environ.get("GANJALF_BACKGROUND_TIMEOUT", DEFAULT_TIMEOUT_S)))
    except ValueError:
        return DEFAULT_TIMEOUT_S


@dataclass
class Job:
    id: str
    session: str
    command: str
    started: float = field(default_factory = time.monotonic)
    cancel: threading.Event = field(default_factory = threading.Event)
    buffer: list = field(default_factory = list)
    size: int = 0
    dropped: int = 0
    read_at: int = 0  # absolute char offset already returned to the model
    result: Optional[str] = None
    thread: Optional[threading.Thread] = None
    changed: threading.Condition = field(default_factory = threading.Condition)

    @property
    def running(self) -> bool:
        return self.result is None

    def append(self, line: str) -> None:
        with self.changed:
            self.buffer.append(line)
            self.size += len(line)
            while self.size - self.dropped > MAX_BUFFER_CHARS and self.buffer:
                gone = self.buffer.pop(0)
                self.dropped += len(gone)
            self.changed.notify_all()

    def text_since(self, offset: int) -> tuple[str, int, int]:
        """(text, new offset, chars lost before it) from an absolute offset."""
        with self.changed:
            whole = "".join(self.buffer)
            start = max(offset, self.dropped)
            return whole[start - self.dropped :], self.size, start - offset


def _key(session_id: Optional[str]) -> str:
    return session_id or "_"


def start(
    command: str,
    session_id: Optional[str],
    run: Callable[[threading.Event, Callable[[str], None], int], str],
) -> str:
    """Start ``run(cancel_event, output_callback, timeout)`` in the background; returns the reply."""
    session = _key(session_id)
    with _lock:
        live = [job for job in _jobs.values() if job.session == session and job.running]
        if len(live) >= MAX_JOBS_PER_SESSION:
            return (
                f"Error: {len(live)} background jobs are already running "
                f"({', '.join(job.id for job in live)}). Stop one with terminal_kill first."
            )
        job = Job(id = f"bg{next(_counter)}", session = session, command = command)
        _jobs[job.id] = job
    timeout = background_timeout()
    context = contextvars.copy_context()

    def work() -> None:
        try:
            outcome = context.run(run, job.cancel, job.append, timeout)
        except BaseException as exc:  # reported through terminal_output
            outcome = f"Execution error: {exc}"
        with job.changed:
            job.result = outcome if isinstance(outcome, str) else str(outcome)
            job.changed.notify_all()

    job.thread = threading.Thread(target = work, name = f"ganjalf-{job.id}", daemon = True)
    job.thread.start()
    # Long enough to catch a dev server's address or an immediate failure.
    with job.changed:
        job.changed.wait_for(lambda: not job.running, timeout = START_WAIT_S)
    text, job.read_at, _ = job.text_since(0)
    head = (
        f"Started background job {job.id}: {command}\n"
        "It keeps running after this call (a chat Stop does not end it). Read its new output with "
        f"terminal_output id=\"{job.id}\", stop it with terminal_kill id=\"{job.id}\"."
    )
    if not job.running:
        head = f"Background job {job.id} already ended: {command}\n{_ended(job)}"
    return head + (f"\n\nOutput so far:\n{_tail(text)}" if text.strip() else "\n\n(no output yet)")


def _tail(text: str, limit: int = READ_CHARS) -> str:
    if len(text) <= limit:
        return text
    return f"... ({len(text) - limit} earlier chars not shown)\n" + text[-limit:]


def _ended(job: Job) -> str:
    result = (job.result or "").lstrip()
    first = result.splitlines()[0][:300] if result else ""
    if result.startswith("Exit code"):
        status = result.split(":", 1)[0]
    elif result.startswith("Execution cancelled"):
        status = "stopped"
    elif "timed out" in result[:300].lower():
        status = "timed out"
    elif result.startswith(("Execution error", "Blocked", "Error", "No command")):
        status = first
    else:
        status = "exit code 0"
    return f"Status: ended ({status})."


def _find(arguments: dict, session_id: Optional[str]) -> "Job | str":
    wanted = str((arguments or {}).get("id") or "").strip()
    session = _key(session_id)
    with _lock:
        mine = [job for job in _jobs.values() if job.session == session]
    if not wanted:
        live = [job for job in mine if job.running]
        if len(live) == 1:
            return live[0]
        listing = ", ".join(f"{job.id} ({'running' if job.running else 'ended'}: {job.command[:60]})" for job in mine)
        return f"Error: pass id. Background jobs in this chat: {listing or 'none'}."
    for job in mine:
        if job.id == wanted:
            return job
    listing = ", ".join(job.id for job in mine)
    return f"Error: no background job {wanted!r} in this chat (jobs: {listing or 'none'})."


def output(arguments: dict, session_id: Optional[str]) -> str:
    job = _find(arguments, session_id)
    if isinstance(job, str):
        return job
    try:
        wait = min(MAX_WAIT_S, max(0.0, float((arguments or {}).get("wait_seconds") or 0)))
    except (TypeError, ValueError):
        wait = 0.0
    if wait:
        deadline = time.monotonic() + wait
        with job.changed:
            job.changed.wait_for(
                lambda: not job.running or job.size > job.read_at,
                timeout = max(0.0, deadline - time.monotonic()),
            )
    text, job.read_at, lost = job.text_since(job.read_at)
    elapsed = int(time.monotonic() - job.started)
    status = f"Status: running for {elapsed} s." if job.running else _ended(job)
    parts = [f"Background job {job.id}: {job.command}", status]
    if lost:
        parts.append(f"({lost} chars of older output were dropped from the buffer.)")
    parts.append(f"New output:\n{_tail(text)}" if text.strip() else "No new output.")
    return "\n".join(parts)


def kill(arguments: dict, session_id: Optional[str]) -> str:
    job = _find(arguments, session_id)
    if isinstance(job, str):
        return job
    if not job.running:
        return f"Background job {job.id} had already ended. {_ended(job)}"
    job.cancel.set()
    if job.thread is not None:
        job.thread.join(timeout = 10)
    return (
        f"Stopped background job {job.id}: {job.command}"
        if not job.running
        else f"Asked background job {job.id} to stop; it is still shutting down."
    )


def list_jobs(session_id: Optional[str]) -> list[dict]:
    session = _key(session_id)
    with _lock:
        return [
            {"id": job.id, "command": job.command, "running": job.running}
            for job in _jobs.values()
            if job.session == session
        ]


def stop_all() -> None:
    """Server shutdown: end every job."""
    with _lock:
        jobs = list(_jobs.values())
    for job in jobs:
        job.cancel.set()


TERMINAL_OUTPUT_TOOL = {
    "type": "function",
    "function": {
        "name": "terminal_output",
        "description": (
            "Read the new output of a background job started with terminal run_in_background "
            "(a dev server, a watcher, a long build) and whether it is still running. Each call "
            "returns only what arrived since the last one."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "Job id, e.g. bg1."},
                "wait_seconds": {
                    "type": "number",
                    "description": f"Wait up to this long (max {MAX_WAIT_S:g}) for new output or the end.",
                },
            },
            "required": ["id"],
        },
    },
}

TERMINAL_KILL_TOOL = {
    "type": "function",
    "function": {
        "name": "terminal_kill",
        "description": "Stop a background job started with terminal run_in_background, and everything it started.",
        "parameters": {
            "type": "object",
            "properties": {"id": {"type": "string", "description": "Job id, e.g. bg1."}},
            "required": ["id"],
        },
    },
}
