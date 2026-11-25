# SPDX-License-Identifier: AGPL-3.0-only
# Copyright 2026-present the Unsloth AI Inc. team. All rights reserved. See /studio/LICENSE.AGPL-3.0

"""check_page: open a page in a headless Chromium on the server and report what it did.

The chat's browser panel only runs while the chat is on screen, and a model that wrote a web page
or a browser game otherwise has no way to see it run. This opens the page off screen (a virtual
display: no window, no desktop), lets its scripts run, optionally presses keys, and returns the
uncaught errors, console errors, failed requests, the visible text and a screenshot.

Workspace files are served from a made-up origin through Playwright's request routing, so ES
modules, import maps and fetch() of sibling files work as on a web server, and no port is opened.
Loopback servers the model started (``python3 -m http.server 8080``) are reachable; Studio's own
ports and private networks are not.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import mimetypes
import os
import shutil
import stat
import threading
import time
from typing import Any, Optional
from urllib.parse import unquote, urlsplit

logger = logging.getLogger(__name__)

CHECK_PAGE = "check_page"
WORKSPACE_ORIGIN = "http://workspace.ganjalf"
_WORKSPACE_HOST = "workspace.ganjalf"

VIEWPORT = {"width": 1280, "height": 720}
DEFAULT_WAIT_S = 2.0
MAX_WAIT_S = 20.0
LOAD_TIMEOUT_MS = 15_000
MAX_KEYS = 20
MAX_HOLD_MS = 3000
MAX_EVALUATE_CHARS = 2000
MAX_EVALUATED_CHARS = 1500
MAX_REPORTS = 25
MAX_REPORT_CHARS = 400
MAX_TEXT_CHARS = 2_000
MAX_SERVED_BYTES = 64 * 1024 * 1024
_AVAILABILITY_TTL_S = 300.0

# Chromium's own names (https://playwright.dev/docs/api/class-keyboard#keyboard-press).
_KEY_ALIASES = {
    "space": "Space",
    " ": "Space",
    "enter": "Enter",
    "return": "Enter",
    "esc": "Escape",
    "escape": "Escape",
    "up": "ArrowUp",
    "down": "ArrowDown",
    "left": "ArrowLeft",
    "right": "ArrowRight",
    "tab": "Tab",
    "shift": "Shift",
    "ctrl": "Control",
    "control": "Control",
    "alt": "Alt",
}

CHECK_PAGE_TOOL = {
    "type": "function",
    "function": {
        "name": CHECK_PAGE,
        "description": (
            "Run a web page in a headless browser on the server and see what it did: uncaught "
            "JavaScript errors with the functions and files they came from, console errors, "
            "failed requests, the visible text, the screenshot's colours in numbers, and the "
            "screenshot itself if you can read images. Use it after writing or changing an HTML page or browser game, before "
            "you say it works. Takes a file in the working directory (served as from a web "
            "server, so ES modules, import maps and fetch() of sibling files work) or an "
            "http://localhost URL of a server you started. For a Vite/webpack/TypeScript project, "
            "build it and pass the built page (e.g. dist/index.html); no server is needed. "
            "Optionally presses keys after the wait, to start a game or test controls."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "HTML file in the working directory (e.g. index.html or game/index.html), "
                        "or an http(s) URL such as http://localhost:8080/."
                    ),
                },
                "wait_seconds": {
                    "type": "number",
                    "description": f"How long the page runs before it is checked (default {DEFAULT_WAIT_S:g}, at most {MAX_WAIT_S:g}).",
                },
                "keys": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        'Keys to press after the wait, in order (e.g. ["Enter", "ArrowUp", '
                        '"Space", "w"]). The screenshot is taken after them.'
                    ),
                },
                "hold_ms": {
                    "type": "number",
                    "description": (
                        "How long each key is held down, in ms (default 80, at most "
                        f"{MAX_HOLD_MS}). A game that moves while a key is down needs ~500-1000."
                    ),
                },
                "evaluate": {
                    "type": "string",
                    "description": (
                        "JavaScript run in the page after the keys; the value of its last "
                        "expression comes back as JSON (a promise is awaited). Use it to check "
                        "what happened instead of guessing from the screenshot "
                        "(`window.game.player.position`), and to use the page as the user would: "
                        "fill a field, click a button, then read the result, e.g. "
                        "`document.querySelector('#desc').value='Taxi'; "
                        "document.querySelector('#add').click(); await new Promise(r => "
                        "setTimeout(r, 500)); document.querySelector('#list').innerText`. An "
                        "error thrown by the page's own handler comes back as `failed: ...`."
                    ),
                },
            },
            "required": ["path"],
        },
    },
}

_available: Optional[tuple[bool, float]] = None
_available_lock = threading.Lock()


def _system_browser() -> Optional[str]:
    configured = os.environ.get("GANJALF_PAGE_CHECK_BROWSER", "").strip()
    if configured:
        return configured if os.path.isfile(configured) else None
    for name in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable"):
        found = shutil.which(name)
        if found:
            return found
    return None


def _bundled_browser() -> Optional[str]:
    """Playwright's own Chromium, when ``playwright install chromium`` has run."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return None
    found: list[Optional[str]] = [None]

    def probe() -> None:
        try:
            with sync_playwright() as playwright:
                path = playwright.chromium.executable_path
                found[0] = path if path and os.path.isfile(path) else None
        except Exception:
            found[0] = None

    # The sync API refuses a thread that runs an event loop: probe from a fresh one.
    worker = threading.Thread(target = probe, daemon = True)
    worker.start()
    worker.join(30)
    return found[0]


