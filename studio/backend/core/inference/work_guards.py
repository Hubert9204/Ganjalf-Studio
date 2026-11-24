"""Ganjalf soft guardrails for the agentic tool loop.

Two reminders, both advisory and both with a guaranteed way out:

* **Verify after writes** (``GANJALF_VERIFY_AFTER_WRITES``, default 6, ``0`` turns it off):
  after that many successful file writes in a row with nothing run in between, a short note is
  appended to the model's copy of the last tool result. The counter then starts over, so the note
  comes back at most once per N writes and never blocks a call.
* **check_page gate** (``GANJALF_CHECK_PAGE_GATE``, default on, ``0`` turns it off): when the model
  is about to give its final answer after changing web files (HTML/CSS, or JS/TS beside an HTML
  page) and has not run ``check_page`` since, the loop sends it back once to check the page. It
  fires at most once per response, only when ``check_page`` is actually offered, and any
  ``check_page`` call (passing, failing or unavailable) clears it.
"""

from __future__ import annotations

import os
import re
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Optional

DEFAULT_VERIFY_AFTER_WRITES = 6

# Always a page or a piece of one.
_MARKUP_EXTS = frozenset({".html", ".htm", ".css", ".scss", ".sass", ".less", ".vue", ".svelte", ".jsx", ".tsx"})
# A page only when an HTML file sits beside or above them (a Node backend is not a page).
_SCRIPT_EXTS = frozenset({".js", ".mjs", ".cjs", ".ts"})
_WEB_EXTS = _MARKUP_EXTS | _SCRIPT_EXTS

_PATH_CHARS = r"[\w./~@+-]+"
# Shell writes: `> f`, `>> f`, `tee [-a] f`, `cp|mv src dst`, `sed -i … f`.
_SHELL_WRITE_RES = (
    re.compile(rf"(?<![0-9&<>])>>?\s*['\"]?({_PATH_CHARS})"),
    re.compile(rf"\btee\s+(?:-a\s+)?['\"]?({_PATH_CHARS})"),
    re.compile(rf"\b(?:cp|mv)\s+(?:-\w+\s+)*\S+\s+['\"]?({_PATH_CHARS})"),
    re.compile(rf"\bsed\s+(?:-\w+\s+)*-i\S*\s+(?:-\w+\s+)*(?:'[^']*'|\"[^\"]*\"|\S+)\s+['\"]?({_PATH_CHARS})"),
)
# Python writes: open("f", "w"/"a"/"x"…), Path("f").write_text(...).
_PY_WRITE_RES = (
    re.compile(r"open\(\s*[rbfu]?['\"]([^'\"]+)['\"]\s*,\s*[rbfu]?['\"][^'\"]*[wax]"),
    re.compile(r"Path\(\s*[rbfu]?['\"]([^'\"]+)['\"]\s*\)\s*\.\s*write_(?:text|bytes)\("),
)
_NOT_FILES = frozenset({"/dev/null", "/dev/stdout", "/dev/stderr", "&1", "&2"})

# Commands that run, build, test or lint something. A command that only writes is not one.
_VERIFY_RE = re.compile(
    r"(?:^|[;&|(\s])(?:"
    r"pytest|py\.test|tox|nox|unittest|mypy|ruff|flake8|pylint|pyright|black\s+--check"
    r"|python3?(?:\.\d+)?\s+(?!-m\s+pip\b)(?:-\w+\s+)*\S"
    r"|uv\s+run|poetry\s+run|pipenv\s+run"
    r"|node\s+\S|deno\s+(?:run|test|check)|bun\s+(?:run|test|x)"
    r"|(?:npm|pnpm|yarn)\s+(?:run\s+\S+|test|t|start|build|lint|check|exec)\b"
    r"|npx\s+\S|tsc\b|vite\s+build|vitest|jest|eslint|playwright|esbuild|webpack"
    r"|cargo\s+(?:build|test|check|run|clippy)|go\s+(?:build|test|run|vet)"
    r"|make\b|cmake\b|ninja\b|gcc\b|g\+\+|clang\b|javac\b|java\s+\S|mvn\b|gradlew?\b"
    r"|dotnet\s+(?:build|test|run)|swift\s+(?:build|test|run)|rustc\b|zig\s+(?:build|run|test)"
    r"|php\s+\S|ruby\s+\S|rspec\b|rake\b|perl\s+\S|lua\s+\S|Rscript\b|julia\s+\S"
    r"|(?:ba|z)?sh\s+\S+\.sh|\./\S+|curl\s|wget\s|shellcheck\b|htmlhint|stylelint"
    r")"
)


def verify_after_writes_limit() -> int:
    """GANJALF_VERIFY_AFTER_WRITES (default 6; 0 or "off" turns the note off)."""
    raw = (os.environ.get("GANJALF_VERIFY_AFTER_WRITES") or "").strip().lower()
    if not raw:
        return DEFAULT_VERIFY_AFTER_WRITES
    if raw in ("off", "no", "false", "none"):
        return 0
    try:
        return max(0, int(raw))
    except ValueError:
        return DEFAULT_VERIFY_AFTER_WRITES


def check_page_gate_enabled() -> bool:
    """GANJALF_CHECK_PAGE_GATE (default on; 0/off turns the final-answer reminder off)."""
    raw = (os.environ.get("GANJALF_CHECK_PAGE_GATE") or "").strip().lower()
    return raw not in ("0", "off", "no", "false", "none")


