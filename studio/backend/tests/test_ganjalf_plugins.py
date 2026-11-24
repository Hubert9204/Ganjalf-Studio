# SPDX-License-Identifier: AGPL-3.0-only
# Copyright 2026-present the Unsloth AI Inc. team. All rights reserved. See /studio/LICENSE.AGPL-3.0

"""Claude Code plugins in Ganjalf: reading, installing, skills and commands, MCP rows, hooks, agents."""

import io
import json
import stat
import sys
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from core.plugins import agents as plugin_agents
from core.plugins import hooks as plugin_hooks
from core.plugins import manager
from core.plugins.fetch import FetchError, parse_source, unpack
from core.plugins.inspect import PluginError, inspect_plugin


@pytest.fixture
def studio(tmp_path, monkeypatch):
    home = tmp_path / "studio"
    home.mkdir()
    monkeypatch.setenv("UNSLOTH_STUDIO_HOME", str(home))
    monkeypatch.delenv("GANJALF_PLUGINS_HOME", raising = False)
    from storage import mcp_servers_db

    mcp_servers_db.reset_schema_state_for_tests()
    return home


def _write(root, files):
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents = True, exist_ok = True)
        path.write_text(content)
    return root


PY = sys.executable


def _demo(tmp_path, name = "demo"):
    return _write(
        tmp_path / name,
        {
            ".claude-plugin/plugin.json": json.dumps(
                {"name": name, "version": "1.2.0", "description": "Demo", "author": {"name": "Ann"}}
            ),
            "skills/lint/SKILL.md": "---\nname: lint\ndescription: Lint the code.\nallowed-tools: [Bash, Read]\n---\nRun ${CLAUDE_PLUGIN_ROOT}/bin/lint\n",
            "skills/lint/ref.md": "reference",
            f"skills/{name}/SKILL.md": f"---\nname: {name}\ndescription: Main skill.\n---\nBody\n",
            "commands/hello.md": "---\ndescription: Say hello\nargument-hint: [name]\n---\nSay hello to $ARGUMENTS.\n",
            "commands/git/sync.md": "Sync the branch.\n",
            "agents/tester.md": "---\nname: tester\ndescription: Runs tests.\ntools: Bash, Edit\n---\nYou run tests.\n",
            "hooks/hooks.json": json.dumps(
                {
                    "hooks": {
                        "PreToolUse": [
                            {"matcher": "Bash", "hooks": [{"type": "command", "command": f'"{PY}" "${{CLAUDE_PLUGIN_ROOT}}/hooks/guard.py"'}]}
                        ],
                        "PostToolUse": [
                            {
                                "matcher": "Edit|Write",
                                "hooks": [
                                    {"type": "command", "command": "echo '{\"hookSpecificOutput\": {\"additionalContext\": \"Run the tests.\"}}'"},
                                    {"type": "command", "command": "echo later", "asyncRewake": True},
                                ],
                            }
                        ],
                        "UserPromptSubmit": [{"hooks": [{"type": "command", "command": "echo Use tabs."}]}],
                        "Stop": [
                            {
                                "hooks": [
                                    {
                                        "type": "command",
                                        "command": f'"{PY}" -c "import json,sys; d=json.load(sys.stdin); print(\'\' if d[\'stop_hook_active\'] else json.dumps({{\'decision\': \'block\', \'reason\': \'Add a summary.\'}}))"',
                                    }
                                ]
                            }
                        ],
                    }
                }
            ),
            "hooks/guard.py": "import json, sys\nd = json.load(sys.stdin)\nif 'rm -rf' in d['tool_input'].get('command', ''):\n    print('No rm -rf.', file=sys.stderr); sys.exit(2)\n",
            ".mcp.json": json.dumps({"mcpServers": {"docs": {"type": "http", "url": "https://example.com/mcp"}}}),
            ".lsp.json": "{}",
            "bin/tool": "#!/bin/sh\n",
        },
    )


def test_inspect_lists_every_part_and_what_is_not_used(tmp_path):
    summary = inspect_plugin(_demo(tmp_path))
    assert summary["name"] == "demo" and summary["version"] == "1.2.0" and summary["author"] == "Ann"
    assert {skill["name"] for skill in summary["skills"]} == {"lint", "demo"}
    assert {command["name"] for command in summary["commands"]} == {"hello", "git:sync"}
    assert summary["commands"][0]["argument_hint"] == "[name]"
    assert summary["agents"][0] == {
        "name": "tester",
        "path": "agents/tester.md",
        "description": "Runs tests.",
        "tools": ["Bash", "Edit"],
    }
    assert set(summary["hooks"]) == {"PreToolUse", "PostToolUse", "UserPromptSubmit", "Stop"}
    assert len(summary["hooks"]["PostToolUse"][0]["hooks"]) == 1
    assert any("background" in warning for warning in summary["warnings"])
    assert list(summary["mcp_servers"]) == ["docs"]
    assert "LSP servers" in summary["unsupported"] and "bin/ (executables on the PATH)" in summary["unsupported"]


