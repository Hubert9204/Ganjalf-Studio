"""The work record kept when a long agent run is compacted."""

import json

from core.inference import llama_cpp
from core.inference.work_state import HEADER, with_work_state, work_state_block


def _call(cid, name, args):
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": cid,
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(args)},
            }
        ],
    }


def _result(cid, text):
    return {"role": "tool", "tool_call_id": cid, "content": text}


def _run():
    return [
        {"role": "system", "content": "You are a coding agent."},
        {"role": "user", "content": "Build the game."},
        _call(
            "a",
            "todo_write",
            {
                "todos": [
                    {"content": "Scaffold Vite", "status": "completed"},
                    {"content": "Write HUD", "status": "in_progress"},
                ]
            },
        ),
        _result("a", "Task list updated."),
        _call(
            "b",
            "edit_file",
            {
                "path": "src/ui/HUD.ts",
                "edits": [{"old_string": "", "new_string": "export class HUD {}"}],
            },
        ),
        _result("b", "Created src/ui/HUD.ts"),
        _call("c", "terminal", {"command": "npx tsc --noEmit 2>&1 | head -20"}),
        _result("c", "src/ui/HUD.ts(3,1): error TS2304: Cannot find name 'x'."),
        _call("d", "terminal", {"command": "npx vite --port 5173", "run_in_background": True}),
        _result(
            "d",
            "Started background job bg1: npx vite --port 5173\n\nOutput so far:\n  Local: http://localhost:5173/",
        ),
        _call(
            "e",
            "edit_file",
            {"path": "src/ui/HUD.ts", "edits": [{"old_string": "x", "new_string": "y"}]},
        ),
        _result("e", "Edited src/ui/HUD.ts (1 replacement)"),
    ]


def test_the_record_lists_tasks_files_checks_and_servers():
    block = work_state_block(_run())
    assert block.startswith(HEADER)
    assert "- [x] Scaffold Vite" in block and "- [~] Write HUD" in block
    assert "src/ui/HUD.ts (created)" in block
    assert "`npx tsc --noEmit 2>&1 | head -20` → errors in output" in block
    assert "bg1: npx vite --port 5173 at http://localhost:5173/" in block


def test_a_stopped_job_and_a_chat_without_tools_leave_nothing_stale():
    messages = _run() + [
        _call("f", "terminal_kill", {"id": "bg1"}),
        _result("f", "Stopped background job bg1."),
    ]
    assert "Still running" not in work_state_block(messages)
    assert work_state_block([{"role": "user", "content": "hi"}]) == ""


def test_the_record_goes_into_the_system_message():
    out = with_work_state(
        [{"role": "system", "content": "Base."}, {"role": "user", "content": "go"}], "REC"
    )
    assert out[0]["content"] == "Base.\n\nREC" and out[1]["content"] == "go"
    assert with_work_state([{"role": "user", "content": "go"}], "REC")[0] == {
        "role": "system",
        "content": "REC",
    }


def _count(messages):
    return sum(len(json.dumps(m)) for m in messages) // 4


def test_a_fit_that_drops_turns_keeps_the_record_of_the_dropped_work():
    messages = _run() + [{"role": "user", "content": "Now add the inventory window. " + "x" * 400}]
    full = _count(messages)
    fitted, truncation = llama_cpp._fit_with_instruction_pins(
        messages,
        context_length = full // 2 + 200,
        max_tokens = 100,
        count_tokens = _count,
        context_policy = "rolling",
    )
    assert truncation and truncation["dropped_messages"] > 0
    system = fitted[0]["content"]
    assert HEADER in system and "src/ui/HUD.ts" in system
    # Same input, same record: the prefix stays cacheable.
    again, _ = llama_cpp._fit_with_instruction_pins(
        messages,
        context_length = full // 2 + 200,
        max_tokens = 100,
        count_tokens = _count,
        context_policy = "rolling",
    )
    assert again[0]["content"] == system


def test_a_fit_that_drops_nothing_adds_nothing():
    messages = _run()
    fitted, _ = llama_cpp._fit_with_instruction_pins(
        messages, context_length = 100000, max_tokens = 100, count_tokens = _count
    )
    assert HEADER not in fitted[0]["content"]
