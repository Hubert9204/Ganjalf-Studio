# SPDX-License-Identifier: AGPL-3.0-only
"""Ganjalf: installs are skipped when the tools are there, and sudo asks the user in a box."""

import os
import shutil
import subprocess
import sys
import threading
import uuid

import pytest

from core.inference import command_shapes, sudo_prompt, system_installs
from core.inference.tool_loop_controller import ToolLoopController

TERMINAL = {
    "type": "function",
    "function": {
        "name": "terminal",
        "parameters": {"type": "object", "properties": {"command": {"type": "string"}}},
    },
}


def test_only_a_whole_install_command_is_read():
    assert system_installs.install_targets("sudo dnf install -y curl wget") == ["curl", "wget"]
    assert system_installs.install_targets("apt-get install -y git") == ["git"]
    assert system_installs.install_targets("sudo -n zypper in jq") == ["jq"]
    assert system_installs.install_targets("pacman -S --needed git") == ["git"]
    for command in (
        "sudo dnf install curl && curl -O x",  # something else runs too
        "dnf search curl",
        "pacman -Ss curl",
        "sudo dnf install @development-tools",
        "npm install curl",
        "dnf install ./local.rpm",
    ):
        assert system_installs.install_targets(command) is None, command


def test_an_install_of_what_is_already_there_is_not_run(monkeypatch):
    system_installs._CACHE.clear()
    monkeypatch.setattr(
        system_installs.shutil, "which", lambda name: f"/usr/bin/{name}" if name == "curl" else None
    )
    monkeypatch.setattr(system_installs, "_package_installed", lambda name: name == "libfoo-devel")
    note = system_installs.already_installed_note("sudo dnf install -y curl libfoo-devel")
    assert note.startswith("Not run: already installed")
    assert "curl (/usr/bin/curl)" in note and "libfoo-devel (installed package)" in note
    system_installs._CACHE.clear()
    assert system_installs.already_installed_note("sudo dnf install -y curl ripgrep") == ""

    system_installs._CACHE.clear()
    controller = ToolLoopController(tools = [TERMINAL], session_id = str(uuid.uuid4()))
    decision = controller.prepare_call(
        {
            "id": "c1",
            "function": {"name": "terminal", "arguments": {"command": "sudo dnf install curl"}},
        }
    )
    assert decision.action == "satisfied" and "/usr/bin/curl" in decision.noop_result
    controller.record_noop(decision)
    assert not controller._force_final_answer


def test_the_box_answer_reaches_the_waiting_command(monkeypatch):
    monkeypatch.setattr(sudo_prompt, "password_works", lambda password: password == "right")
    monkeypatch.setattr("utils.account_context.current_account_id", lambda: "acct")
    session = str(uuid.uuid4())
    asked = []

    def _box(event):
        prompt = event["sudo_prompt"]
        asked.append(prompt["wrong"])
        answer = "nope" if prompt["wrong"] == 0 else "right"
        assert not sudo_prompt.resolve_prompt(prompt["id"], "another-chat", "acct", answer)
        threading.Timer(
            0.05, sudo_prompt.resolve_prompt, (prompt["id"], session, "acct", answer)
        ).start()

    password, note = sudo_prompt.obtain_password(session, "sudo dnf install curl", _box)
    assert (password, note) == ("right", "") and asked == [0, 1]
    # Remembered for the chat: the next sudo command asks nothing.
    assert sudo_prompt.obtain_password(session, "sudo dnf install jq", None) == ("right", "")
    sudo_prompt.forget(session)

    def _closed(event):
        prompt = event["sudo_prompt"]
        threading.Timer(
            0.05, sudo_prompt.resolve_prompt, (prompt["id"], session, "acct", None)
        ).start()

    assert sudo_prompt.obtain_password(session, "sudo dnf install curl", _closed) == (
        None,
        "declined",
    )
    assert sudo_prompt.scrub("x right y", "right") == "x ******** y"


@pytest.mark.skipif(sys.platform != "linux", reason = "SO_PEERCRED and /proc")
def test_the_password_goes_only_to_a_helper_started_by_sudo(tmp_path):
    with sudo_prompt.AskpassServer("s3cret") as server:
        env = {**os.environ, **server.env()}
        wrapper = open(os.path.join(env.pop(sudo_prompt.PATH_PREPEND), "sudo")).read()
        assert wrapper.endswith(' -A "$@"\n')
        # Not started by sudo: nothing.
        plain = subprocess.run([server.helper_path], env = env, capture_output = True, timeout = 30)
        assert plain.returncode != 0 and plain.stdout == b""
        # Started by a process called sudo: the password once, with the newline sudo needs.
        fake_sudo = tmp_path / "sudo"
        shutil.copy(shutil.which("sh"), fake_sudo)
        script = f"'{server.helper_path}'; '{server.helper_path}' || echo again"
        out = subprocess.run(
            [str(fake_sudo), "-c", script], env = env, capture_output = True, timeout = 30
        )
        assert out.stdout == b"s3cret\nagain\n"
    assert not os.path.exists(server.helper_path)


def test_the_terminal_asks_and_runs_with_askpass(monkeypatch, tmp_path):
    from core.inference import tools

    seen = {}

    def _fake_exec(
        command,
        *args,
        extra_env = None,
        **kwargs,
    ):
        seen["env"] = dict(extra_env or {})
        return "installed right"

    monkeypatch.setattr(tools, "_bash_exec", _fake_exec)
    monkeypatch.setattr(sudo_prompt, "enabled", lambda: True)
    monkeypatch.setattr(sudo_prompt, "needs_password", lambda: True)
    monkeypatch.setattr(system_installs, "already_installed_note", lambda command: "")
    session = str(uuid.uuid4())
    monkeypatch.setattr(sudo_prompt, "obtain_password", lambda *a, **k: ("right", ""))
    out = tools.execute_tool(
        "terminal",
        {"command": "sudo dnf install -y ripgrep"},
        session_id = session,
        disable_sandbox = True,
    )
    assert out.startswith("installed ********")
    assert seen["env"]["SUDO_ASKPASS"].endswith("askpass") and "DISPLAY" in seen["env"]

    out = tools.execute_tool(
        "terminal",
        {"command": "sudo dnf install -y ripgrep"},
        session_id = session,
        disable_sandbox = False,
    )
    assert out == sudo_prompt.SANDBOX_NOTE

    monkeypatch.setattr(sudo_prompt, "obtain_password", lambda *a, **k: (None, "declined"))
    out = tools.execute_tool(
        "terminal",
        {"command": "sudo dnf install -y ripgrep"},
        session_id = session,
        disable_sandbox = True,
    )
    assert command_shapes.ROOT_REFUSED_MARK in out and command_shapes.root_refused(session)
