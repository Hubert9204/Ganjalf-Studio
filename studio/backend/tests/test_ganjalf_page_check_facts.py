"""Ganjalf: check_page says where an error came from and what the screenshot holds in numbers."""

import io

from core.inference import page_check

VITE_STACK = """TypeError: Cannot read properties of null (reading 'getContext')
    at drawMinimap (http://localhost:5173/src/UI.ts?t=1764090000000:498:22)
    at Game.animate (http://localhost:5173/src/Game.ts:410:5)
    at http://localhost:5173/node_modules/.vite/deps/three.js?v=1a2b:1234:9
    at main (http://localhost:5173/src/main.ts:12:3)"""


def test_the_error_names_the_functions_and_files():
    where = page_check._where(VITE_STACK)
    assert where == (
        " - at drawMinimap (src/UI.ts:498) <- Game.animate (src/Game.ts:410) <- main (src/main.ts:12)"
    )
    assert page_check._where("") == ""
    assert "game.js:7" in page_check._where("Error: x\n    at http://workspace.ganjalf/game.js:7:1")


def _png(draw):
    from PIL import Image

    image = Image.new("RGB", (320, 180), (26, 42, 26))
    draw(image)
    out = io.BytesIO()
    image.save(out, "PNG")
    return out.getvalue()


def test_screenshot_numbers_for_a_model_that_cannot_see():
    flat = _png(lambda image: None)
    assert page_check._screenshot_facts(flat) is None
    assert "one flat color" in page_check._blank_note(flat)

    def scene(image):
        from PIL import ImageDraw

        pen = ImageDraw.Draw(image)
        pen.rectangle((0, 120, 320, 180), fill = (60, 110, 40))
        pen.rectangle((150, 70, 170, 120), fill = (90, 90, 100))

    facts = page_check._screenshot_facts(_png(scene))
    assert facts.startswith("Screenshot: 3 distinct colours")
    assert "#182818" in facts


def test_text_only_note_forbids_describing_the_page():
    assert "cannot see images" in page_check.TEXT_ONLY_NOTE
    assert "not verified" in page_check.TEXT_ONLY_NOTE


def test_evaluate_reports_what_the_page_holds(tmp_path):
    import pytest

    if not page_check.check_page_available():
        pytest.skip("needs Playwright and Chromium")
    (tmp_path / "index.html").write_text(
        "<script>window.game={x:0};const d=new Set();"
        "addEventListener('keydown',e=>d.add(e.key));addEventListener('keyup',e=>d.delete(e.key));"
        "setInterval(()=>{if(d.has('w'))window.game.x+=1},16);</script>"
    )
    held = page_check.check_page(
        {
            "path": "index.html",
            "wait_seconds": 0.3,
            "keys": ["w"],
            "hold_ms": 600,
            "evaluate": "window.game.x",
        },
        str(tmp_path),
    )
    moved = int(next(line for line in held.splitlines() if line.startswith("evaluate: "))[10:])
    assert moved > 10  # the key was held long enough for the game loop to see it
    broken = page_check.check_page(
        {"path": "index.html", "wait_seconds": 0.1, "evaluate": "window.nope.x"}, str(tmp_path)
    )
    assert "evaluate: failed: TypeError: Cannot read properties of undefined" in broken
    assert page_check.check_page({"path": "index.html", "evaluate": 5}, str(tmp_path)).startswith(
        "Error"
    )


def test_evaluate_uses_the_page_like_the_user(tmp_path):
    """Fill, click, await, read: the UI path the API checks with curl never exercised."""
    import pytest

    if not page_check.check_page_available():
        pytest.skip("needs Playwright and Chromium")
    (tmp_path / "index.html").write_text(
        '<input id="d"><button id="add" onclick="add()">Add</button><ul id="list"></ul><script>'
        "async function add(){await new Promise(r=>setTimeout(r,100));const li=document.createElement('li');"
        "li.textContent=document.querySelector('#d').value;document.querySelector('#list').appendChild(li)}"
        "function custom(){return document.querySelector('.split-row select').value}</script>"
    )

    def value(expression):
        out = page_check.check_page(
            {"path": "index.html", "wait_seconds": 0.1, "evaluate": expression}, str(tmp_path)
        )
        return next(line for line in out.splitlines() if line.startswith("evaluate: "))[10:]

    assert (
        value(
            "document.querySelector('#d').value='Taxi';\nawait add();\ndocument.querySelector('#list').innerText"
        )
        == '"Taxi"'
    )
    assert (
        value(
            "document.querySelector('#d').value='Pizza'; document.querySelector('#add').click(); "
            "await new Promise(r => setTimeout(r, 300)); document.querySelector('#list').innerText"
        )
        == '"Pizza"'
    )
    assert value("custom()").startswith("failed: TypeError")  # the handler's own bug comes back
    assert value("const f = () => {\n  return 2\n}\nf()") == "2"
    assert value("return {n: 1}") == '{"n":1}'
    assert value("`a;${1+1}`") == '"a;2"'