def test_a_folder_with_nothing_usable_is_refused(tmp_path):
    _write(tmp_path / "empty", {"README.md": "hi"})
    with pytest.raises(PluginError):
        inspect_plugin(tmp_path / "empty")


def test_paths_outside_the_plugin_are_ignored(tmp_path):
    root = _write(
        tmp_path / "p",
        {
            ".claude-plugin/plugin.json": json.dumps({"name": "p", "skills": ["../outside"], "agents": ["/etc/passwd"]}),
            "commands/a.md": "A",
        },
    )
    _write(tmp_path / "outside", {"x/SKILL.md": "---\nname: x\ndescription: d\n---\n"})
    summary = inspect_plugin(root)
    assert summary["skills"] == [] and summary["agents"] == []
    assert len([w for w in summary["warnings"] if "outside the plugin" in w]) == 2


def test_sources_parse():
    assert parse_source("anthropics/claude-code").to_dict() == {"kind": "github", "owner": "anthropics", "repo": "claude-code"}
    assert parse_source("o/r/plugins/x@v2").to_dict() == {"kind": "github", "owner": "o", "repo": "r", "ref": "v2", "path": "plugins/x"}
    assert parse_source("https://github.com/o/r/tree/main/a/b").to_dict() == {
        "kind": "github",
        "owner": "o",
        "repo": "r",
        "ref": "main",
        "path": "a/b",
    }
    assert parse_source("https://example.com/p.zip").kind == "url"
    assert parse_source("https://gitlab.com/o/r.git").kind == "git"
    with pytest.raises(FetchError):
        parse_source("o/r/../../etc")


def test_archives_unpack_without_escapes_or_links(tmp_path):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("top/ok.txt", "ok")
        archive.writestr("../evil.txt", "no")
        link = zipfile.ZipInfo("top/link")
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(link, "/etc/passwd")
    unpack(output.getvalue(), tmp_path / "out")
    assert (tmp_path / "out" / "top" / "ok.txt").read_text() == "ok"
    assert not (tmp_path / "evil.txt").exists() and not (tmp_path / "out" / "top" / "link").exists()


def test_install_turns_skills_and_commands_into_studio_skills(studio, tmp_path):
    from core.inference import skills

    preview = manager.preview(str(_demo(tmp_path)))
    assert preview["kind"] == "plugin" and preview["plugin"]["installed"] is False
    record = manager.install(preview["token"])
    assert record["skills"] == ["demo", "demo-lint"]
    assert sorted(record["commands"]) == ["demo-git-sync", "demo-hello"]
    assert record["hooks_enabled"] is False and record["mcp_server_count"] == 1
    listed = {skill["name"]: skill for skill in skills.list_skills() if skill["source"] == "plugin"}
    assert set(listed) == {"demo", "demo-lint", "demo-hello", "demo-git-sync"}
    assert all(skill["valid"] and skill["enabled"] for skill in listed.values())
    lint = skills.read_skill_instructions("demo-lint")
    assert str(manager.plugin_dir("demo")) + "/bin/lint" in lint
    assert (manager.skills_root() / "demo-lint" / "ref.md").is_file()
    hello = skills.read_skill_instructions("demo-hello")
    assert "/demo-hello" in hello and "Say hello to $ARGUMENTS." in hello
    assert listed["demo-lint"]["allowed_tools"] == "Bash Read"


def test_off_removes_its_skills_and_turns_its_mcp_servers_off(studio, tmp_path):
    from core.inference import skills
    from storage import mcp_servers_db

    manager.install(manager.preview(str(_demo(tmp_path)))["token"])
    rows = [row for row in mcp_servers_db.list_servers() if row["display_name"] == "demo · docs"]
    assert len(rows) == 1 and rows[0]["is_enabled"]
    manager.set_enabled("demo", False)
    assert not [s for s in skills.list_skills() if s["source"] == "plugin"]
    assert not mcp_servers_db.get_server(rows[0]["id"])["is_enabled"]
    manager.set_enabled("demo", True)
    assert len([s for s in skills.list_skills() if s["source"] == "plugin"]) == 4
    manager.uninstall("demo")
    assert mcp_servers_db.get_server(rows[0]["id"]) is None
    assert not manager.plugin_dir("demo").exists()
    assert not [s for s in skills.list_skills() if s["source"] == "plugin"]
    assert manager.list_plugins() == []


