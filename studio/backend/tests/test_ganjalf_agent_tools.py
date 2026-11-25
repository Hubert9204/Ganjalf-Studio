"""Ganjalf Claude Code-style tools: todo_write, read_file, grep, glob and background jobs."""

from __future__ import annotations

import threading
import time

import pytest

from core.inference import agent_tools, background_jobs, tools


@pytest.fixture(autouse = True)
def _budget():
    context_token = tools._REQUEST_CONTEXT_TOKENS.set(tools._UNSET_CONTEXT_TOKENS)
    budget_token = tools._REQUEST_RESULT_BUDGET.set(None)
    yield
    tools._REQUEST_CONTEXT_TOKENS.reset(context_token)
    tools._REQUEST_RESULT_BUDGET.reset(budget_token)


@pytest.fixture
def project(tmp_path, monkeypatch):
    root = tmp_path / "project"
    (root / "src").mkdir(parents = True)
    (root / "node_modules" / "three").mkdir(parents = True)
    (root / "src" / "main.ts").write_text(
        "import { Engine } from './engine';\nnew Engine().start();\n"
    )
    (root / "src" / "engine.ts").write_text(
        "export class Engine {\n"
        + "".join(f"  line{i}() {{}}\n" for i in range(1, 600))
        + "  start() {}\n}\n"
    )
    (root / "index.html").write_text("<script type=module src=/src/main.ts></script>\n")
    (root / "node_modules" / "three" / "index.js").write_text("export class Engine {}\n")
    (root / "logo.png").write_bytes(b"\x89PNG\x00\x00binary")
    monkeypatch.setattr(tools, "_get_workdir", lambda *_a, **_k: str(root))
    return root


def run(name, arguments):
    return tools.execute_tool(name, arguments, session_id = "s1")


def test_todo_write_keeps_the_list_and_coaches():
    reply = run(
        "todo_write",
        {
            "todos": [
                {"content": "Scene and player", "status": "completed"},
                {"content": "Camera", "status": "in_progress", "activeForm": "Adding the camera"},
                {"content": "HUD", "status": "pending"},
            ]
        },
    )
    assert (
        reply.startswith("Task list updated (1/3 done)")
        and "[>] Camera" in reply
        and "[x] Scene" in reply
    )
    assert agent_tools.current_todos("s1")[1]["activeForm"] == "Adding the camera"
    assert "exactly one" in run(
        "todo_write",
        {
            "todos": [
                {"content": "a", "status": "in_progress"},
                {"content": "b", "status": "in_progress"},
            ]
        },
    )
    assert "verify the result" in run(
        "todo_write", {"todos": [{"content": "a", "status": "completed"}]}
    )
    assert run("todo_write", {"todos": [{"content": "a", "status": "doing"}]}).startswith("Error")
    assert run("todo_write", {"todos": '[{"content": "a", "status": "pending"}]'}).startswith(
        "Task list"
    )


def test_read_file_numbers_lines_and_pages(project):
    first = run("read_file", {"path": "src/engine.ts"})
    assert first.startswith("     1\texport class Engine {")
    assert "(lines 1-400 of 602; continue with offset=401)" in first
    part = run("read_file", {"path": "src/engine.ts", "offset": 600, "limit": 5})
    assert "   601\t  start() {}" in part and part.endswith("(lines 600-602 of 602)")
    assert "binary" in run("read_file", {"path": "logo.png"})
    assert "does not exist" in run("read_file", {"path": "nope.ts"})
    assert "past the end" in run("read_file", {"path": "src/main.ts", "offset": 99})
    assert "outside" in run("read_file", {"path": "/etc/passwd"})


def test_grep_finds_code_and_skips_dependencies(project):
    hits = run("grep", {"pattern": r"class Engine"})
    assert "src/engine.ts:1:export class Engine {" in hits and "node_modules" not in hits
    assert "node_modules/three/index.js" in run(
        "grep", {"pattern": "class Engine", "path": "node_modules"}
    )
    assert run("grep", {"pattern": "start", "glob": "*.html"}).startswith("No matches")
    assert "src/main.ts" in run(
        "grep", {"pattern": "ENGINE", "ignore_case": True, "files_only": True}
    )
    context = run("grep", {"pattern": "line300", "context": 1})
    assert "src/engine.ts-300-" in context and "src/engine.ts:301:" in context
    assert "invalid regular expression" in run("grep", {"pattern": "start("})


