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