def test_reinstall_keeps_choices(studio, tmp_path):
    manager.install(manager.preview(str(_demo(tmp_path)))["token"])
    manager.set_hooks_enabled("demo", True)
    again = manager.preview(str(tmp_path / "demo"))
    assert again["plugin"]["installed"] is True and again["plugin"]["installed_version"] == "1.2.0"
    record = manager.install(again["token"])
    assert record["hooks_enabled"] is True


def test_marketplace_with_a_relative_plugin(studio, tmp_path):
    market = _write(
        tmp_path / "market",
        {
            ".claude-plugin/marketplace.json": json.dumps(
                {"name": "team-tools", "owner": {"name": "Team"}, "plugins": [{"name": "greeter", "source": "./plugins/greeter", "description": "Greets"}]}
            ),
            "plugins/greeter/commands/hi.md": "Say hi.",
        },
    )
    found = manager.preview(str(market))
    assert found["kind"] == "marketplace" and found["marketplace"]["plugins"][0]["name"] == "greeter"
    manager.add_marketplace(str(market))
    preview = manager.preview("greeter@team-tools")
    record = manager.install(preview["token"])
    assert record["marketplace"] == "team-tools" and record["commands"] == ["greeter-hi"]
    assert manager.list_marketplaces()[0]["plugins"][0]["installed"] is True


def test_slash_command_loads_like_a_mention():
    from core.inference.skill_mentions import mentioned_skill_names

    assert mentioned_skill_names("/demo-hello Ann and @lint") == ["demo-hello", "lint"]
    assert mentioned_skill_names("see /etc/passwd") == []
    assert mentioned_skill_names("```\n/demo-hello\n```") == []


def test_hooks_run_only_when_switched_on(studio, tmp_path):
    manager.install(manager.preview(str(_demo(tmp_path)))["token"])
    workdir = str(tmp_path)
    assert plugin_hooks.before_tool("terminal", {"command": "rm -rf /"}, session_id = "s", workdir = workdir) is None
    manager.set_hooks_enabled("demo", True)
    blocked = plugin_hooks.before_tool("terminal", {"command": "rm -rf /"}, session_id = "s", workdir = workdir)
    assert blocked.startswith("Error: a plugin hook blocked this call.") and "No rm -rf." in blocked
    assert plugin_hooks.before_tool("terminal", {"command": "ls"}, session_id = "s", workdir = workdir) is None
    assert plugin_hooks.before_tool("python", {"code": "rm -rf"}, session_id = "s", workdir = workdir) is None
    edited = plugin_hooks.after_tool(
        "edit_file", {"path": "a.py", "edits": [{"old_string": "a", "new_string": "b"}]}, "Edited a.py", session_id = "s", workdir = workdir
    )
    assert edited == "Edited a.py\n\nPlugin hook feedback:\n[demo] Run the tests."
    context = plugin_hooks.prompt_context([{"role": "user", "content": "hi"}], session_id = "s", workdir = workdir)
    assert context == "Plugin hooks:\n[demo] Use tabs."
    assert plugin_hooks.stop_check("done", session_id = "s", workdir = workdir, rounds = 0).endswith("[demo] Add a summary.")
    assert plugin_hooks.stop_check("done", session_id = "s", workdir = workdir, rounds = 1) is None
    manager.set_enabled("demo", False)
    assert not plugin_hooks.has_hooks()


def test_claude_names_for_studio_tools():
    assert plugin_hooks.claude_tool("terminal", {"command": "ls"}, "/w") == ("Bash", {"command": "ls", "description": ""})
    assert plugin_hooks.claude_tool("edit_file", {"path": "x.py", "edits": [{"old_string": "", "new_string": "hi"}]}, "/w") == (
        "Write",
        {"file_path": "/w/x.py", "content": "hi"},
    )
    assert plugin_hooks.claude_tool("view_image", {"path": "/a.png"}, "/w") == ("Read", {"file_path": "/a.png"})
    assert plugin_hooks._if_matches("Bash(git*commit*)", "Bash", {"command": "git commit -m x"})
    assert not plugin_hooks._if_matches("Bash(git*push*)", "Bash", {"command": "git commit"})
    assert plugin_hooks._matches("Edit|Write", ("Write", "edit_file"))
    assert plugin_hooks._matches("", ("anything",))


