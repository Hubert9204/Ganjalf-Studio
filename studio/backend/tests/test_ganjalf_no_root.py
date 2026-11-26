# SPDX-License-Identifier: AGPL-3.0-only
"""Ganjalf: without the administrator password the agent stops trying sudo after the first refusal."""

import uuid

from core.inference import command_shapes
from core.inference.tool_loop_controller import ToolLoopController

TERMINAL = {
    "type": "function",
    "function": {
        "name": "terminal",
        "parameters": {"type": "object", "properties": {"command": {"type": "string"}}},
    },
}
SUDO_FAILED = (
    "Exit code 1:\nsudo: a terminal is required to read the password; either use the -S option "
    "to read from standard input or configure an askpass helper\nsudo: a password is required\n"
)


def _call(command):
    return {"id": "c1", "function": {"name": "terminal", "arguments": {"command": command}}}


def test_the_elevating_commands_are_recognised():
    for command in (
        "sudo dnf install -y curl",
        "cd x && sudo apt-get install curl",
        "dnf install curl",
        "apt install -y wget",
        "pkexec dnf install curl",
        "su -c 'dnf install curl'",
        "pacman -S curl",
        "zypper in curl",
        "flatpak install flathub org.x.Y",
    ):
        assert command_shapes.needs_elevation(command), command
    for command in (
        "npm install",
        "pip install --user requests",
        "flatpak install --user flathub org.x.Y",
        "echo sudoku",
        "cargo install ripgrep",
        "brew install curl",
    ):
        assert not command_shapes.needs_elevation(command), command


def test_a_refused_sudo_gets_one_clear_note():
    session = str(uuid.uuid4())
    note = command_shapes.no_root_note(SUDO_FAILED, "sudo dnf install curl", session)
    assert note.startswith("\n" + command_shapes.ROOT_REFUSED_MARK)
    assert "sudo dnf install curl" in note and "urllib.request" in note
    assert command_shapes.root_refused(session)
    # A real failure of another kind, or a command that does not elevate, gets nothing.
    other = str(uuid.uuid4())
    assert (
        command_shapes.no_root_note(
            "Exit code 1:\nNo match for argument: curlx", "sudo dnf install curlx", other
        )
        == ""
    )
    assert command_shapes.no_root_note(SUDO_FAILED, "make -j4", other) == ""
    assert not command_shapes.root_refused(other)
    dnf = "Error: This command has to be run with superuser privileges (under the root user on most systems)."
    assert command_shapes.no_root_note(dnf, "dnf install curl", other)


def test_the_tool_loop_refuses_the_next_tries_and_ends_after_three():
    session = str(uuid.uuid4())
    controller = ToolLoopController(tools = [TERMINAL], session_id = session)
    first = controller.prepare_call(_call("sudo dnf install -y curl"))
    assert first.action == "execute"
    controller.record_result(
        first, SUDO_FAILED + command_shapes.no_root_note(SUDO_FAILED, "sudo dnf install -y curl")
    )

    for command in (
        "pkexec dnf install curl",
        "su -c 'dnf install curl'",
        "sudo -S apt install curl",
    ):
        decision = controller.prepare_call(_call(command))
        assert decision.action == "retired"
        assert decision.noop_result == command_shapes.ROOT_ALREADY_REFUSED
        controller.record_noop(decision)
    assert controller._force_final_answer  # three refusals: it answers the user instead
    assert controller.prepare_call(_call("ls -la")).action == "execute"

    # Another chat is not affected.
    fresh = ToolLoopController(tools = [TERMINAL], session_id = str(uuid.uuid4()))
    assert fresh.prepare_call(_call("sudo dnf install curl")).action == "execute"
