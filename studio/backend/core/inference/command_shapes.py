"""Ganjalf: small readings of what a model asked for, so a slow local model wastes fewer rounds.

- ``promoted_background`` turns ``nohup npx vite > vite.log 2>&1 & echo $! > vite.pid`` into a
  background job: in the sandbox a process left behind with ``&`` dies when the call returns, so
  the model otherwise spends several rounds finding out why its server is gone.
- ``compile_errors_note`` asks for every listed compiler error to be fixed before the next run.
- ``removed_definitions_note`` reports functions and methods an edit deleted, the usual way a
  rewrite of a big file silently drops code that is still called.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Optional

# --- `&` at the end of a command -------------------------------------------------------------


def _background_ampersands(command: str) -> Optional[list[int]]:
    """Positions of job-control ``&`` outside quotes; None when the shape is too hairy to read."""
    if "<<" in command or "`" in command:
        return None
    found: list[int] = []
    quote = ""
    i = 0
    while i < len(command):
        ch = command[i]
        if quote:
            if ch == "\\" and quote == '"':
                i += 2
                continue
            if ch == quote:
                quote = ""
        elif ch == "\\":
            i += 2
            continue
        elif ch in ("'", '"'):
            quote = ch
        elif ch == "&":
            prev = command[i - 1] if i else ""
            nxt = command[i + 1] if i + 1 < len(command) else ""
            if nxt == "&":  # &&
                i += 2
                continue
            if prev not in (">", "<", "|", "&") and nxt != ">":
                found.append(i)
        i += 1
    return None if quote else found


# What may follow the `&` and still be dropped: bookkeeping about the process just started.
_HARMLESS_TAIL = re.compile(
    r"""^(?:
        echo\s+["']?\$!["']?(?:\s*>{1,2}\s*\S+)?   # echo $! > app.pid
        | disown(?:\s+-?\w+)?
        | sleep\s+\d+(?:\.\d+)?
        | true
    )$""",
    re.VERBOSE,
)
_REDIRECT_TO_FILE = re.compile(
    r"\s*(?:(?P<both>&>{1,2})\s*(?P<f1>[^\s&|;]+)"
    r"|(?P<out>1?>{1,2})\s*(?P<f2>[^\s&|;]+)(?:\s+2>&1)?)"
    r"(?:\s+<\s*/dev/null)?\s*$"
)
_NOHUP = re.compile(r"(^|&&\s*|;\s*)nohup\s+")


def promoted_background(command: str) -> Optional[str]:
    """The command to run as a background job when ``command`` only starts one process with
    ``&`` and then does bookkeeping; None otherwise."""
    if not isinstance(command, str) or "&" not in command:
        return None
    marks = _background_ampersands(command)
    if not marks or len(marks) != 1:
        return None
    head, tail = command[: marks[0]].rstrip(), command[marks[0] + 1 :].strip()
    for part in re.split(r"\s*(?:;|&&)\s*", tail) if tail else []:
        if part and not _HARMLESS_TAIL.match(part):
            return None
    if not head or head.endswith(("|", "&&", ";")):
        return None
    head = _NOHUP.sub(r"\1", head).strip()
    # Keep the log file the model will read, but let the job see the output too.
    redirect = _REDIRECT_TO_FILE.search(head)
    if redirect and redirect.group(0).strip():
        target = redirect.group("f1") or redirect.group("f2")
        if target and target != "/dev/null":
            append = (redirect.group("both") or redirect.group("out") or "").endswith(">>")
            head = head[: redirect.start()] + f" 2>&1 | tee {'-a ' if append else ''}{target}"
        else:
            head = head[: redirect.start()]
    head = head.strip()
    return head or None


BACKGROUND_AMPERSAND_NOTE = (
    "\n[A process started with `&` or nohup is stopped when this call returns. "
    "To keep a server or watcher running, call terminal with run_in_background: true "
    "and read it with terminal_output.]"
)


def leaves_background_process(command: str) -> bool:
    marks = _background_ampersands(command) if isinstance(command, str) else None
    return bool(marks)


# --- compiler output -----------------------------------------------------------------------

_ERROR_LINE = re.compile(
    r"(?m)^(?:\S+\(\d+,\d+\): error TS\d+|\S+:\d+:\d+(?: -)? error\b|error TS\d+:|ERROR in \S+)"
)


# Last full error count per (session, check command), to say when edits made it worse.
_LAST_ERROR_COUNTS: dict[tuple[str, str], int] = {}
_MAX_REMEMBERED_CHECKS = 200
_CUT_OUTPUT_RE = re.compile(r"\|\s*(?:head|tail|grep|less|more)\b")


def _check_key(session_id, command: str) -> "tuple[str, str] | None":
    command = " ".join(str(command or "").split())
    if not command or _CUT_OUTPUT_RE.search(command):
        return None  # a cut list cannot be compared with a whole one
    return (str(session_id or ""), command.replace(" 2>&1", ""))


def compile_errors_note(
    output: str,
    session_id = None,
    command: str = "",
) -> str:
    if not isinstance(output, str):
        return ""
    count = len(_ERROR_LINE.findall(output))
    key = _check_key(session_id, command) if command else None
    before = _LAST_ERROR_COUNTS.get(key) if key else None
    if key:
        if len(_LAST_ERROR_COUNTS) >= _MAX_REMEMBERED_CHECKS and key not in _LAST_ERROR_COUNTS:
            _LAST_ERROR_COUNTS.pop(next(iter(_LAST_ERROR_COUNTS)))
        _LAST_ERROR_COUNTS[key] = count
    worse = ""
    if before is not None and count > before:
        worse = (
            f" That is MORE than the {before} of the previous run: your edits since then made it "
            "worse. Undo the change that caused the new errors (they name the file and line) "
            "instead of patching around it; for missing types, import the real module rather "
            "than declaring your own."
        )
    if count < 2:
        return f"\n[{worse.strip()}]" if worse else ""
    return (
        f"\n[{count} errors listed. Fix all of them in one edit_file call (one entry in 'edits' "
        "per fix, or one call per file) before running the check again; if the list was cut "
        f"short, run the check once without head to see them all.{worse}]"
    )


# --- definitions an edit removed -----------------------------------------------------------

_CODE_EXTENSIONS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".py", ".vue", ".svelte")
_KEYWORDS = frozenset(
    "if for while switch catch function return constructor super with elif else do try".split()
)
_DEFINITION_RES = (
    re.compile(
        r"(?m)^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*([A-Za-z_$][\w$]*)"
    ),
    re.compile(r"(?m)^\s*(?:export\s+)?(?:default\s+)?(?:abstract\s+)?class\s+([A-Za-z_$][\w$]*)"),
    re.compile(
        r"(?m)^[ \t]+(?:(?:public|private|protected|static|async|readonly|override|get|set)\s+)*"
        r"([A-Za-z_$][\w$]*)\s*(?:<[^>()]*>)?\s*\([^()]*(?:\([^()]*\)[^()]*)*\)\s*(?::\s*[^{=;]+)?\{"
    ),
    re.compile(
        r"(?m)^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?"
        r"(?:\([^()]*\)|[A-Za-z_$][\w$]*)\s*(?::\s*[^=]+)?=>"
    ),
    re.compile(r"(?m)^\s*(?:async\s+)?def\s+([A-Za-z_]\w*)"),
)


def _definitions(text: str) -> Counter:
    names: Counter = Counter()
    for pattern in _DEFINITION_RES:
        for name in pattern.findall(text):
            if name not in _KEYWORDS:
                names[name] += 1
    return names


def removed_definitions_note(path: str, before: str, after: str) -> str:
    if not isinstance(path, str) or not path.lower().endswith(_CODE_EXTENSIONS):
        return ""
    if not isinstance(before, str) or not isinstance(after, str) or before == after:
        return ""
    was, now = _definitions(before), _definitions(after)
    gone = [name for name in was if name not in now]
    if not gone:
        return ""
    still_used = [name for name in gone if re.search(rf"(?<![\w$]){re.escape(name)}\s*\(", after)]
    shown = ", ".join(gone[:8]) + (f" and {len(gone) - 8} more" if len(gone) > 8 else "")
    note = f"\n[This edit removed: {shown}."
    if still_used:
        note += f" Still called in this file: {', '.join(still_used[:8])}."
    return note + " If that was not intended, put them back now.]"
