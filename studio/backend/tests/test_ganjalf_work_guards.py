"""Ganjalf soft guardrails: verify-after-writes note and the one-time check_page gate."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_BACKEND_DIR = str(Path(__file__).resolve().parent.parent)
for _path in (_BACKEND_DIR, str(Path(__file__).resolve().parent)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from core.inference.work_guards import (  # noqa: E402
    WorkLedger,
    runs_something,
    written_paths,
)


@pytest.fixture(autouse = True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("GANJALF_VERIFY_AFTER_WRITES", raising = False)
    monkeypatch.delenv("GANJALF_CHECK_PAGE_GATE", raising = False)


def _edit(path):
    return ("edit_file", {"path": path, "edits": [{"old_string": "", "new_string": "x"}]})


@pytest.mark.parametrize(
    "tool, args, expected",
    [
        ("edit_file", {"path": "index.html"}, ["index.html"]),
        ("terminal", {"command": "cat > app.js <<'EOF'\nx\nEOF"}, ["app.js"]),
        ("terminal", {"command": "echo hi >> notes.md && ls 2>&1"}, ["notes.md"]),
        ("terminal", {"command": "npm run build > /dev/null 2>&1"}, []),
        ("terminal", {"command": "printf x | tee -a log.txt"}, ["log.txt"]),
        ("terminal", {"command": "sed -i 's/a/b/' src/main.ts"}, ["src/main.ts"]),
        ("python", {"code": "open('out.css', 'w').write('a{}')"}, ["out.css"]),
        ("python", {"code": "from pathlib import Path\nPath('a.py').write_text('x')"}, ["a.py"]),
        ("python", {"code": "print(open('a.txt').read())"}, []),
        ("web_search", {"query": "x > y.html"}, []),
    ],
)
def test_written_paths(tool, args, expected):
    assert written_paths(tool, args) == expected


@pytest.mark.parametrize(
    "tool, args, expected",
    [
        ("terminal", {"command": "pytest -q"}, True),
        ("terminal", {"command": "cd app && npm run build"}, True),
        ("terminal", {"command": "npx tsc --noEmit"}, True),
        ("terminal", {"command": "python3 main.py"}, True),
        ("terminal", {"command": "python -m pip install rich"}, False),
        ("terminal", {"command": "go test ./..."}, True),
        ("terminal", {"command": "./run.sh"}, True),
        ("terminal", {"command": "ls -la && cat a.py"}, False),
        ("terminal", {"command": "npm install"}, False),
        ("python", {"code": "print(1 + 1)"}, True),
        ("python", {"code": "open('a.txt','w').write('x')"}, False),
        ("python", {"code": "open('a.txt','w').write('x')\nprint(open('a.txt').read())"}, True),
        ("check_page", {"path": "index.html"}, True),
        ("edit_file", {"path": "a.py"}, False),
    ],
)
def test_runs_something(tool, args, expected):
    assert runs_something(tool, args) is expected


def test_note_after_n_writes_then_starts_over(monkeypatch):
    monkeypatch.setenv("GANJALF_VERIFY_AFTER_WRITES", "3")
    ledger = WorkLedger()
    notes = [ledger.note_call(*_edit(f"f{i}.py"), failed = False) for i in range(7)]
    assert [bool(n) for n in notes] == [False, False, True, False, False, True, False]
    assert "3 file writes in a row" in notes[2]
    assert "carry on" in notes[2]


def test_a_run_resets_the_count_and_failed_edits_do_not_count(monkeypatch):
    monkeypatch.setenv("GANJALF_VERIFY_AFTER_WRITES", "2")
    ledger = WorkLedger()
    assert ledger.note_call(*_edit("a.py"), failed = False) == ""
    assert ledger.note_call("terminal", {"command": "python a.py"}, failed = True) == ""
    assert ledger.note_call(*_edit("b.py"), failed = False) == ""
    assert ledger.note_call(*_edit("c.py"), failed = True) == ""
    assert ledger.note_call("web_search", {"query": "x"}, failed = False) == ""
    assert ledger.note_call(*_edit("d.py"), failed = False) != ""


@pytest.mark.parametrize("value", ["0", "off"])
def test_the_note_can_be_turned_off(monkeypatch, value):
    monkeypatch.setenv("GANJALF_VERIFY_AFTER_WRITES", value)
    ledger = WorkLedger()
    assert all(ledger.note_call(*_edit(f"f{i}.py"), failed = False) == "" for i in range(20))


def test_default_limit_is_six():
    ledger = WorkLedger()
    notes = [ledger.note_call(*_edit(f"f{i}.py"), failed = False) for i in range(6)]
    assert [bool(n) for n in notes] == [False] * 5 + [True]


def test_page_reminder_fires_once_and_any_check_clears_it(tmp_path):
    ledger = WorkLedger()
    ledger.note_call(*_edit("index.html"), failed = False)
    ledger.note_call(*_edit("style.css"), failed = False)
    reminder = ledger.check_page_reminder(offered = True, workdir = str(tmp_path))
    assert reminder and "index.html, style.css" in reminder and "say so in one line and finish" in reminder
    # Once per response, whatever the model does next.
    assert ledger.check_page_reminder(offered = True, workdir = str(tmp_path)) is None

    fresh = WorkLedger()
    fresh.note_call(*_edit("index.html"), failed = False)
    fresh.note_call("check_page", {"path": "index.html"}, failed = True)  # unavailable / failed
    assert fresh.check_page_reminder(offered = True, workdir = str(tmp_path)) is None


def test_page_reminder_needs_check_page_offered_and_the_gate_on(tmp_path, monkeypatch):
    ledger = WorkLedger()
    ledger.note_call(*_edit("index.html"), failed = False)
    assert ledger.check_page_reminder(offered = False, workdir = str(tmp_path)) is None
    monkeypatch.setenv("GANJALF_CHECK_PAGE_GATE", "0")
    assert ledger.check_page_reminder(offered = True, workdir = str(tmp_path)) is None


def test_scripts_count_only_beside_an_html_page(tmp_path):
    (tmp_path / "server").mkdir()
    (tmp_path / "game" / "src").mkdir(parents = True)
    (tmp_path / "game" / "index.html").write_text("<html></html>")

    backend = WorkLedger()
    backend.note_call(*_edit("server/app.ts"), failed = False)
    backend.note_call(*_edit("server/notes.py"), failed = False)
    assert backend.check_page_reminder(offered = True, workdir = str(tmp_path)) is None

    page = WorkLedger()
    page.note_call(*_edit("game/src/main.js"), failed = False)
    assert "game/src/main.js" in page.check_page_reminder(offered = True, workdir = str(tmp_path))


def test_controller_puts_the_note_only_in_the_model_copy(monkeypatch):
    from core.inference.tool_loop_controller import ToolLoopController

    monkeypatch.setenv("GANJALF_VERIFY_AFTER_WRITES", "1")
    controller = ToolLoopController(
        tools = [{"type": "function", "function": {"name": "edit_file", "parameters": {"type": "object"}}}],
    )
    decision = controller.prepare_call(
        {"id": "c1", "function": {"name": "edit_file", "arguments": {"path": "a.py", "edits": []}}}
    )
    completion = controller.record_result(decision, "Edited a.py")
    assert "file writes in a row" in completion.model_message()["content"]
    assert "file writes in a row" not in completion.tool_end_payload()["result"]


# --- the gate inside the real llama tool loop (fake llama-server streams) -------------------


def _tools(*names):
    return [
        {"type": "function", "function": {"name": n, "parameters": {"type": "object", "properties": {}}}}
        for n in names
    ]


def _run(monkeypatch, tmp_path, streams, tool_names):
    from test_llama_cpp_tool_loop import _backend_and_payloads, _record_tool_calls

    backend, payloads = _backend_and_payloads(monkeypatch, streams)
    calls = _record_tool_calls(monkeypatch, lambda name: f"ok {name}")
    monkeypatch.setattr("core.inference.tools._get_workdir", lambda *_a, **_k: str(tmp_path))
    events = list(
        backend.generate_chat_completion_with_tools(
            messages = [{"role": "user", "content": "Make a page."}],
            tools = _tools(*tool_names),
            max_tool_iterations = 10,
            permission_mode = "off",
        )
    )
    return events, payloads, calls


def _stream_call(name, args, cid):
    from test_llama_cpp_tool_loop import _structured_tool_call

    return _structured_tool_call(name, args, cid)


def _stream_text(text):
    from test_llama_cpp_tool_loop import _done, _sse

    return [_sse({"content": text}), _done()]


def _gate_messages(payloads):
    return [
        m for p in payloads for m in p.get("messages", [])
        if m.get("role") == "user" and "did not run check_page" in str(m.get("content"))
    ]


def test_loop_sends_the_agent_back_once_then_lets_it_finish(monkeypatch, tmp_path):
    edit = {"path": "index.html", "edits": [{"old_string": "", "new_string": "<html></html>"}]}
    streams = [
        _stream_call("edit_file", edit, "c1"),
        _stream_text("Done, the page is ready."),
        _stream_text("Still done, check_page is not needed."),  # ignores the reminder
    ]
    events, payloads, calls = _run(monkeypatch, tmp_path, streams, ["edit_file", "check_page"])
    assert [c[0] for c in calls] == ["edit_file"]
    assert len(payloads) == 3  # edit, first answer, one more turn after the reminder: no loop
    assert len(_gate_messages(payloads[2:])) == 1
    assert any(e.get("type") == "status" and "Checking the page" in str(e.get("text")) for e in events)


def test_loop_skips_the_gate_without_check_page_or_after_a_check(monkeypatch, tmp_path):
    edit = {"path": "index.html", "edits": [{"old_string": "", "new_string": "<html></html>"}]}
    streams = [_stream_call("edit_file", edit, "c1"), _stream_text("Done.")]
    _events, payloads, _calls = _run(monkeypatch, tmp_path, streams, ["edit_file"])
    assert len(payloads) == 2 and not _gate_messages(payloads)

    streams = [
        _stream_call("edit_file", edit, "c1"),
        _stream_call("check_page", {"path": "index.html"}, "c2"),
        _stream_text("Done, no errors."),
    ]
    _events, payloads, calls = _run(monkeypatch, tmp_path, streams, ["edit_file", "check_page"])
    assert [c[0] for c in calls] == ["edit_file", "check_page"]
    assert len(payloads) == 3 and not _gate_messages(payloads)


# --- point 4: a cut build/test log keeps its errors and last lines ---------------------------


def _build_log():
    lines = [f"compiling module {i} ... ok" for i in range(3000)]
    lines[2200] = "src/app.ts(12,5): error TS2304: Cannot find name 'foo'."
    lines[2600] = "npm ERR! code ELIFECYCLE"
    lines += ["", "Build failed with 2 errors.", "exit status 1"]
    return "\n".join(lines)


def test_digest_keeps_error_lines_and_the_tail():
    from core.inference.tools import _output_digest

    log = _build_log()
    digest = _output_digest(log, 16_000)
    assert "2201: src/app.ts(12,5): error TS2304" in digest
    assert "2601: npm ERR! code ELIFECYCLE" in digest
    assert digest.rstrip().endswith("exit status 1")
    assert len(digest) < 16_000 * 0.45
    assert _output_digest("short", 16_000) == ""
    assert _output_digest(log, 1_000) == ""  # too little room: head only, as before
    assert "error TS2304" in _output_digest(log, 16_000, numbered = False)
    assert "2201:" not in _output_digest(log, 16_000, numbered = False)


def test_truncate_with_digest_stays_within_the_room(monkeypatch):
    from core.inference import tools

    monkeypatch.setattr(tools, "_request_result_room", lambda: None)
    log = _build_log()
    plain = tools._truncate(log, 16_000)
    with_digest = tools._truncate(log, 16_000, digest = True)
    assert "error TS2304" not in plain and "error TS2304" in with_digest
    assert with_digest.startswith("compiling module 0 ... ok")
    assert "truncated to" in with_digest
    # Same total budget: the head gives up the room the digest takes.
    assert abs(len(with_digest) - len(plain)) < 400


def test_sandbox_env_quiets_npm():
    import inspect

    from core.inference import tools

    source = inspect.getsource(tools)
    for key in ("NO_COLOR", "npm_config_progress", "npm_config_fund", "npm_config_audit", "npm_config_update_notifier"):
        assert source.count(f'"{key}"') >= 2, key