def test_glob_lists_newest_first(project):
    time.sleep(0.01)
    (project / "src" / "hud.ts").write_text("export {};\n")
    listing = run("glob", {"pattern": "src/**/*.ts"})
    assert listing.splitlines()[1].startswith("src/hud.ts")
    assert "node_modules" not in run("glob", {})
    assert run("glob", {"pattern": "*.py"}).startswith("No files")


def test_offered_beside_terminal_and_always_safe(monkeypatch):
    names = {t["function"]["name"] for t in agent_tools.code_agent_tools()}
    assert names == agent_tools.CODE_AGENT_TOOL_NAMES
    for name in names:
        assert tools.is_always_safe_tool(name)
        assert not tools.is_high_risk_tool_call(name, {})
    monkeypatch.setenv("GANJALF_AGENT_TOOLS", "0")
    assert agent_tools.code_agent_tools() == []
    params = tools.TERMINAL_TOOL["function"]["parameters"]["properties"]
    assert params["run_in_background"]["type"] == "boolean"


def test_background_job_lifecycle():
    started = threading.Event()

    def fake_run(cancel, append, timeout):
        append("VITE ready\n")
        append("  Local: http://localhost:5173/\n")
        started.set()
        while not cancel.wait(0.05):
            pass
        append("bye\n")
        return "Execution cancelled."

    reply = background_jobs.start("npm run dev", "s2", fake_run)
    job_id = reply.split("Started background job ", 1)[1].split(":", 1)[0]
    assert "http://localhost:5173/" in reply and "terminal_output" in reply
    status = background_jobs.output({"id": job_id}, "s2")
    assert "Status: running" in status and "No new output." in status
    assert background_jobs.output({"id": job_id}, "other-chat").startswith(
        "Error: no background job"
    )
    stopped = background_jobs.kill({"id": job_id}, "s2")
    assert stopped.startswith(f"Stopped background job {job_id}")
    final = background_jobs.output({"id": job_id}, "s2")
    assert "ended (stopped)" in final and "bye" in final
    assert "already ended" in background_jobs.kill({"id": job_id}, "s2")


def test_background_job_that_fails_at_once_reports_its_exit():
    reply = background_jobs.start(
        "npm run nope",
        "s3",
        lambda c, a, t: (a("missing script\n"), "Exit code 1:\nmissing script")[1],
    )
    assert "already ended" in reply and "Exit code 1" in reply and "missing script" in reply


def test_background_job_limit_and_id_lookup():
    gate = threading.Event()

    def long_run(cancel, append, timeout):
        cancel.wait()
        return "Execution cancelled."

    ids = []
    for _ in range(background_jobs.MAX_JOBS_PER_SESSION):
        reply = background_jobs.start("sleep", "s4", long_run)
        ids.append(reply.split("Started background job ", 1)[1].split(":", 1)[0])
    assert background_jobs.start("one more", "s4", long_run).startswith("Error:")
    assert "pass id" in background_jobs.output({}, "s4")
    for job_id in ids:
        background_jobs.kill({"id": job_id}, "s4")
    gate.set()


def test_terminal_run_in_background_uses_the_real_terminal(project):
    reply = run("terminal", {"command": "echo ready; sleep 30", "run_in_background": True})
    if "Execution error" in reply or "Blocked" in reply:
        pytest.skip(f"terminal unavailable here: {reply[:120]}")
    job_id = reply.split("job ", 1)[1].split(":", 1)[0]
    assert "ready" in reply or "ready" in run("terminal_output", {"id": job_id, "wait_seconds": 5})
    assert "Status: running" in run("terminal_output", {"id": job_id})
    assert run("terminal_kill", {"id": job_id}).startswith("Stopped")


def test_job_panel_lists_addresses_and_stops_only_own_jobs(monkeypatch):
    def server(cancel, append, timeout):
        append("  ➜  Local:   http://localhost:5173/\n")
        append("  ➜  Network: http://0.0.0.0:5173/\n")
        cancel.wait()
        return "Execution cancelled."

    monkeypatch.setattr(background_jobs, "_account", lambda: "alice")
    reply = background_jobs.start("npx vite --host 0.0.0.0", "panel", server)
    job_id = reply.split("Started background job ", 1)[1].split(":", 1)[0]
    listed = [job for job in background_jobs.account_jobs() if job["id"] == job_id][0]
    assert listed["running"] and listed["addresses"] == ["http://localhost:5173/"]
    monkeypatch.setattr(background_jobs, "_account", lambda: "bob")
    assert all(job["id"] != job_id for job in background_jobs.account_jobs())
    assert background_jobs.stop_for_account(job_id) is None
    monkeypatch.setattr(background_jobs, "_account", lambda: "alice")
    assert background_jobs.stop_for_account(job_id) == f"Stopped background job {job_id}."
    listed = [job for job in background_jobs.account_jobs() if job["id"] == job_id][0]
    assert not listed["running"] and listed["status"] == "ended (stopped)"


