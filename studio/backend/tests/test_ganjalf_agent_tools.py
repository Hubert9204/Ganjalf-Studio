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
    (root / "src" / "main.ts").write_text("import { Engine } from './engine';\nnew Engine().start();\n")
    (root / "src" / "engine.ts").write_text(
        "export class Engine {\n" + "".join(f"  line{i}() {{}}\n" for i in range(1, 600)) + "  start() {}\n}\n"
    )
    (root / "index.html").write_text("<script type=module src=/src/main.ts></script>\n")
    (root / "node_modules" / "three" / "index.js").write_text("export class Engine {}\n")
    (root / "logo.png").write_bytes(b"\x89PNG\x00\x00binary")
    monkeypatch.setattr(tools, "_get_workdir", lambda *_a, **_k: str(root))
    return root


def run(name, arguments):
    return tools.execute_tool(name, arguments, session_id = "s1")


def test_todo_write_keeps_the_list_and_coaches():
    reply = run("todo_write", {"todos": [
        {"content": "Scene and player", "status": "completed"},
        {"content": "Camera", "status": "in_progress", "activeForm": "Adding the camera"},
        {"content": "HUD", "status": "pending"},
    ]})
    assert reply.startswith("Task list updated (1/3 done)") and "[>] Camera" in reply and "[x] Scene" in reply
    assert agent_tools.current_todos("s1")[1]["activeForm"] == "Adding the camera"
    assert "exactly one" in run("todo_write", {"todos": [
        {"content": "a", "status": "in_progress"}, {"content": "b", "status": "in_progress"}]})
    assert "verify the result" in run("todo_write", {"todos": [{"content": "a", "status": "completed"}]})
    assert run("todo_write", {"todos": [{"content": "a", "status": "doing"}]}).startswith("Error")
    assert run("todo_write", {"todos": '[{"content": "a", "status": "pending"}]'}).startswith("Task list")


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
    assert "node_modules/three/index.js" in run("grep", {"pattern": "class Engine", "path": "node_modules"})
    assert run("grep", {"pattern": "start", "glob": "*.html"}).startswith("No matches")
    assert "src/main.ts" in run("grep", {"pattern": "ENGINE", "ignore_case": True, "files_only": True})
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
    assert background_jobs.output({"id": job_id}, "other-chat").startswith("Error: no background job")
    stopped = background_jobs.kill({"id": job_id}, "s2")
    assert stopped.startswith(f"Stopped background job {job_id}")
    final = background_jobs.output({"id": job_id}, "s2")
    assert "ended (stopped)" in final and "bye" in final
    assert "already ended" in background_jobs.kill({"id": job_id}, "s2")


def test_background_job_that_fails_at_once_reports_its_exit():
    reply = background_jobs.start("npm run nope", "s3", lambda c, a, t: (a("missing script\n"), "Exit code 1:\nmissing script")[1])
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
