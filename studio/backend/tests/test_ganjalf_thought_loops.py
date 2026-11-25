"""Ganjalf: a thought that repeats itself is recognised (from a real Qwen3.6 35B-A3B session)."""

import json
import sys
from pathlib import Path

from core.inference import thought_loops

# The length-continuation tests' fake llama-server, reused for the cut thought.
sys.path.insert(0, str(Path(__file__).resolve().parent))

LOOP = (
    "Actually, I think the issue might be that the terrain mesh is being created but the terrain "
    "mesh is not being added to the scene because createTerrainMesh() is failing silently.\n\n"
    "This should work. But maybe the issue is that the terrain mesh is too large and the camera "
    "can't see it.\n\n"
    "OK, I'm going in circles. Let me just check if the 3D rendering is working by adding a "
    "simple colored cube to the scene and seeing if it's visible.\n\n"
)
HONEST = (
    "The error says drawMinimap reads getContext of null. The minimap canvas is created in "
    "initUI, which runs after the constructor asks for it. Moving initUI before the first frame "
    "fixes the order. Then the loop no longer throws, so the 3D scene keeps rendering. "
    "I will read Game.ts around the constructor to confirm where initUI is called from. "
    "If it is called later, I move it up and run check_page again to see the errors gone. "
    "The terrain size is fine at 512 units; the camera far plane is 1000, so it is visible. "
    "Lights are added before the first render, so the scene is lit."
)


def test_the_real_loop_is_caught():
    assert thought_loops.is_looping("Let me look at the scene setup.\n" + LOOP * 5)


def test_a_thought_that_moves_on_is_not():
    assert not thought_loops.is_looping(HONEST * 1)
    assert not thought_loops.is_looping(LOOP)  # once is a thought, not a loop
    # A recap of one earlier line in a long, varied thought is not a loop either.
    varied = " ".join(
        f"Step {i}: change line {i * 7} of Game.ts and rerun the check." for i in range(60)
    )
    assert not thought_loops.is_looping(varied + " " + LOOP)


def test_the_note_keeps_each_idea_once_and_the_message_asks_for_facts():
    note = thought_loops.loop_progress(LOOP * 6)
    assert note.count("going in circles") == 1
    message = thought_loops.loop_message()
    assert "console.log" in message and "read" in message


def test_the_tool_loop_cuts_the_circling_thought_and_asks_for_action(monkeypatch):
    from test_length_truncated_reasoning_continuation import (
        _done,
        _make_backend,
        _run,
        _sse,
        _texts,
    )

    payloads: list[dict] = []
    # The server would go on for minutes; the loop stops reading once the circle is clear.
    circling = [_sse({"reasoning_content": LOOP}) for _ in range(40)] + [_done()]
    backend = _make_backend(
        monkeypatch,
        [circling, [_sse({"content": "Reading Game.ts now."}), _done()]],
        payloads,
    )

    events = _run(backend)

    assert len(payloads) == 2
    second = json.dumps(payloads[1]["messages"])
    assert "going in circles (the same sentences" in second
    assert payloads[1]["chat_template_kwargs"]["enable_thinking"] is False
    assert "Reading Game.ts now." in "".join(_texts(events, "content"))
