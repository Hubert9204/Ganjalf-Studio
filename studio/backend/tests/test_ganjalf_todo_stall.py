"""Ganjalf: a model that re-sends the same task list instead of working is told so, then the
tool is taken away for the rest of the turn (Qwen3.6 35B-A3B sent one list 25 times in a row)."""

from __future__ import annotations

import uuid

from core.inference import agent_tools
from core.inference.tool_loop_controller import ToolLoopController

LIST = [
    {"content": "Check environment", "status": "completed"},
    {"content": "Initialize project with package.json", "status": "in_progress"},
    {"content": "Create the engine", "status": "pending"},
]


def _todo_call(todos = LIST, call_id = "call_0"):
    return {"id": call_id, "function": {"name": "todo_write", "arguments": {"todos": todos}}}


def _controller():
    controller = ToolLoopController(
        tools = [
            agent_tools.TODO_WRITE_TOOL,
            {"type": "function", "function": {"name": "edit_file", "parameters": {}}},
        ],
        session_id = "stall",
    )
    controller.test_session = f"stall-{uuid.uuid4().hex}"
    return controller


def _run(controller, call):
    decision = controller.prepare_call(call)
    if not decision.should_execute:
        return controller.record_noop(decision)
    result = agent_tools.todo_write(decision.arguments, controller.test_session)
    return controller.record_result(decision, result)


def test_same_list_again_says_what_to_do_instead():
    first = agent_tools.todo_write({"todos": LIST}, "same")
    assert first.startswith("Task list updated")
    again = agent_tools.todo_write({"todos": LIST}, "same")
    assert again.startswith(agent_tools.TODO_UNCHANGED)
    assert "Initialize project with package.json" in again
    assert "edit_file" in again
    assert not again.lower().startswith("error")
    third = agent_tools.todo_write({"todos": LIST}, "same")
    assert "3 times in a row" in third


def test_a_changed_list_resets_the_count():
    agent_tools.todo_write({"todos": LIST}, "reset")
    agent_tools.todo_write({"todos": LIST}, "reset")
    moved = [dict(item) for item in LIST]
    moved[1]["status"] = "completed"
    moved[2]["status"] = "in_progress"
    assert agent_tools.todo_write({"todos": moved}, "reset").startswith("Task list updated")
    assert "times in a row" not in agent_tools.todo_write({"todos": moved}, "reset")


def test_the_loop_takes_the_task_list_away_after_repeats():
    controller = _controller()
    _run(controller, _todo_call(call_id = "a"))
    assert "todo_write" not in controller.retired_tools
    _run(controller, _todo_call(call_id = "b"))
    assert "todo_write" not in controller.retired_tools
    _run(controller, _todo_call(call_id = "c"))
    assert "todo_write" in controller.retired_tools
    names = [tool["function"]["name"] for tool in controller.active_tools()]
    assert names == ["edit_file"]
    assert controller.has_active_tools()

    skipped = _run(controller, _todo_call(call_id = "d"))
    assert not skipped.executed
    assert "edit_file" in skipped.result
    # One stray call does not end the turn; a model that keeps at it is stopped.
    assert not controller.force_final_answer
    _run(controller, _todo_call(call_id = "e"))
    _run(controller, _todo_call(call_id = "f"))
    assert controller.force_final_answer


def test_work_between_two_lists_is_not_a_loop():
    controller = _controller()
    _run(controller, _todo_call(call_id = "a"))
    _run(controller, _todo_call(call_id = "b"))
    edit = controller.prepare_call(
        {"id": "e", "function": {"name": "edit_file", "arguments": {"path": "a.txt"}}}
    )
    controller.record_result(edit, "Wrote a.txt")
    _run(controller, _todo_call(call_id = "c"))
    assert "todo_write" not in controller.retired_tools


def test_rewording_an_item_is_not_progress():
    agent_tools.todo_write({"todos": LIST}, "reword")
    reworded = [dict(item) for item in LIST]
    reworded[1]["content"] = "Setup progetto base"
    assert agent_tools.todo_write({"todos": reworded}, "reword").startswith(
        agent_tools.TODO_UNCHANGED
    )
    # The new wording is still what the checklist shows.
    assert agent_tools.current_todos("reword")[1]["content"] == "Setup progetto base"


def test_presenting_an_approved_plan_again_does_not_end_the_turn():
    from core.inference.tool_loop_controller import PLAN_ALREADY_APPROVED

    controller = _controller()  # plan mode off: no exit_plan_mode among the tools
    decision = controller.prepare_call(
        {"id": "p", "function": {"name": "exit_plan_mode", "arguments": {"plan": "1. Files"}}}
    )
    assert not decision.should_execute
    completion = controller.record_noop(decision)
    assert completion.result == PLAN_ALREADY_APPROVED
    assert not controller.force_final_answer and controller.has_active_tools()


def test_a_list_moved_back_and_forth_is_circling_too():
    controller = _controller()
    flip = [dict(item) for item in LIST]
    flip[1]["status"], flip[2]["status"] = "pending", "in_progress"
    for call_id, todos in (("a", LIST), ("b", flip), ("c", LIST)):
        _run(controller, _todo_call(todos, call_id = call_id))
    assert "todo_write" in controller.retired_tools


def test_a_tool_plan_mode_left_out_is_a_slip_not_the_end_of_the_turn():
    from core.inference.agent_tools import EXIT_PLAN_MODE_TOOL, READ_FILE_TOOL

    controller = ToolLoopController(tools = [READ_FILE_TOOL, EXIT_PLAN_MODE_TOOL])
    decision = controller.prepare_call(
        {"id": "t", "function": {"name": "terminal", "arguments": {"command": "node -v"}}}
    )
    completion = controller.record_noop(decision)
    assert not completion.executed and "plan mode is on" in completion.result
    assert "exit_plan_mode" in completion.result
    assert not controller.force_final_answer
    assert {t["function"]["name"] for t in controller.active_tools()} == {
        "read_file",
        "exit_plan_mode",
    }
    # Outside plan mode an unknown tool still ends the rounds, as before.
    plain = ToolLoopController(tools = [READ_FILE_TOOL])
    plain.record_noop(
        plain.prepare_call({"id": "t", "function": {"name": "terminal", "arguments": {}}})
    )
    assert plain.force_final_answer