def test_job_routes(monkeypatch):
    import asyncio

    from routes import inference as routes

    monkeypatch.setattr(background_jobs, "account_jobs", lambda: [{"id": "bg9"}])
    monkeypatch.setattr(
        background_jobs,
        "stop_for_account",
        lambda job_id: "Stopped background job bg9." if job_id == "bg9" else None,
    )
    assert asyncio.run(routes.get_background_jobs(current_subject = "u")) == {"jobs": [{"id": "bg9"}]}
    assert asyncio.run(routes.stop_background_job("bg9", current_subject = "u"))[
        "message"
    ].startswith("Stopped")
    with pytest.raises(Exception):
        asyncio.run(routes.stop_background_job("bg1", current_subject = "u"))


def test_plan_mode_offers_only_reading_and_the_plan_tool():
    import asyncio

    from models.inference import ChatCompletionRequest
    from routes.inference import _select_request_tools

    chat = ChatCompletionRequest(
        model = "m",
        messages = [{"role": "user", "content": "build a game"}],
        enable_tools = True,
        enabled_tools = ["terminal", "python", "edit_file", "web_search"],
        plan_mode = True,
    )
    names = [
        t["function"]["name"]
        for t in asyncio.run(_select_request_tools(chat, tools_on = True, mcp_allowed = False))
    ]
    assert set(names) == {"web_search", "read_file", "grep", "glob", "todo_write", "exit_plan_mode"}
    assert names[-1] == "exit_plan_mode"
    assert tools.is_always_safe_tool("exit_plan_mode")


def test_exit_plan_mode_ends_the_tool_rounds():
    from core.inference.tool_loop_controller import ToolLoopController

    controller = ToolLoopController(
        tools = [agent_tools.EXIT_PLAN_MODE_TOOL, agent_tools.READ_FILE_TOOL]
    )
    decision = controller.prepare_call(
        {"id": "p1", "function": {"name": "exit_plan_mode", "arguments": {"plan": "1. Scene"}}}
    )
    reply = tools.execute_tool("exit_plan_mode", {"plan": "1. Scene"}, session_id = "s")
    # The card shows the plan from the call's arguments; the result only says to end the turn.
    assert reply.startswith(agent_tools.PLAN_APPROVAL_TAG) and "Do not repeat" in reply
    controller.record_result(decision, reply)
    assert controller.force_final_answer and controller.active_tools() == []
    assert controller.awaiting_user
    assert tools.execute_tool("exit_plan_mode", {}, session_id = "s").startswith("Error")


# --- command shapes: `&` servers, compiler error batches, removed definitions ---------------

from core.inference import command_shapes as shapes


@pytest.mark.parametrize(
    "command, expected",
    [
        (
            "nohup npx vite --port 5173 > vite.log 2>&1 & echo $! > vite.pid",
            "npx vite --port 5173 2>&1 | tee vite.log",
        ),
        (
            "cd /home/u/Test\\ Game && nohup npx vite --port 5173 > vite.log 2>&1 &",
            "cd /home/u/Test\\ Game && npx vite --port 5173 2>&1 | tee vite.log",
        ),
        ("npm run dev &", "npm run dev"),
        (
            "python -m http.server 8000 >> s.log 2>&1 & sleep 2",
            "python -m http.server 8000 2>&1 | tee -a s.log",
        ),
        ("node server.js > /dev/null 2>&1 & disown", "node server.js"),
        ("npm run dev &>dev.log &", "npm run dev 2>&1 | tee dev.log"),
    ],
)
def test_a_server_left_with_ampersand_becomes_a_background_job(command, expected):
    assert shapes.promoted_background(command) == expected


@pytest.mark.parametrize(
    "command",
    [
        "npm install && npm run build",
        "npx tsc --noEmit 2>&1 | head -20",
        "npm run dev & sleep 3 && curl -s localhost:5173",
        "a & b &",
        "echo 'a & b'",
        "ls >&2",
        "cat <<EOF\n&\nEOF",
    ],
)
def test_other_commands_run_as_written(command):
    assert shapes.promoted_background(command) is None


def test_leftover_ampersand_gets_a_note():
    assert shapes.leaves_background_process("npm run dev & sleep 3 && curl -s localhost:5173")
    assert not shapes.leaves_background_process("npm i && npm run build 2>&1")