def test_execute_tool_runs_between_hooks(studio, tmp_path, monkeypatch):
    from core.inference import tools

    manager.install(manager.preview(str(_demo(tmp_path)))["token"])
    manager.set_hooks_enabled("demo", True)
    calls = []
    monkeypatch.setattr(tools, "_execute_tool_unhooked", lambda name, arguments, *a, **k: calls.append(name) or "ran")
    monkeypatch.setattr(plugin_hooks, "workdir_for", lambda session_id: str(tmp_path))
    assert tools.execute_tool("terminal", {"command": "rm -rf x"}, session_id = "s").startswith("Error: a plugin hook")
    assert calls == []
    assert tools.execute_tool("terminal", {"command": "ls"}, session_id = "s") == "ran"
    assert calls == ["terminal"]


def _sse_chunks(message):
    """The reply as llama-server streams it: content and tool-call arguments in pieces."""
    deltas = []
    if message.get("content"):
        text = message["content"]
        deltas += [{"content": text[: len(text) // 2]}, {"content": text[len(text) // 2 :]}]
    for index, call in enumerate(message.get("tool_calls") or []):
        arguments = call["function"]["arguments"]
        deltas.append({"tool_calls": [{"index": index, "id": call["id"], "type": "function", "function": {"name": call["function"]["name"], "arguments": ""}}]})
        deltas += [
            {"tool_calls": [{"index": index, "function": {"arguments": arguments[:5]}}]},
            {"tool_calls": [{"index": index, "function": {"arguments": arguments[5:]}}]},
        ]
    lines = [f"data: {json.dumps({'choices': [{'index': 0, 'delta': delta}]})}\n\n".encode() for delta in deltas]
    return lines + [b"data: [DONE]\n\n"]


def test_run_agent_works_in_its_own_conversation(studio, tmp_path, monkeypatch):
    from core.inference import tools

    manager.install(manager.preview(str(_demo(tmp_path)))["token"])
    definition = plugin_agents.tool_definition()
    assert definition["function"]["name"] == "run_agent" and "demo:tester: Runs tests." in definition["function"]["description"]
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append(body)
            if len(seen) == 1:
                message = {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "terminal", "arguments": json.dumps({"command": "pytest"})}}],
                }
            else:
                message = {"role": "assistant", "content": "2 passed; " + body["messages"][-1]["content"]}
            assert body["stream"] is True
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for chunk in _sse_chunks(message):
                self.wfile.write(chunk)
                self.wfile.flush()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target = server.serve_forever, daemon = True).start()
    monkeypatch.setattr(tools, "execute_tool", lambda name, arguments, **kwargs: f"ran {name}: {arguments['command']}")
    monkeypatch.setattr(tools, "_get_workdir", lambda session_id = None: str(tmp_path))
    try:
        report = plugin_agents.run_agent(
            {"agent": "demo:tester", "task": "Run the tests"},
            session_id = "s",
            server = (f"http://127.0.0.1:{server.server_port}", None),
        )
    finally:
        server.shutdown()
    assert report == "Agent demo:tester finished (1 tool call).\n\nIts report:\n2 passed; ran terminal: pytest"
    assert [tool["function"]["name"] for tool in seen[0]["tools"]] == ["terminal", "python", "edit_file"]
    assert seen[0]["messages"][0]["content"].startswith("You run tests.")
    assert "run_agent" not in json.dumps(seen[0]["tools"])
    assert plugin_agents.run_agent({"agent": "nope", "task": "x"}, session_id = "s").startswith("Error: no agent 'nope'")


