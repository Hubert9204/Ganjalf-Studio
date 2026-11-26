# SPDX-License-Identifier: AGPL-3.0-only
"""Ganjalf: sudo with the user's own password, typed in a Studio box.

When an agent command needs ``sudo`` and sudo wants a password, the chat shows a password box
(a ``sudo_prompt`` tool_output event, answered by POST /api/inference/sudo-password). The
password never reaches the model, the command text, the environment or a file:

- it is checked once with ``sudo -A -k true``;
- the command then runs with ``SUDO_ASKPASS`` pointing at a tiny helper that asks a private
  Unix socket for it; the socket answers only a helper whose parent process is ``sudo``, and
  each sudo process at most once, so a wrong password costs one attempt, never three
  (which would trip faillock);
- it is kept in memory for GANJALF_SUDO_REMEMBER_S seconds (default 600; 0 asks every time),
  per chat, so a few installs in a row ask once.

Linux only; nothing changes when Studio already runs as root or sudo needs no password.
"""

from __future__ import annotations

import os
import re
import secrets
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any, Callable, Optional

PROMPT_TIMEOUT_S = 180.0
# Not an environment variable: the terminal puts this folder first on the command's PATH.
PATH_PREPEND = "__ganjalf_path_prepend__"
MAX_ATTEMPTS = 3

_SUDO_RE = re.compile(r"(?:^|[\s;&|(`$])sudo(?=\s|$)")

_lock = threading.Lock()
_pending: dict[str, dict] = {}
_remembered: dict[str, tuple[str, float]] = {}

SANDBOX_NOTE = (
    "Not run: sudo cannot work inside the sandbox (it blocks becoming root). Tell the user the "
    "command to run in their own terminal, or ask them to switch this chat to Full access; then "
    "Studio shows a box for their password. Do not retry it with su, pkexec or doas."
)
DECLINED_NOTE = (
    "\n[No administrator password: the user closed the password box, so this was not run. Do not "
    "try again with sudo, su, pkexec, doas or another package manager. Tell the user the exact "
    "command to run in their own terminal, then carry on without it if you can, or stop and wait.]"
)
EXPIRED_NOTE = (
    "Not run: nobody typed the administrator password in time. Tell the user the command and that "
    "Studio asks for the password in a box when it runs it, then stop and wait."
)
WRONG_NOTE = (
    "Not run: the administrator password was wrong {n} times. Tell the user, and give them the "
    "command to run in their own terminal."
)


def uses_sudo(command: Any) -> bool:
    return isinstance(command, str) and bool(_SUDO_RE.search(command))


def enabled() -> bool:
    if os.environ.get("GANJALF_SUDO_PROMPT", "1").strip().lower() in ("0", "false", "no", "off"):
        return False
    if sys.platform != "linux" or not hasattr(socket, "SO_PEERCRED"):
        return False
    return os.geteuid() != 0 and shutil.which("sudo") is not None


def _remember_seconds() -> float:
    try:
        return max(0.0, float(os.environ.get("GANJALF_SUDO_REMEMBER_S", "600")))
    except ValueError:
        return 600.0


def _quiet_env(extra: Optional[dict] = None) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("SUDO_ASKPASS")}
    env["LC_ALL"] = "C"
    env.update(extra or {})
    return env


def needs_password() -> bool:
    """False when sudo runs without one (NOPASSWD, or a cached ticket)."""
    try:
        done = subprocess.run(
            ["sudo", "-n", "true"],
            stdin = subprocess.DEVNULL,
            stdout = subprocess.DEVNULL,
            stderr = subprocess.DEVNULL,
            start_new_session = True,
            timeout = 10,
            env = _quiet_env(),
        )
    except (OSError, subprocess.SubprocessError):
        return True
    return done.returncode != 0


# --- the box in the chat -------------------------------------------------------------------


def begin_prompt(session_id: str, account_id: str) -> tuple[str, dict]:
    prompt_id = secrets.token_urlsafe(16)
    slot = {
        "event": threading.Event(),
        "password": None,
        "session": session_id or "",
        "account": account_id or "",
    }
    with _lock:
        _pending[prompt_id] = slot
    return prompt_id, slot


