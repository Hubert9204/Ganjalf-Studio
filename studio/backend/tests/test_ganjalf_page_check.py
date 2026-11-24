# SPDX-License-Identifier: AGPL-3.0-only
# Copyright 2026-present the Unsloth AI Inc. team. All rights reserved. See /studio/LICENSE.AGPL-3.0

"""check_page (headless Chromium for the model's pages) and the page errors the browser panel reports."""

import json
import os

import pytest

from core.inference import page_check
from core.inference.browser_agent import format_result
from core.inference.mcp_images import SENTINEL, is_image_tool


def test_panel_page_errors_reach_the_model_inside_the_fence():
    text = format_result(
        "browser_snapshot",
        {
            "ok": True,
            "file": "index.html",
            "text": "Score 0",
            "console": ["Uncaught ReferenceError: player is not defined (line 12:5)", 42, "x" * 5000],
        },
        None,
    )
    fence_end = text.index("</untrusted_web_content>")
    assert text.index("Page errors since it loaded") < fence_end
    assert "- Uncaught ReferenceError: player is not defined (line 12:5)" in text
    assert "x" * 401 not in text and "- " + "x" * 400 + "\n" in text
    assert "42" not in text


def test_no_errors_no_section():
    text = format_result("browser_snapshot", {"ok": True, "file": "a.html", "text": "hi", "console": []}, None)
    assert "Page errors" not in text


def test_workspace_files_never_leave_the_folder(tmp_path):
    root = os.path.realpath(tmp_path)
    (tmp_path / "game").mkdir()
    (tmp_path / "game" / "index.html").write_text("<title>x</title>")
    (tmp_path / "lib.js").write_text("export {}")
    assert page_check._workspace_file(root, "/game/") == os.path.join(root, "game", "index.html")
    assert page_check._workspace_file(root, "/lib.js") == os.path.join(root, "lib.js")
    assert page_check._workspace_file(root, "/../etc/passwd") is None
    assert page_check._workspace_file(root, "/%2e%2e/%2e%2e/etc/passwd") is None
    assert page_check._workspace_file(root, "/missing.js") is None


def test_target_urls(tmp_path):
    root = os.path.realpath(tmp_path)
    (tmp_path / "my game").mkdir()
    (tmp_path / "my game" / "index.html").write_text("<title>x</title>")
    url, error = page_check._target_url("my game", root, None)
    assert error is None and url == "http://workspace.ganjalf/my%20game/index.html"
    assert page_check._target_url("../outside.html", root, None)[0] is None
    assert page_check._target_url("nope.html", root, None)[1].startswith("Error: nope.html does not exist")
    assert "not a public address" in page_check._target_url("http://10.0.0.2/", root, None)[1]
    assert "own address" in page_check._target_url("http://localhost:8888/", root, None)[1]
    assert page_check._target_url("http://localhost:8080/", root, None) == ("http://localhost:8080/", None)


def test_module_types():
    assert page_check._content_type("a/b.mjs") == "text/javascript"
    assert page_check._content_type("x.wasm") == "application/wasm"
    assert page_check._content_type("model.glb") == "model/gltf-binary"


def test_switched_off(monkeypatch):
    monkeypatch.setenv("GANJALF_PAGE_CHECK", "0")
    assert page_check.check_page_available(refresh = True) is False
    assert page_check.check_page({"path": "index.html"}, "/tmp").startswith("Error: check_page needs Playwright")


def test_screenshot_travels_like_view_image():
    assert is_image_tool("check_page")
    from core.inference.tools import ALL_TOOLS

    assert "check_page" in {tool["function"]["name"] for tool in ALL_TOOLS}


def test_offered_only_where_it_can_run(monkeypatch):
    from routes import inference

    monkeypatch.setattr(page_check, "check_page_available", lambda refresh = False: False)
    assert inference._check_page_offered(page_check.CHECK_PAGE_TOOL) is False
    assert inference._check_page_offered({"function": {"name": "python"}}) is True


def test_report_fences_the_page_and_flags_a_blank_screen():
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (64, 36), (0, 0, 0)).save(buffer, format = "PNG")
    text = page_check._format(
        {
            "url": "http://workspace.ganjalf/index.html",
            "title": "Game",
            "text": "HP 0/0",
            "errors": ["Uncaught TypeError: x is undefined"],
            "requests": ["404 /missing.js (no such file in the working directory)"],
            "notes": [],
            "pressed": ["Enter"],
            "canvases": [[640, 360]],
            "png": buffer.getvalue(),
        },
        2.0,
    )
    head, images = text.split(SENTINEL, 1)
    assert head.startswith("Ran index.html in a headless browser")
    assert "Pressed: Enter." in head
    assert head.index("Uncaught TypeError") < head.index("</untrusted_web_content>")
    assert "one flat color (#000000)" in head
    assert json.loads(images)[0]["mimeType"] == "image/png"


@pytest.mark.skipif(
    os.environ.get("GANJALF_PAGE_CHECK_LIVE") != "1" or not page_check.check_page_available(refresh = True),
    reason = "set GANJALF_PAGE_CHECK_LIVE=1 with Playwright and Chromium installed",
)
def test_live_module_game(tmp_path):
    (tmp_path / "lib.js").write_text("export const hud = 'Score';")
    (tmp_path / "index.html").write_text(
        "<!doctype html><title>Game</title>"
        '<script type="importmap">{"imports":{"lib":"./lib.js"}}</script>'
        "<div id=h></div><canvas id=c width=200 height=100></canvas>"
        '<script type="module">import { hud } from "lib";'
        "addEventListener('keydown', e => { if (e.key === 'Enter') h.textContent = hud + ' 1'; });"
        "const gl = c.getContext('webgl'); (function f(){ gl.clearColor(0.2,0.6,0.9,1); gl.clear(gl.COLOR_BUFFER_BIT); requestAnimationFrame(f); })();"
        "setTimeout(() => player.update(), 50);</script>"
    )
    text = page_check.check_page({"path": "index.html", "wait_seconds": 0.5, "keys": ["Enter"]}, str(tmp_path))
    head = text.split(SENTINEL, 1)[0]
    assert "Uncaught ReferenceError: player is not defined" in head
    assert "Visible text: Score 1" in head
    assert "one flat color" not in head
