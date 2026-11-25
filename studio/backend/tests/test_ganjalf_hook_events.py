"""The four plugin hook events that used to be accepted but never run."""

import json
import time

from core.plugins import hooks


def _wire(monkeypatch, tmp_path, events):
    # One file per hook run: hooks run concurrently, and two `cat >> same-file` interleave.
    log = tmp_path / "events"
    log.mkdir()
    registry = {
        event: [
            (
                "demo",
                matcher,
                {
                    "type": "command",
                    "command": f'f=$(mktemp {log}/.ev.XXXXXX); cat > "$f"; mv "$f" "$f.json"',
                },
            )
        ]
        for event, matcher in events.items()
    }
    monkeypatch.setattr(hooks, "_all_hooks", lambda: registry)
    monkeypatch.setattr(hooks, "workdir_for", lambda session_id: str(tmp_path))
    monkeypatch.setattr("core.plugins.manager.expand", lambda command, plugin: command)
    monkeypatch.setattr("core.plugins.manager.plugin_dir", lambda plugin: tmp_path)
    monkeypatch.setattr("core.plugins.manager.data_dir", lambda plugin: tmp_path)
    return log


def _events(
    log,
    count = 1,
    wait = 5.0,
):
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline and len(list(log.glob("*.json"))) < count:
        time.sleep(0.05)
    return {
        event["hook_event_name"]: event
        for event in (json.loads(path.read_text()) for path in log.glob("*.json"))
    }


def test_subagent_stop_and_session_end_run_with_their_payload(monkeypatch, tmp_path):
    log = _wire(monkeypatch, tmp_path, {"SubagentStop": "", "SessionEnd": ""})
    hooks.subagent_stop("s1", "explore", "Agent explore finished (3 tool calls).")
    hooks.session_end("t9", "clear")
    events = _events(log, count = 2)
    first, second = events["SubagentStop"], events["SessionEnd"]
    assert first["agent_type"] == "explore"
    assert "finished" in first["last_assistant_message"]
    assert second == {
        "hook_event_name": "SessionEnd",
        "cwd": str(tmp_path),
        "session_id": "t9",
        "reason": "clear",
    }


def test_pre_compact_and_notification_match_on_their_kind(monkeypatch, tmp_path):
    log = _wire(monkeypatch, tmp_path, {"PreCompact": "auto", "Notification": "permission_prompt"})
    hooks.pre_compact("s", "manual")  # matcher is "auto": skipped
    hooks.notification("s", "done", "idle_prompt")  # matcher is permission_prompt: skipped
    hooks.pre_compact("s", "auto")
    hooks.notification("s", "Ganjalf needs your permission to use terminal", "permission_prompt")
    _events(log, count = 2)
    time.sleep(0.3)  # a skipped hook that ran anyway would show up by now
    assert len(list(log.glob("*.json"))) == 2
    by_name = _events(log)
    assert sorted(by_name) == ["Notification", "PreCompact"]
    assert by_name["PreCompact"]["trigger"] == "auto"
    assert by_name["Notification"]["notification_type"] == "permission_prompt"


def test_parallel_agents_each_report_and_fire_subagent_stop(monkeypatch):
    from core.plugins import agents

    seen = []
    monkeypatch.setattr(agents, "run_agent", lambda task, **kw: f"report for {task['task']}")
    monkeypatch.setattr(
        agents, "_subagent_stop", lambda session, task, report: seen.append(task["agent"])
    )
    out = agents.run_agents(
        {"tasks": [{"agent": "explore", "task": "src"}, {"agent": "explore", "task": "tests"}]},
        session_id = "s",
    )
    assert (
        "## 1. explore: src\nreport for src" in out
        and "## 2. explore: tests\nreport for tests" in out
    )
    assert seen == ["explore", "explore"]
    assert "at most" in agents.run_agents(
        {"tasks": [{"agent": "a", "task": "t"}] * 5}, session_id = "s"
    )


def test_background_agents_run_as_a_job(monkeypatch):
    from core.inference import background_jobs
    from core.plugins import agents

    monkeypatch.setattr(agents, "run_agent", lambda task, **kw: "the report")
    monkeypatch.setattr(agents, "_subagent_stop", lambda *a: None)
    reply = agents.run_agents(
        {"agent": "explore", "task": "map src", "run_in_background": True}, session_id = "bgs"
    )
    assert (
        "ackground job bg" in reply
    )  # "Started background job" or, this fast, "Background job … ended"
    job_id = "bg" + reply.split("job bg", 1)[1].split(":", 1)[0].split(" ", 1)[0]
    out = background_jobs.output({"id": job_id, "wait_seconds": 5}, "bgs")
    assert "the report" in reply + out  # a fast job hands its output over in the start reply


def test_explore_in_parallel_needs_no_approval_but_a_writer_among_them_does():
    from core.inference import tools

    read_only = {"tasks": [{"agent": "explore", "task": "a"}, {"agent": "explore", "task": "b"}]}
    mixed = {
        "tasks": [{"agent": "explore", "task": "a"}, {"agent": "general-purpose", "task": "b"}]
    }
    assert tools._read_only_sub_agent("run_agent", read_only)
    assert not tools._read_only_sub_agent("run_agent", mixed)