def resolve_prompt(
    prompt_id: str, session_id: Optional[str], account_id: str, password: Optional[str]
) -> bool:
    """First answer wins; None (or empty) means the user closed the box."""
    if not prompt_id:
        return False
    with _lock:
        slot = _pending.get(prompt_id)
        if not slot or slot["event"].is_set():
            return False
        if slot["session"] != (session_id or "") or slot["account"] != (account_id or ""):
            return False
        slot["password"] = password if isinstance(password, str) and password else None
        slot["event"].set()
    return True


def _wait_prompt(
    slot: dict, prompt_id: str, cancel_event, timeout: float
) -> tuple[str, Optional[str]]:
    waited = 0.0
    try:
        while not slot["event"].wait(timeout = 0.25):
            if cancel_event is not None and cancel_event.is_set():
                return "cancelled", None
            waited += 0.25
            if waited >= timeout:
                return "expired", None
        password = slot["password"]
        return ("answered", password) if password else ("declined", None)
    finally:
        with _lock:
            if _pending.get(prompt_id) is slot:
                _pending.pop(prompt_id, None)


# --- handing the password to sudo ----------------------------------------------------------

_HELPER = """#!{python}
import os, socket, sys
try:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(30)
    s.connect(os.environ["GANJALF_ASKPASS_SOCKET"])
    data = b""
    while True:
        chunk = s.recv(4096)
        if not chunk:
            break
        data += chunk
except Exception:
    sys.exit(1)
if not data:
    sys.exit(1)
sys.stdout.buffer.write(data)
"""


def _parent_is_sudo(pid: int) -> "tuple[bool, int]":
    try:
        with open(f"/proc/{pid}/status", encoding = "ascii", errors = "replace") as handle:
            ppid = next(int(line.split()[1]) for line in handle if line.startswith("PPid:"))
        with open(f"/proc/{ppid}/comm", encoding = "ascii", errors = "replace") as handle:
            return handle.read().strip() == "sudo", ppid
    except (OSError, StopIteration, ValueError, IndexError):
        return False, 0


class AskpassServer:
    """A private socket that hands the password to sudo's askpass helper, once per sudo process."""

    def __init__(
        self,
        password: str,
        max_serves: int = 64,
    ):
        self._password = password.encode() + b"\n"  # sudo drops a reply with no newline
        self._max = max_serves
        self._served: set[int] = set()
        self._dir = tempfile.mkdtemp(prefix = "ganjalf-askpass-")
        os.chmod(self._dir, 0o700)
        self.socket_path = os.path.join(self._dir, "s")
        self.helper_path = os.path.join(self._dir, "askpass")
        with open(self.helper_path, "w", encoding = "utf-8") as handle:
            handle.write(_HELPER.format(python = sys.executable))
        os.chmod(self.helper_path, 0o700)
        # `sudo` in the command becomes `sudo -A`, so it asks the helper whatever the sudo version.
        self.bin_dir = os.path.join(self._dir, "bin")
        os.mkdir(self.bin_dir, 0o700)
        real_sudo = shutil.which("sudo") or "/usr/bin/sudo"
        wrapper = os.path.join(self.bin_dir, "sudo")
        with open(wrapper, "w", encoding = "utf-8") as handle:
            handle.write(f'#!/bin/sh\nexec "{real_sudo}" -A "$@"\n')
        os.chmod(wrapper, 0o700)
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.bind(self.socket_path)
        os.chmod(self.socket_path, 0o600)
        self._sock.listen(4)
        self._sock.settimeout(0.5)
        self._closed = threading.Event()
        self._thread = threading.Thread(target = self._serve, daemon = True, name = "ganjalf-askpass")
        self._thread.start()

    def env(self) -> dict:
        return {
            "SUDO_ASKPASS": self.helper_path,
            "GANJALF_ASKPASS_SOCKET": self.socket_path,
            # sudo uses the askpass helper on its own only when there is no terminal AND a display.
            "DISPLAY": os.environ.get("DISPLAY") or ":0",
            PATH_PREPEND: self.bin_dir,
        }

    def _serve(self) -> None:
        uid = os.getuid()
        while not self._closed.is_set():
            try:
                conn, _ = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            with conn:
                try:
                    creds = conn.getsockopt(
                        socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")
                    )
                    pid, peer_uid, _gid = struct.unpack("3i", creds)
                    is_sudo, sudo_pid = _parent_is_sudo(pid)
                    if peer_uid != uid or not is_sudo or sudo_pid in self._served:
                        continue
                    if len(self._served) >= self._max:
                        continue
                    self._served.add(sudo_pid)
                    conn.sendall(self._password)
                except OSError:
                    continue

    def close(self) -> None:
        self._closed.set()
        try:
            self._sock.close()
        except OSError:
            pass
        self._thread.join(timeout = 2)
        self._password = b""
        shutil.rmtree(self._dir, ignore_errors = True)

    def __enter__(self) -> "AskpassServer":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()