def test_terminal_promotes_an_ampersand_server(project):
    reply = run("terminal", {"command": "nohup sleep 30 > s.log 2>&1 & echo $! > s.pid"})
    if "Execution error" in reply or "Blocked" in reply:
        pytest.skip(f"terminal unavailable here: {reply[:120]}")
    assert reply.startswith("The command ended with `&`")
    job_id = reply.split("Started background job ", 1)[1].split(":", 1)[0]
    assert "Status: running" in run("terminal_output", {"id": job_id})
    assert run("terminal_kill", {"id": job_id}).startswith("Stopped")


def test_compile_errors_ask_for_one_batch():
    out = (
        "src/ui/HUD.ts(12,5): error TS2339: Property 'log' does not exist.\n"
        "src/engine/Audio.ts(80,3): error TS2322: Type 'x' is not assignable.\n"
    )
    assert "2 errors listed" in shapes.compile_errors_note(out)
    assert shapes.compile_errors_note("src/a.ts(1,1): error TS1005: ';' expected.") == ""


def test_an_edit_that_drops_methods_says_so():
    before = (
        "export class HUD {\n"
        "  log(msg: string): void {\n    this.lines.push(msg);\n  }\n"
        "  private addFrag(text: string) {\n    this.frags.push(text);\n  }\n"
        "  toggleShop() { this.shop = !this.shop; }\n"
        "  draw() {\n    if (this.shop) {}\n    this.log('x');\n  }\n"
        "}\n"
    )
    after = "export class HUD {\n  draw() {\n    if (this.shop) {}\n    this.log('x');\n  }\n}\n"
    note = shapes.removed_definitions_note("src/ui/HUD.ts", before, after)
    assert "removed: log, addFrag, toggleShop" in note
    assert "Still called in this file: log" in note
    assert shapes.removed_definitions_note("notes.md", before, after) == ""
    assert shapes.removed_definitions_note("src/ui/HUD.ts", before, before + "\n") == ""


def test_edit_file_reports_removed_definitions(project):
    run(
        "edit_file",
        {
            "path": "m.py",
            "edits": [
                {
                    "old_string": "",
                    "new_string": "def a():\n    return 1\n\n\ndef b():\n    return a()\n",
                }
            ],
        },
    )
    reply = run(
        "edit_file",
        {
            "path": "m.py",
            "edits": [{"old_string": "def a():\n    return 1\n\n\n", "new_string": ""}],
        },
    )
    assert "This edit removed: a. Still called in this file: a." in reply


def test_plan_mode_is_said_in_the_system_text_not_only_in_the_tool_list(monkeypatch):
    """Qwen 27B, given only read tools, decided it could not write files and pasted the program."""
    from routes import inference as routes

    monkeypatch.setattr(
        routes,
        "_enabled_agent_skills",
        lambda: [{"name": "coding-agent", "description": "Build programs.", "valid": True}],
    )
    full = [
        {"type": "function", "function": t["function"]}
        for t in tools.ALL_TOOLS
        if t["function"]["name"] in ("terminal", "web_search")
    ]
    planned = agent_tools.apply_plan_mode(
        full + [{"type": "function", "function": {"name": "edit_file"}}]
    )
    text = routes._build_tool_action_nudge(tools = planned, model_name = "Qwen3.8-27B-GGUF")
    assert text.startswith("PLAN MODE IS ON")
    assert "exit_plan_mode" in text and "do not ask the user to copy code" in text
    assert "No local python or terminal tool is available" not in text
    normal = routes._build_tool_action_nudge(tools = full, model_name = "Qwen3.8-27B-GGUF")
    assert "PLAN MODE" not in normal


def test_agent_rounds_think_within_a_budget_unless_the_user_set_one(monkeypatch):
    from core.inference import llama_cpp

    monkeypatch.delenv("GANJALF_AGENT_THINKING_BUDGET", raising = False)
    assert llama_cpp.agent_thinking_budget() == 6144
    monkeypatch.setenv("GANJALF_AGENT_THINKING_BUDGET", "0")
    assert llama_cpp.agent_thinking_budget() is None
    monkeypatch.setenv("GANJALF_AGENT_THINKING_BUDGET", "2048")
    assert llama_cpp.agent_thinking_budget() == 2048


def test_the_plan_card_is_not_repeated_as_text():
    reply = tools.execute_tool("exit_plan_mode", {"plan": "1. Scene"}, session_id = "s")
    assert (
        "Do not repeat or summarise the plan" in reply
        and "write the plan as your answer" not in reply
    )
