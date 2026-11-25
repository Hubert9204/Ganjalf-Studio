"""Plugin bin/, output styles and monitors (Claude Code's plugin layout)."""

import json
import os
import time

import pytest

from core.plugins import manager


@pytest.fixture
def studio(tmp_path, monkeypatch):
    home = tmp_path / "studio"
    home.mkdir()
    monkeypatch.setenv("UNSLOTH_STUDIO_HOME", str(home))
    monkeypatch.delenv("GANJALF_PLUGINS_HOME", raising = False)
    from storage import mcp_servers_db

    mcp_servers_db.reset_schema_state_for_tests()
    return home


def _plugin(tmp_path, monitors = None):
    root = tmp_path / "tools"
    files = {
        ".claude-plugin/plugin.json": json.dumps({"name": "tools", "description": "Tools"}),
        "bin/hello-tool": "#!/bin/sh\necho hello from plugin\n",
        "output-styles/terse.md": "---\nname: terse\ndescription: Short answers.\nkeep-coding-instructions: true\n---\nAnswer in at most three sentences.\n",
        "monitors/monitors.json": json.dumps(
            monitors
            if monitors is not None
            else [{"name": "ticker", "command": "echo tick; sleep 30", "description": "Ticks"}]
        ),
        "themes/dark.json": "{}",
        "workflows/release.js": "export default {}",
    }
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents = True, exist_ok = True)
        path.write_text(content)
    os.chmod(root / "bin" / "hello-tool", 0o755)
    return root


def test_the_parts_are_read_and_the_two_without_meaning_listed(studio, tmp_path):
    preview = manager.preview(str(_plugin(tmp_path)))
    contents = preview["plugin"]
    assert contents["bin"] == ["hello-tool"]
    assert (
        contents["output_styles"][0]["name"] == "terse"
        and contents["output_styles"][0]["keep_coding_instructions"]
    )
    assert contents["monitors"][0] == {
        "name": "ticker",
        "command": "echo tick; sleep 30",
        "description": "Ticks",
        "when": "always",
    }
    assert any("themes" in label for label in contents["unsupported"])
    assert any("workflows" in label for label in contents["unsupported"])
    assert not any(
        "bin" in label or "monitor" in label or "output" in label
        for label in contents["unsupported"]
    )


def test_bin_goes_on_the_terminal_path_while_the_plugin_is_on(studio, tmp_path):
    from core.inference import tools

    manager.install(manager.preview(str(_plugin(tmp_path)))["token"])
    folder = str(manager.plugin_dir("tools") / "bin")
    assert manager.bin_dirs() == [folder]
    env = tools._build_safe_env(str(tmp_path))
    assert env["PATH"].split(os.pathsep)[-1] == folder  # last: never shadows a system command
    manager.set_enabled("tools", False)
    assert manager.bin_dirs() == []


def test_an_output_style_is_chosen_and_reaches_the_agent_instructions(studio, tmp_path):
    from routes import inference as routes

    manager.install(manager.preview(str(_plugin(tmp_path)))["token"])
    assert manager.output_style_choices() == [
        {"id": "tools:terse", "plugin": "tools", "name": "terse"}
    ]
    manager.set_output_style("tools:terse")
    style = manager.active_output_style()
    assert (
        style["body"] == "Answer in at most three sentences." and style["keep_coding_instructions"]
    )
    assert "Output style chosen by the user (tools:terse)" in routes._active_output_style_text()
    manager.set_enabled("tools", False)
    assert manager.active_output_style() is None and routes._active_output_style_text() == ""
    with pytest.raises(manager.PluginError):
        manager.set_output_style("tools:nope")


def test_monitors_start_only_with_hooks_on_and_once_per_chat(studio, tmp_path):
    from core.inference import background_jobs
    from core.plugins import monitors

    manager.install(manager.preview(str(_plugin(tmp_path)))["token"])
    assert monitors.start("chat-1") == []  # hooks off: no command runs
    manager.set_hooks_enabled("tools", True)
    started = monitors.start("chat-1")
    if not started:
        pytest.skip("terminal unavailable here")
    assert started[0]["monitor"] == "tools:ticker"
    assert monitors.start("chat-1") == started  # not started twice
    assert "tools:ticker (job " in monitors.note("chat-1")
    job = started[0]["job"]
    deadline = time.monotonic() + 10
    out = ""
    while time.monotonic() < deadline and "tick" not in out:
        out += background_jobs.output({"id": job, "wait_seconds": 1}, "chat-1")
    assert "tick" in out
    background_jobs.kill({"id": job}, "chat-1")


def test_skill_bound_monitors_match_the_names_ganjalf_gives_skills():
    assert manager._monitor_fires("on-skill-invoke:deploy", "on-skill-invoke:tools-deploy", "tools")
    assert manager._monitor_fires("on-skill-invoke:deploy", "on-skill-invoke:deploy", "tools")
    assert not manager._monitor_fires("on-skill-invoke:deploy", "on-skill-invoke:other", "tools")
    assert not manager._monitor_fires("on-skill-invoke:deploy", "always", "tools")
    assert manager._monitor_fires("always", "always", "tools")