def password_works(password: str) -> bool:
    with AskpassServer(password, max_serves = 1) as server:
        try:
            done = subprocess.run(
                ["sudo", "-A", "-k", "true"],
                stdin = subprocess.DEVNULL,
                stdout = subprocess.DEVNULL,
                stderr = subprocess.DEVNULL,
                start_new_session = True,
                timeout = 30,
                env = _quiet_env(server.env()),
            )
        except (OSError, subprocess.SubprocessError):
            return False
    return done.returncode == 0


def _recall(session_key: str) -> Optional[str]:
    with _lock:
        entry = _remembered.get(session_key)
        if entry and entry[1] > time.monotonic():
            return entry[0]
        _remembered.pop(session_key, None)
    return None


def _keep(session_key: str, password: str) -> None:
    seconds = _remember_seconds()
    if seconds <= 0 or not session_key:
        return
    with _lock:
        _remembered[session_key] = (password, time.monotonic() + seconds)


def forget(session_key: str) -> None:
    with _lock:
        _remembered.pop(session_key, None)


def obtain_password(
    session_key: str,
    command: str,
    output_callback: Optional[Callable[[Any], None]],
    cancel_event = None,
) -> tuple[Optional[str], str]:
    """(password, "") or (None, note for the model). Asks in the chat, up to MAX_ATTEMPTS."""
    from utils.account_context import current_account_id

    remembered = _recall(session_key)
    if remembered is not None:
        if password_works(remembered):
            return remembered, ""
        forget(session_key)
    if output_callback is None:
        return None, EXPIRED_NOTE
    wrong = 0
    while wrong < MAX_ATTEMPTS:
        prompt_id, slot = begin_prompt(session_key, current_account_id())
        try:
            output_callback(
                {
                    "sudo_prompt": {
                        "id": prompt_id,
                        "session_id": session_key,
                        "command": command[:500],
                        "wrong": wrong,
                        "timeout_s": PROMPT_TIMEOUT_S,
                        "expires_at": int((time.time() + PROMPT_TIMEOUT_S) * 1000),
                    }
                }
            )
        except BaseException:
            with _lock:
                _pending.pop(prompt_id, None)
            raise
        outcome, password = _wait_prompt(slot, prompt_id, cancel_event, PROMPT_TIMEOUT_S)
        if outcome == "cancelled":
            return None, "Error: stopped while waiting for the administrator password."
        if outcome == "expired":
            return None, EXPIRED_NOTE
        if outcome == "declined" or password is None:
            return None, "declined"
        if password_works(password):
            _keep(session_key, password)
            return password, ""
        wrong += 1
    return None, WRONG_NOTE.format(n = MAX_ATTEMPTS)


def scrub(text: str, password: Optional[str]) -> str:
    """The password never goes back to the model, even if a program printed it."""
    if not isinstance(text, str) or not password or len(password) < 3:
        return text
    return text.replace(password, "********")