def test_routes_refuse_api_keys_and_install_for_the_owner(studio, tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from auth.authentication import authenticated_via_api_key, get_current_subject
    from routes.plugins import router

    app = FastAPI()
    app.include_router(router, prefix = "/api/plugins")
    app.dependency_overrides[get_current_subject] = lambda: "owner"
    app.dependency_overrides[authenticated_via_api_key] = lambda: True
    client = TestClient(app)
    assert client.get("/api/plugins").status_code == 403
    app.dependency_overrides[authenticated_via_api_key] = lambda: False
    preview = client.post("/api/plugins/preview", json = {"source": str(_demo(tmp_path))})
    assert preview.status_code == 200, preview.text
    installed = client.post("/api/plugins/install", json = {"token": preview.json()["token"]})
    assert installed.status_code == 200, installed.text
    assert client.get("/api/plugins").json()["plugins"][0]["name"] == "demo"
    assert client.put("/api/plugins/demo/hooks", json = {"enabled": True}).json()["hooks_enabled"] is True
    assert client.post("/api/plugins/install", json = {"token": "0" * 32}).status_code == 400
    assert client.delete("/api/plugins/demo").status_code == 204
    assert client.get("/api/plugins/demo").status_code == 400


def test_a_run_of_failed_calls_is_counted_from_the_end(monkeypatch):
    from core.inference import tool_call_parser
    from core.inference.tool_loop_controller import ToolLoopController, _ToolCallRecord

    controller = ToolLoopController.__new__(ToolLoopController)
    controller._history = [
        _ToolCallRecord(key = "a", is_error = True, executed = True, action = None),
        _ToolCallRecord(key = "b", is_error = False, executed = True, action = None),
        _ToolCallRecord(key = "c", is_error = True, executed = True, action = None),
        _ToolCallRecord(key = "d", is_error = False, executed = False, action = None),
        _ToolCallRecord(key = "e", is_error = True, executed = True, action = None),
    ]
    assert controller.failure_streak == 2
    assert tool_call_parser.failure_streak_limit() == 8
    monkeypatch.setenv("GANJALF_TOOL_FAILURE_STREAK", "0")
    assert tool_call_parser.failure_streak_limit() == 0
    assert "8 tool calls all failed" in tool_call_parser.FAILURE_STREAK_NUDGE.format(count = 8)



def test_a_stop_ends_a_hook_and_skips_the_rest(studio, tmp_path):
    import time

    root = _write(
        tmp_path / "slow",
        {
            ".claude-plugin/plugin.json": json.dumps({"name": "slow"}),
            "hooks/hooks.json": json.dumps(
                {"hooks": {"PreToolUse": [{"hooks": [{"type": "command", "command": f'"{PY}" -c "import time; time.sleep(30)"'}]}]}}
            ),
        },
    )
    manager.install(manager.preview(str(root))["token"])
    manager.set_hooks_enabled("slow", True)
    cancel = threading.Event()
    threading.Timer(0.5, cancel.set).start()
    started = time.monotonic()
    result = plugin_hooks.before_tool("terminal", {"command": "ls"}, session_id = "s", workdir = str(tmp_path), cancel_event = cancel)
    assert time.monotonic() - started < 5
    assert result == "Error: the run was stopped before this call."


def test_a_stop_ends_a_sub_agent_mid_reply(studio, tmp_path, monkeypatch):
    import time

    from core.inference import tools

    manager.install(manager.preview(str(_demo(tmp_path)))["token"])

    class Slow(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            try:
                for _ in range(200):
                    self.wfile.write(b'data: {"choices": [{"index": 0, "delta": {"content": "."}}]}\n\n')
                    self.wfile.flush()
                    time.sleep(0.1)
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Slow)
    threading.Thread(target = server.serve_forever, daemon = True).start()
    monkeypatch.setattr(tools, "_get_workdir", lambda session_id = None: str(tmp_path))
    cancel = threading.Event()
    threading.Timer(0.5, cancel.set).start()
    started = time.monotonic()
    try:
        result = plugin_agents.run_agent(
            {"agent": "demo:tester", "task": "x"},
            session_id = "s",
            cancel_event = cancel,
            server = (f"http://127.0.0.1:{server.server_port}", None),
        )
    finally:
        server.shutdown()
    assert result == "Error: run_agent was cancelled."
    assert time.monotonic() - started < 5


def test_run_agent_context_budget_and_clipping(monkeypatch):
    monkeypatch.delenv("GANJALF_AGENT_CONTEXT_CHARS", raising = False)
    assert plugin_agents.context_budget_chars(None) == plugin_agents.DEFAULT_CONTEXT_CHARS
    assert plugin_agents.context_budget_chars(4096) == plugin_agents.MIN_CONTEXT_CHARS
    assert plugin_agents.context_budget_chars(65536) == (65536 - 4096) * 9 // 4
    assert plugin_agents.context_budget_chars(10**7) == plugin_agents.MAX_CONTEXT_CHARS
    monkeypatch.setenv("GANJALF_AGENT_CONTEXT_CHARS", "20000")
    assert plugin_agents.context_budget_chars(65536) == 20000

    log = "start\n" + "x" * 20_000 + "\nFAILED test_a"
    clipped = plugin_agents._clip_result(log)
    assert clipped.startswith("start") and clipped.endswith("FAILED test_a") and "chars cut" in clipped
    assert len(clipped) < plugin_agents.MAX_TOOL_RESULT_CHARS + 100

    messages = [{"role": "system", "content": "s"}, {"role": "user", "content": "task"}]
    for i in range(6):
        messages.append({"role": "assistant", "content": "", "tool_calls": [{"id": f"c{i}"}]})
        messages.append({"role": "tool", "tool_call_id": f"c{i}", "content": f"r{i} " + "y" * 6000})
    assert plugin_agents.trim_history(messages, 20_000) > 0
    assert sum(plugin_agents._message_chars(m) for m in messages) <= 20_000
    assert messages[-1]["content"].startswith("r5 ") and messages[-3]["content"].startswith("r4 ")
    assert messages[3]["content"].startswith("[older result shortened")
    assert messages[1]["content"] == "task"


def test_run_agent_keeps_its_conversation_under_the_budget(studio, tmp_path, monkeypatch):
    from core.inference import tools

    manager.install(manager.preview(str(_demo(tmp_path)))["token"])
    monkeypatch.setenv("GANJALF_AGENT_CONTEXT_CHARS", "16000")
    sizes = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            sizes.append(sum(plugin_agents._message_chars(m) for m in body["messages"]))
            if len(sizes) < 8:
                call = {"command": f"cat big{len(sizes)}.log"}
                message = {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{"id": f"c{len(sizes)}", "type": "function", "function": {"name": "terminal", "arguments": json.dumps(call)}}],
                }
            else:
                message = {"role": "assistant", "content": "done"}
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for chunk in _sse_chunks(message):
                self.wfile.write(chunk)
                self.wfile.flush()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target = server.serve_forever, daemon = True).start()
    monkeypatch.setattr(tools, "execute_tool", lambda name, arguments, **kwargs: "z" * 9000)
    monkeypatch.setattr(tools, "_get_workdir", lambda session_id = None: str(tmp_path))
    try:
        report = plugin_agents.run_agent(
            {"agent": "demo:tester", "task": "Read the logs"},
            session_id = "s",
            server = (f"http://127.0.0.1:{server.server_port}", None),
        )
    finally:
        server.shutdown()
    assert report.startswith("Agent demo:tester finished (7 tool calls).")
    # Each result is clipped to 6k; the budget keeps every request near 16k however many rounds run.
    assert max(sizes) <= 16_000 + plugin_agents.MAX_TOOL_RESULT_CHARS
    assert sizes[-1] < 7 * plugin_agents.MAX_TOOL_RESULT_CHARS