def _clean_path(raw: str) -> Optional[str]:
    path = raw.strip().strip("'\"").rstrip(";,)")
    if not path or path in _NOT_FILES or path.startswith("&") or "$" in path:
        return None
    return path


def _ext(path: str) -> str:
    return PurePosixPath(path).suffix.lower()


def written_paths(tool_name: str, arguments: Mapping[str, Any]) -> list[str]:
    """Files a call writes, as far as its arguments show (a heuristic: empty when unsure)."""
    if tool_name == "edit_file":
        path = arguments.get("path")
        return [path] if isinstance(path, str) and path.strip() else []
    if tool_name == "terminal":
        text = arguments.get("command")
        patterns: Iterable[re.Pattern] = _SHELL_WRITE_RES
    elif tool_name == "python":
        text = arguments.get("code")
        patterns = _PY_WRITE_RES
    else:
        return []
    if not isinstance(text, str):
        return []
    found: list[str] = []
    for pattern in patterns:
        for match in pattern.finditer(text):
            path = _clean_path(match.group(1))
            if path and path not in found:
                found.append(path)
    return found


def runs_something(tool_name: str, arguments: Mapping[str, Any]) -> bool:
    """Whether a call runs, builds or tests code (what the write counter waits for)."""
    if tool_name == "check_page":
        return True
    if tool_name == "terminal":
        command = arguments.get("command")
        return isinstance(command, str) and bool(_VERIFY_RE.search(command))
    if tool_name == "python":
        # Running code is a check unless all it does is write files.
        code = arguments.get("code")
        if not isinstance(code, str) or not code.strip():
            return False
        if not written_paths("python", arguments):
            return True
        return bool(re.search(r"\b(?:print\s*\(|assert\b|subprocess\b|unittest\b|pytest\b|runpy\b|exec\s*\()", code))
    return False


class WorkLedger:
    """Per-response ledger behind the two reminders; never raises into the loop."""

    def __init__(self) -> None:
        self._writes_since_check = 0
        self._unchecked_web: list[str] = []
        self._page_reminder_used = False
        self._limit = verify_after_writes_limit()

    @property
    def unchecked_web_files(self) -> tuple[str, ...]:
        return tuple(self._unchecked_web)

    def note_call(self, tool_name: str, arguments: Any, failed: bool) -> str:
        """Record an executed call; returns a note for the model, or ""."""
        try:
            return self._note_call(tool_name, arguments if isinstance(arguments, Mapping) else {}, failed)
        except Exception:  # noqa: BLE001 -- a guard must never break the loop
            return ""

    def _note_call(self, tool_name: str, arguments: Mapping[str, Any], failed: bool) -> str:
        if tool_name == "check_page":
            # Any attempt clears the gate: a failing or unavailable check must not trap the model.
            self._unchecked_web.clear()
            self._writes_since_check = 0
            return ""
        ran = runs_something(tool_name, arguments)
        paths = [] if (failed and tool_name == "edit_file") else written_paths(tool_name, arguments)
        for path in paths:
            if _ext(path) in _WEB_EXTS and path not in self._unchecked_web:
                self._unchecked_web.append(path)
        if ran:
            self._writes_since_check = 0
            return ""
        if not paths:
            return ""
        self._writes_since_check += 1
        if not self._limit or self._writes_since_check < self._limit:
            return ""
        count, self._writes_since_check = self._writes_since_check, 0
        return (
            f"\n\n[Ganjalf] {count} file writes in a row without running anything. If what you "
            "changed can be checked now (build, tests, running the script, check_page for a web "
            "page), do that before writing more; if nothing can be checked yet, carry on."
        )

    def page_files_to_check(self, workdir: Optional[str]) -> list[str]:
        """Unchecked files that belong to a web page (JS/TS only beside an HTML file)."""
        pages: list[str] = []
        root = Path(workdir).resolve() if workdir else None
        for path in self._unchecked_web:
            if _ext(path) in _MARKUP_EXTS:
                pages.append(path)
            elif root is not None and _has_html_nearby(root, path):
                pages.append(path)
        return pages

    def check_page_reminder(self, *, offered: bool, workdir: Optional[str]) -> Optional[str]:
        """The one-time final-answer reminder, or None (off, not offered, used, or nothing to check)."""
        try:
            if self._page_reminder_used or not offered or not check_page_gate_enabled():
                return None
            files = self.page_files_to_check(workdir)
            if not files:
                return None
            self._page_reminder_used = True
            shown = ", ".join(files[:6]) + (" …" if len(files) > 6 else "")
            return (
                f"Before finishing: you changed web files ({shown}) but did not run check_page "
                "after the last change. Run check_page once on the HTML page that uses them, fix "
                "any error it reports, then give your final answer. If the page cannot be checked "
                "(no HTML entry point, check_page unavailable), say so in one line and finish."
            )
        except Exception:  # noqa: BLE001
            return None


def _has_html_nearby(root: Path, rel_path: str) -> bool:
    """An .html file in the script's folder or up to two folders above it, inside the workdir."""
    try:
        target = (root / rel_path).resolve()
        folder = target.parent
        for _ in range(3):
            if root != folder and root not in folder.parents:
                return False
            if folder.is_dir() and any(
                child.suffix.lower() in (".html", ".htm") for child in folder.iterdir() if child.is_file()
            ):
                return True
            if folder == root:
                return False
            folder = folder.parent
    except OSError:
        return False
    return False