def _browser_executable(playwright) -> Optional[str]:
    """None: Playwright's bundled Chromium; else a system Chrome/Chromium path."""
    if os.environ.get("GANJALF_PAGE_CHECK_BROWSER", "").strip():
        return _system_browser()
    try:
        bundled = playwright.chromium.executable_path
    except Exception:
        bundled = None
    return None if bundled and os.path.isfile(bundled) else _system_browser()


def check_page_available(refresh: bool = False) -> bool:
    """Playwright importable and some Chromium to drive; cached, as the probe starts a driver."""
    global _available
    if os.environ.get("GANJALF_PAGE_CHECK", "").strip().lower() in {"0", "off", "false", "no"}:
        return False
    with _available_lock:
        now = time.monotonic()
        if not refresh and _available is not None and now - _available[1] < _AVAILABILITY_TTL_S:
            return _available[0]
        try:
            import playwright.sync_api  # noqa: F401
            ok = bool(_bundled_browser() or _system_browser())
        except Exception:
            ok = False
        _available = (ok, now)
        return ok


def _clip(text: Any, limit: int = MAX_REPORT_CHARS) -> str:
    flat = " ".join(str(text).split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def _inside(root: str, target: str) -> bool:
    try:
        return os.path.commonpath([root, target]) == root
    except ValueError:
        return False


def _workspace_file(root: str, url_path: str) -> Optional[str]:
    """The regular file a workspace URL names, or None; never outside ``root``."""
    relative = unquote(url_path).lstrip("/")
    target = os.path.realpath(os.path.join(root, relative))
    try:
        if os.path.commonpath([root, target]) != root:
            return None
    except ValueError:
        return None
    if os.path.isdir(target):
        target = os.path.join(target, "index.html")
    try:
        info = os.stat(target)
    except OSError:
        return None
    if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_SERVED_BYTES:
        return None
    return target


def _content_type(path: str) -> str:
    extension = os.path.splitext(path)[1].lower()
    fixed = {
        ".js": "text/javascript",
        ".mjs": "text/javascript",
        ".cjs": "text/javascript",
        ".json": "application/json",
        ".wasm": "application/wasm",
        ".css": "text/css",
        ".html": "text/html",
        ".htm": "text/html",
        ".svg": "image/svg+xml",
        ".glb": "model/gltf-binary",
        ".gltf": "model/gltf+json",
    }
    if extension in fixed:
        return fixed[extension]
    return mimetypes.guess_type(path)[0] or "application/octet-stream"


def _host_refusal(
    url: str, website_policy: Optional[dict], resolved: dict[str, Optional[str]]
) -> Optional[str]:
    """Why the page may not load ``url``, or None."""
    from .browser_agent import _host_problem, _is_loopback, _studio_port_problem

    parts = urlsplit(url)
    host = parts.hostname or ""
    if _is_loopback(host):
        return _studio_port_problem(url)
    problem = _host_problem(host)
    if problem:
        return problem
    if website_policy:
        from .web_access_policy import check_url_access
        allowed, _reason, blocked_host = check_url_access(url, website_policy)
        if not allowed:
            return f"{blocked_host or host} is not allowed by the website access policy"
    if host not in resolved:
        try:
            ipaddress.ip_address(host.strip("[]"))
            resolved[host] = None
        except ValueError:
            from .tools import _validate_and_resolve_host

            try:
                port = parts.port or (443 if parts.scheme == "https" else 80)
            except ValueError:
                return "the address has a bad port"
            ok, reason, _ips = _validate_and_resolve_host(host, port)
            resolved[host] = None if ok else (reason or f"{host} is not a public address")
    return resolved[host]


def _target_url(
    path: str, root: str, website_policy: Optional[dict]
) -> tuple[Optional[str], Optional[str]]:
    """(URL to open, error)."""
    text = path.strip()
    if text.lower().startswith(("http://", "https://")):
        problem = _host_refusal(text, website_policy, {})
        if problem:
            return None, f"Error: check_page cannot open that address ({problem})."
        return text, None
    if text.lower().startswith("file://"):
        text = urlsplit(text).path
    from .view_image import _strip_habit_prefix

    text = _strip_habit_prefix(text, root)
    target = os.path.realpath(os.path.join(root, text))
    try:
        inside = os.path.commonpath([root, target]) == root
    except ValueError:
        inside = False
    if not inside:
        return (
            None,
            "Error: the page must be inside this conversation's working directory, or an http(s) URL.",
        )
    if os.path.isdir(target):
        target = os.path.join(target, "index.html")
    if not os.path.isfile(target):
        return None, f"Error: {path} does not exist in the working directory."
    relative = os.path.relpath(target, root).replace(os.sep, "/")
    from urllib.parse import quote

    return f"{WORKSPACE_ORIGIN}/{quote(relative)}", None


def _launch_args() -> list[str]:
    args = [
        # WebGL without a GPU: games and three.js scenes still draw.
        "--use-angle=swiftshader",
        "--enable-unsafe-swiftshader",
        "--ignore-gpu-blocklist",
        "--disable-dev-shm-usage",
        "--mute-audio",
        "--autoplay-policy=no-user-gesture-required",
        "--js-flags=--max-old-space-size=2048",
    ]
    # Chromium's own sandbox needs user namespaces, which root in a container usually lacks.
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        args.append("--no-sandbox")
    return args


# Ganjalf: said to a model that takes no images, after a check_page result. Without it a text-only
# model "describes" the screenshot it never got (a black canvas, then a player on green grass).
TEXT_ONLY_NOTE = (
    "[You cannot see images: the screenshot went to the user only. Do not say what the page "
    "looks like or that you can see something in it. Judge only from the errors, text and "
    "screenshot numbers above, and tell the user what is not verified.]"
)

_STACK_FRAME_RE = None


def _where(stack: str, frames: int = 3) -> str:
    """Ganjalf: the functions and files an uncaught error went through, so the model reads that
    code instead of guessing (a bare "reading 'add' of undefined" cost one session 8 minutes)."""
    import re

    global _STACK_FRAME_RE
    if _STACK_FRAME_RE is None:
        _STACK_FRAME_RE = re.compile(r"^\s*at (?:(.+?) \()?(\S+?):(\d+):\d+\)?\s*$")
    found: list[str] = []
    for line in str(stack or "").splitlines():
        match = _STACK_FRAME_RE.match(line)
        if not match:
            continue
        function, url, number = match.groups()
        parts = urlsplit(url)
        path = parts.path.lstrip("/") if parts.scheme in ("http", "https") else url
        if not path or "node_modules/.vite/deps" in path:
            # Inside a bundled library: the caller's frame below is the useful one.
            continue
        name = (function or "").replace("Object.", "").strip()
        found.append(f"{name} ({path}:{number})" if name else f"{path}:{number}")
        if len(found) >= frames:
            break
    if not found:
        return ""
    return " - at " + " <- ".join(found)


def _screenshot_facts(png: bytes) -> Optional[str]:
    """What the screenshot holds, in numbers a text-only model can use."""
    try:
        import io

        from PIL import Image
        with Image.open(io.BytesIO(png)) as image:
            # Nearest: a smoothing resize would invent the in-between colours of every edge.
            raw = image.convert("RGB").resize((160, 90), Image.NEAREST).tobytes()
    except Exception:
        return None
    if not raw:
        return None
    counts: dict[tuple[int, int, int], int] = {}
    for index in range(0, len(raw) - 2, 3):
        key = (raw[index] >> 3, raw[index + 1] >> 3, raw[index + 2] >> 3)
        counts[key] = counts.get(key, 0) + 1
    pixels = len(raw) // 3
    if len(counts) <= 1:
        return None  # one flat color: _blank_note says it
    top, top_n = max(counts.items(), key = lambda item: item[1])
    share = round(100 * top_n / pixels)
    color = "#{:02x}{:02x}{:02x}".format(*(value << 3 for value in top))
    return (
        f"Screenshot: {len(counts)} distinct colours; the most common ({color}) covers {share}% "
        "of the page."
    )


def _blank_note(png: bytes) -> Optional[str]:
    try:
        import io

        from PIL import Image
        with Image.open(io.BytesIO(png)) as image:
            small = image.convert("RGB").resize((64, 36))
            extrema = small.getextrema()
    except Exception:
        return None
    if all(low == high for low, high in extrema):
        color = "#{:02x}{:02x}{:02x}".format(*(low for low, _ in extrema))
        return (
            f"The screenshot is one flat color ({color}): nothing was drawn. If this is a canvas "
            "game, its script likely stopped; read the errors above."
        )
    return None


def _run(
    url: str,
    root: str,
    wait_s: float,
    keys: list[str],
    website_policy: Optional[dict],
    cancel_event,
    hold_ms: int = 80,
    expression: str = "",
) -> dict:
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import TimeoutError as PlaywrightTimeout
    from playwright.sync_api import sync_playwright

    errors: list[str] = []
    requests: list[str] = []
    notes: list[str] = []
    resolved: dict[str, Optional[str]] = {}
    # A built page in a subfolder (Vite/webpack dist/index.html) asks for /assets/... from its own
    # folder: root-absolute paths that miss the working directory are tried there too.
    page_root = root
    opened = urlsplit(url)
    if (opened.hostname or "").lower() == _WORKSPACE_HOST:
        folder = os.path.dirname(unquote(opened.path).lstrip("/"))
        if folder:
            page_root = os.path.realpath(os.path.join(root, folder))

    def add(target: list[str], line: str) -> None:
        line = _clip(line)
        if line and line not in target and len(target) < MAX_REPORTS:
            target.append(line)

    def route(route, request) -> None:
        request_url = request.url
        parts = urlsplit(request_url)
        scheme = parts.scheme.lower()
        if scheme in {"data", "blob", "about"}:
            route.continue_()
            return
        if scheme not in {"http", "https"}:
            add(requests, f"Blocked {request_url} (only web addresses load here)")
            route.abort("blockedbyclient")
            return
        if (parts.hostname or "").lower() == _WORKSPACE_HOST:
            path = _workspace_file(root, parts.path)
            if path is None and page_root != root and _inside(root, page_root):
                path = _workspace_file(page_root, parts.path)
            if path is not None and path.lower().endswith(
                (".ts", ".tsx", ".jsx", ".vue", ".svelte")
            ):
                add(
                    notes,
                    f"The page loads source that browsers cannot run ({parts.path}): it needs its "
                    "bundler. Build it (e.g. `npm run build`) and check the built page (e.g. "
                    "dist/index.html), or start the dev server with nohup and pass its http://localhost URL.",
                )
            if path is None:
                add(requests, f"404 {parts.path} (no such file in the working directory)")
                route.fulfill(status = 404, content_type = "text/plain", body = "Not found")
                return
            with open(path, "rb") as handle:
                body = handle.read(MAX_SERVED_BYTES + 1)
            route.fulfill(
                status = 200,
                body = body,
                headers = {"Content-Type": _content_type(path), "Cache-Control": "no-store"},
            )
            return
        problem = _host_refusal(request_url, website_policy, resolved)
        if problem:
            add(requests, f"Blocked {request_url} ({problem})")
            route.abort("blockedbyclient")
            return
        route.continue_()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless = True,
            executable_path = _browser_executable(playwright),
            args = _launch_args(),
            timeout = 30_000,
        )
        try:
            context = browser.new_context(
                viewport = VIEWPORT,
                # The model's own page under test: a strict CSP must not block `evaluate`.
                bypass_csp = True,
                service_workers = "block",
                accept_downloads = False,
            )
            context.route("**/*", route)
            page = context.new_page()
            page.on(
                "pageerror",
                lambda error: add(
                    errors,
                    f"Uncaught {getattr(error, 'name', '') or 'Error'}: {getattr(error, 'message', error)}"
                    + _where(getattr(error, "stack", "") or ""),
                ),
            )

            def on_console(message) -> None:
                if message.type != "error":
                    return
                location = message.location or {}
                where = ""
                if location.get("lineNumber"):
                    source = str(location.get("url") or "").replace(WORKSPACE_ORIGIN + "/", "")
                    where = (
                        f" ({source}:{location.get('lineNumber')})"
                        if source
                        else f" (line {location.get('lineNumber')})"
                    )
                add(errors, f"console.error: {message.text}{where}")

            page.on("console", on_console)
            page.on(
                "requestfailed",
                lambda request: None
                if (request.failure or "").endswith("ERR_BLOCKED_BY_CLIENT")
                else add(
                    requests,
                    f"Failed {request.url.replace(WORKSPACE_ORIGIN + '/', '')} ({request.failure})",
                ),
            )
            page.on(
                "response",
                lambda response: add(
                    requests,
                    f"HTTP {response.status} {response.url.replace(WORKSPACE_ORIGIN + '/', '')}",
                )
                if response.status >= 400 and urlsplit(response.url).hostname != _WORKSPACE_HOST
                else None,
            )
            try:
                page.goto(url, wait_until = "load", timeout = LOAD_TIMEOUT_MS)
            except PlaywrightTimeout:
                notes.append(f"The page did not finish loading within {LOAD_TIMEOUT_MS // 1000} s.")
            deadline = time.monotonic() + wait_s
            while time.monotonic() < deadline:
                if cancel_event is not None and cancel_event.is_set():
                    return {"cancelled": True}
                page.wait_for_timeout(min(250, max(1, int((deadline - time.monotonic()) * 1000))))
            pressed: list[str] = []
            if keys:
                page.mouse.click(VIEWPORT["width"] // 2, VIEWPORT["height"] // 2)
                for key in keys:
                    name = _KEY_ALIASES.get(key.strip().lower(), key.strip())
                    try:
                        page.keyboard.press(name, delay = hold_ms)
                        pressed.append(name)
                    except PlaywrightError:
                        notes.append(
                            f"Unknown key {key!r}; use names like Enter, ArrowUp, Space or a letter."
                        )
                    page.wait_for_timeout(150)
                page.wait_for_timeout(500)
            evaluated = None
            if expression:
                evaluated = _evaluate(page, expression)
            title = page.title()
            try:
                text = page.inner_text("body", timeout = 2_000)
            except PlaywrightError:
                text = ""
            canvases = page.evaluate(
                "() => Array.from(document.querySelectorAll('canvas')).map(c => {"
                " const r = c.getBoundingClientRect(); return [Math.round(r.width), Math.round(r.height)]; })"
            )
            png = page.screenshot(type = "png", timeout = 10_000)
            return {
                "url": page.url,
                "title": title,
                "text": text,
                "errors": errors,
                "requests": requests,
                "notes": notes,
                "pressed": pressed,
                "canvases": canvases if isinstance(canvases, list) else [],
                "evaluated": evaluated,
                "png": png,
            }
        finally:
            browser.close()


# Runs the model's code as the body of an async function whose result is its last statement, so
# top-level `await` works and `a(); b; c.innerText` returns c.innerText. Statements are split on
# top-level `;` (outside strings and brackets); a last statement that is not an expression
# (`if`, `const`) runs as written and gives undefined.
_EVALUATE_JS = r"""
async (source) => {
  const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
  const split = (s) => {
    const parts = []; let depth = 0, quote = null, cur = '';
    for (let i = 0; i < s.length; i++) {
      const c = s[i];
      if (quote) {
        cur += c;
        if (c === '\\') { cur += s[++i] || ''; continue; }
        if (c === quote) quote = null;
        continue;
      }
      if (c === '"' || c === "'" || c === '`') { quote = c; cur += c; continue; }
      if ('([{'.includes(c)) depth++;
      if (')]}'.includes(c)) depth--;
      if ((c === ';' || c === '\n') && depth === 0) { if (cur.trim()) parts.push(cur); cur = ''; continue; }
      cur += c;
    }
    if (cur.trim()) parts.push(cur);
    return parts.map((p) => p.trim());
  };
  let run;
  const parts = split(source);
  const last = parts.pop() || 'undefined';
  try {
    run = new AsyncFunction(parts.join(';\n') + ';\nreturn (' + last + '\n);');
  } catch (e) {
    // The last statement is not an expression (`if`, `const`, `return x`): run it as written.
    if (!(e instanceof SyntaxError)) throw e;
    run = new AsyncFunction(source);
  }
  const v = await run();
  try { return JSON.stringify(v) ?? String(v); } catch (e) { return String(v); }
}
"""


def _evaluate(page, expression: str) -> str:
    """Ganjalf: the value of the model's expression, as JSON text, or why it failed."""
    try:
        # Awaited when it returns a promise, so `await addExpense(); document.body.innerText`
        # or a handler that fetches is read after it finished.
        value = page.evaluate(_EVALUATE_JS, expression)
    except Exception as exc:  # noqa: BLE001 -- the page's own error goes back to the model
        first = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
        return "failed: " + _clip(first.replace("Page.evaluate: ", "", 1), 300)
    text = str(value)
    if len(text) > MAX_EVALUATED_CHARS:
        text = text[:MAX_EVALUATED_CHARS] + " … (cut)"
    return text


def _format(outcome: dict, wait_s: float) -> str:
    from .browser_agent import _FENCE, _UNTRUSTED_NOTE, _fenced
    from .mcp_images import SENTINEL, _png_data_url

    shown_url = _clip(str(outcome.get("url") or "").replace(WORKSPACE_ORIGIN + "/", ""), 300)
    head = [
        f"Ran {shown_url} in a headless browser ({VIEWPORT['width']}x{VIEWPORT['height']}) for {wait_s:g} s."
    ]
    if outcome.get("pressed"):
        head.append("Pressed: " + ", ".join(outcome["pressed"]) + ".")
    # Everything below comes from the page, so it stays inside the untrusted-content fence.
    lines: list[str] = []
    title = _clip(outcome.get("title") or "", 200)
    lines.append(f"Title: {title}" if title else "Title: (none)")
    errors = outcome.get("errors") or []
    if errors:
        lines.append(f"JavaScript errors ({len(errors)}):")
        lines.extend(f"- {line}" for line in errors)
    else:
        lines.append("JavaScript errors: none.")
    if outcome.get("requests"):
        lines.append("Failed or blocked requests:")
        lines.extend(f"- {line}" for line in outcome["requests"])
    if outcome.get("evaluated") is not None:
        lines.append(f"evaluate: {outcome['evaluated']}")
    canvases = outcome.get("canvases") or []
    if canvases:
        sizes = ", ".join(f"{w}x{h}" for w, h in canvases[:6])
        lines.append(f"Canvases: {len(canvases)} ({sizes}).")
    lines.extend(outcome.get("notes") or [])
    text = " ".join(str(outcome.get("text") or "").split())
    if text:
        if len(text) > MAX_TEXT_CHARS:
            text = text[:MAX_TEXT_CHARS] + " … (cut)"
        lines.append(f"Visible text: {text}")
    else:
        lines.append("Visible text: (none)")
    png = outcome.get("png") or b""
    body = (
        "\n".join(head)
        + f"\n<{_FENCE}>\n{_fenced(chr(10).join(lines))}\n</{_FENCE}>\n{_UNTRUSTED_NOTE}"
    )
    blank = _blank_note(png) if png else None
    if blank:
        body += "\n" + blank
    else:
        facts = _screenshot_facts(png) if png else None
        if facts:
            body += "\n" + facts
    if not png:
        return body + "\nNo screenshot could be taken."
    import base64

    url = _png_data_url(base64.b64encode(png).decode("ascii"))
    if url is None:
        return body + "\nThe screenshot could not be read."
    return (
        body
        + "\n"
        + SENTINEL
        + json.dumps([{"data": url.split(",", 1)[1], "mimeType": "image/png"}])
    )


def check_page(
    arguments: Any,
    workdir: str,
    cancel_event = None,
    website_policy: Optional[dict] = None,
) -> str:
    if not isinstance(arguments, dict):
        return 'Error: check_page takes {"path": ...}.'
    path = arguments.get("path")
    if not isinstance(path, str) or not path.strip():
        return "Error: 'path' must be an HTML file in the working directory or an http(s) URL."
    try:
        wait_s = float(arguments.get("wait_seconds", DEFAULT_WAIT_S))
    except (TypeError, ValueError):
        wait_s = DEFAULT_WAIT_S
    wait_s = min(MAX_WAIT_S, max(0.0, wait_s))
    raw_keys = arguments.get("keys") or []
    if isinstance(raw_keys, str):
        raw_keys = [raw_keys]
    if not isinstance(raw_keys, list):
        return "Error: 'keys' must be a list of key names."
    keys = [key for key in raw_keys if isinstance(key, str) and 0 < len(key) <= 30][:MAX_KEYS]
    try:
        hold_ms = int(float(arguments.get("hold_ms", 80)))
    except (TypeError, ValueError):
        hold_ms = 80
    hold_ms = min(MAX_HOLD_MS, max(10, hold_ms))
    expression = arguments.get("evaluate") or ""
    if not isinstance(expression, str):
        return "Error: 'evaluate' must be a JavaScript expression as a string."
    expression = expression.strip()
    if len(expression) > MAX_EVALUATE_CHARS:
        return f"Error: 'evaluate' is limited to {MAX_EVALUATE_CHARS} characters; check one thing at a time."
    if not check_page_available():
        return (
            "Error: check_page needs Playwright and Chromium on the server, which are not installed. "
            "Tell the user to run `bash scripts/ganjalf-install-page-check.sh` in Ganjalf Studio's "
            "folder (Docker: rebuild the image), then restart Studio. Until then, say the page is unchecked."
        )
    root = os.path.realpath(workdir)
    url, error = _target_url(path, root, website_policy)
    if error:
        return error
    outcome: dict = {}
    failure: list[BaseException] = []

    def work() -> None:
        try:
            outcome.update(
                _run(
                    url,
                    root,
                    wait_s,
                    keys,
                    website_policy,
                    cancel_event,
                    hold_ms = hold_ms,
                    expression = expression,
                )
            )
        except BaseException as exc:  # reported to the model below
            failure.append(exc)

    # Playwright's sync API refuses a thread with a running event loop: run in a fresh one.
    worker = threading.Thread(target = work, name = "check-page", daemon = True)
    worker.start()
    deadline = time.monotonic() + wait_s + len(keys) * (0.5 + hold_ms / 1000) + 90
    while worker.is_alive() and time.monotonic() < deadline:
        # A stop does not wait for the browser: the worker notices the same event and closes it.
        if cancel_event is not None and cancel_event.is_set():
            return "Error: check_page was cancelled."
        worker.join(0.25)
    if worker.is_alive():
        return (
            "Error: the headless browser did not finish in time; the page may be stuck in a loop."
        )
    if failure:
        logger.warning("check_page failed: %s", failure[0])
        message = _clip(
            str(failure[0]).splitlines()[0] if str(failure[0]) else type(failure[0]).__name__, 300
        )
        return f"Error: the headless browser failed: {message}"
    if outcome.get("cancelled"):
        return "Error: check_page was cancelled."
    return _format(outcome, wait_s)