def test_built_in_agents_are_always_listed_and_explore_is_read_only(studio, tmp_path, monkeypatch):
    from core.inference import tools

    agents = {agent["id"]: agent for agent in plugin_agents.available_agents()}
    assert {"explore", "general-purpose"} <= set(agents)
    definition = plugin_agents.tool_definition()
    assert definition is not None and "explore:" in definition["function"]["description"].replace("- explore", "explore")
    # explore runs without approval in Auto; general-purpose asks like any writer.
    assert tools.is_high_risk_tool_call("run_agent", {"agent": "explore", "task": "x"}) is False
    assert tools.is_high_risk_tool_call("run_agent", {"agent": "general-purpose", "task": "x"}) is True

    (tmp_path / "app.py").write_text("def answer():\n    return 42\n")
    seen_tools = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen_tools.append(sorted(t["function"]["name"] for t in body.get("tools", [])))
            if len(seen_tools) == 1:
                call = {"pattern": "def answer"}
                message = {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "grep", "arguments": json.dumps(call)}}],
                }
            else:
                tool_text = body["messages"][-1]["content"]
                message = {"role": "assistant", "content": f"Found it: {tool_text.splitlines()[1]}"}
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for chunk in _sse_chunks(message):
                self.wfile.write(chunk)
                self.wfile.flush()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target = server.serve_forever, daemon = True).start()
    monkeypatch.setattr(tools, "_get_workdir", lambda *a, **k: str(tmp_path))
    try:
        report = plugin_agents.run_agent(
            {"agent": "explore", "task": "Where is answer defined?"},
            session_id = "s",
            server = (f"http://127.0.0.1:{server.server_port}", None),
        )
    finally:
        server.shutdown()
    assert seen_tools[0] == ["glob", "grep", "read_file"]
    assert report.startswith("Agent explore finished (1 tool call).")
    assert "app.py:1:def answer():" in report
