"""Ganjalf: Claude Code-style tools for the coding agent.

* ``todo_write`` - the task list (Claude Code's TodoWrite): the model writes its plan, keeps one
  item in progress and ticks items off; the chat shows it as a checklist.
* ``read_file`` - numbered lines of a file, by range (Read).
* ``grep`` - search file contents with a regular expression (Grep).
* ``glob`` - list files by pattern, newest first (Glob).

They are offered with the local code tools (terminal), read only the conversation's working
directory (the same paths edit_file may use), and never run code.
"""

from __future__ import annotations

import fnmatch
import os
import re
import threading
from typing import Optional

TODO_STATUSES = ("pending", "in_progress", "completed")
MAX_TODOS = 40
READ_DEFAULT_LINES = 400
READ_MAX_LINES = 2000
READ_MAX_CHARS = 60_000
LINE_MAX_CHARS = 2000
GREP_MAX_MATCHES = 200
GREP_MAX_FILE_BYTES = 2 * 1024 * 1024
GLOB_MAX_RESULTS = 300
SCAN_MAX_FILES = 20_000
# Folders a search skips unless the pattern or path names them.
SKIPPED_DIRS = frozenset(
    {
        ".git",
        "node_modules",
        ".venv",
        "venv",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".next",
        ".cache",
        "dist",
        "build",
        ".ganjalf",
    }
)

_todos_lock = threading.Lock()
_todos: dict[str, list[dict]] = {}
# Same list sent again, in a row: the model is circling, not working.
_todo_repeats: dict[str, int] = {}
# A result that starts with this changed nothing; the tool loop counts these to stop the circling.
TODO_UNCHANGED = "No change:"


# --- todo_write ---------------------------------------------------------------------------


def todo_write(arguments: dict, session_id: Optional[str]) -> str:
    todos = (arguments or {}).get("todos")
    if isinstance(todos, str):
        import json
        try:
            todos = json.loads(todos)
        except ValueError:
            return "Error: todos must be a list of {content, status} objects."
    if not isinstance(todos, list) or not todos:
        return "Error: todos must be a non-empty list of {content, status} objects."
    if len(todos) > MAX_TODOS:
        return f"Error: at most {MAX_TODOS} items; group small steps together."
    clean = []
    for item in todos:
        if not isinstance(item, dict):
            return "Error: each item needs content and status."
        content = str(item.get("content") or "").strip()
        status = str(item.get("status") or "pending").strip().lower()
        if not content:
            return "Error: an item has no content."
        if status not in TODO_STATUSES:
            return f"Error: status must be one of {', '.join(TODO_STATUSES)} (got {status!r})."
        entry = {"content": content[:300], "status": status}
        active = str(item.get("activeForm") or item.get("active_form") or "").strip()
        if active:
            entry["activeForm"] = active[:300]
        clean.append(entry)
    key = session_id or "_"
    with _todos_lock:
        # No status moved: a reworded item is not progress (models reword to look busy).
        previous = _todos.get(key)
        unchanged = previous is not None and [item["status"] for item in previous] == [
            item["status"] for item in clean
        ]
        _todo_repeats[key] = _todo_repeats.get(key, 0) + 1 if unchanged else 0
        repeats = _todo_repeats[key]
        _todos[key] = clean
    if unchanged:
        return _unchanged_note(clean, repeats)
    done = sum(item["status"] == "completed" for item in clean)
    doing = [item for item in clean if item["status"] == "in_progress"]
    marks = {"completed": "[x]", "in_progress": "[>]", "pending": "[ ]"}
    lines = [f"{marks[item['status']]} {item['content']}" for item in clean]
    advice = []
    if len(doing) > 1:
        advice.append("Keep exactly one item in_progress at a time.")
    if not doing and done < len(clean):
        advice.append("Mark the item you start now as in_progress.")
    if done == len(clean):
        advice.append("All items are done: verify the result, then give the final answer.")
    else:
        advice.append("Update the list as soon as an item is done (do not batch the updates).")
    return (
        f"Task list updated ({done}/{len(clean)} done):\n"
        + "\n".join(lines)
        + "\n"
        + " ".join(advice)
    )


def _unchanged_note(clean: list[dict], repeats: int) -> str:
    """The list did not move: name the one thing to do, so the next call is the work itself."""
    doing = next((item for item in clean if item["status"] == "in_progress"), None)
    doing = doing or next((item for item in clean if item["status"] == "pending"), None)
    times = "" if repeats < 2 else f" You have now sent it {repeats + 1} times in a row."
    if doing is None:
        step = "Every item is completed: verify the result, then give the final answer."
    else:
        step = (
            f"Do this item now: '{doing['content']}'. Your next tool call must be that work "
            "itself, e.g. edit_file to write a file or terminal to run a command. If it is "
            "already done, mark it completed and set the next one in_progress."
        )
    return (
        f"{TODO_UNCHANGED} no item changed status since the list you last sent, so this "
        f"call did nothing useful.{times} Do not call todo_write again until an item's status "
        f"changes. {step}"
    )


def current_todos(session_id: Optional[str]) -> list[dict]:
    with _todos_lock:
        return list(_todos.get(session_id or "_", []))


# --- read_file ------------------------------------------------------------------------------


def _resolve(raw: str, session_id, disable_sandbox) -> tuple[Optional[str], str]:
    from .tools import _STUDIO_CREDENTIAL_BLOCKED, _edit_file_resolve, _references_studio_credential

    if _references_studio_credential(str(raw or "")):
        return None, _STUDIO_CREDENTIAL_BLOCKED
    target, error = _edit_file_resolve(str(raw or ""), session_id, disable_sandbox)
    if error:
        return None, error.replace("edit_file can write", "these tools can read")
    if _references_studio_credential(target):
        return None, _STUDIO_CREDENTIAL_BLOCKED
    return target, ""


def _shown(path: str, session_id) -> str:
    """Path as the model should pass it back: relative to the working directory when inside it."""
    from .tools import _get_workdir

    try:
        workdir = os.path.realpath(_get_workdir(session_id))
        relative = os.path.relpath(path, workdir)
    except (OSError, ValueError):
        return path
    return path if relative.startswith("..") else relative.replace(os.sep, "/")


def _int(value, default: int, low: int, high: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


def read_file(
    arguments: dict,
    session_id: Optional[str],
    disable_sandbox: bool = False,
) -> str:
    arguments = arguments or {}
    target, error = _resolve(arguments.get("path"), session_id, disable_sandbox)
    if error:
        return error
    if os.path.isdir(target):
        return f"Error: {arguments.get('path')} is a folder; use glob to list it."
    if not os.path.isfile(target):
        return f"Error: {arguments.get('path')} does not exist. Use glob to find the file."
    with open(target, "rb") as handle:
        head = handle.read(8192)
    if b"\x00" in head:
        return f"Error: {arguments.get('path')} is a binary file (use view_image for images)."
    offset = _int(arguments.get("offset"), 1, 1, 10**9)
    limit = _int(arguments.get("limit"), READ_DEFAULT_LINES, 1, READ_MAX_LINES)
    out: list[str] = []
    chars = 0
    total = 0
    stopped_at = None
    with open(target, "r", encoding = "utf-8", errors = "replace") as handle:
        for number, line in enumerate(handle, start = 1):
            total = number
            if number < offset:
                continue
            if stopped_at is not None:
                continue
            text = line.rstrip("\n").rstrip("\r")
            if len(text) > LINE_MAX_CHARS:
                text = text[:LINE_MAX_CHARS] + f" ... ({len(text) - LINE_MAX_CHARS} chars cut)"
            entry = f"{number:>6}\t{text}"
            if len(out) >= limit or chars + len(entry) > READ_MAX_CHARS:
                stopped_at = number
                continue
            out.append(entry)
            chars += len(entry) + 1
    if total == 0:
        return f"{arguments.get('path')} is empty."
    if offset > total:
        return f"Error: {arguments.get('path')} has {total} lines; offset {offset} is past the end."
    shown_to = offset + len(out) - 1
    footer = (
        f"\n\n(lines {offset}-{shown_to} of {total}; continue with offset={stopped_at})"
        if stopped_at is not None
        else f"\n\n(lines {offset}-{shown_to} of {total})"
    )
    return "\n".join(out) + footer


# --- grep / glob ----------------------------------------------------------------------------


def _walk(root: str, include_skipped: bool):
    """Files under root, skipping heavy folders; stops after SCAN_MAX_FILES."""
    seen = 0
    for folder, dirs, files in os.walk(root):
        dirs[:] = sorted(
            d for d in dirs if include_skipped or (d not in SKIPPED_DIRS and not d.startswith("."))
        )
        for name in sorted(files):
            seen += 1
            if seen > SCAN_MAX_FILES:
                return
            yield os.path.join(folder, name)


def _matches_glob(relative: str, pattern: str) -> bool:
    if not pattern:
        return True
    relative = relative.replace(os.sep, "/")
    patterns = [p.strip() for p in pattern.split(",") if p.strip()]
    for item in patterns:
        if "/" in item or "**" in item:
            if fnmatch.fnmatch(relative, item) or fnmatch.fnmatch(
                relative, item.replace("**/", "")
            ):
                return True
        elif fnmatch.fnmatch(os.path.basename(relative), item):
            return True
    return False


def grep(
    arguments: dict,
    session_id: Optional[str],
    disable_sandbox: bool = False,
) -> str:
    arguments = arguments or {}
    pattern = str(arguments.get("pattern") or "")
    if not pattern:
        return "Error: 'pattern' is required."
    flags = re.IGNORECASE if arguments.get("ignore_case") is True else 0
    try:
        regex = re.compile(pattern, flags)
    except re.error as exc:
        return f"Error: invalid regular expression ({exc}). Escape special characters such as ( [ . with a backslash."
    root, error = _resolve(arguments.get("path") or ".", session_id, disable_sandbox)
    if error:
        return error
    include = str(arguments.get("glob") or "")
    context = _int(arguments.get("context"), 0, 0, 5)
    files_only = arguments.get("files_only") is True
    candidates = (
        [root]
        if os.path.isfile(root)
        else _walk(root, include_skipped = any(d in pattern + include for d in SKIPPED_DIRS))
    )
    base = root if os.path.isdir(root) else os.path.dirname(root)
    hits: list[str] = []
    matched_files: list[str] = []
    count = 0
    for path in candidates:
        relative = os.path.relpath(path, base)
        if include and not _matches_glob(relative, include):
            continue
        try:
            if os.path.getsize(path) > GREP_MAX_FILE_BYTES:
                continue
            with open(path, "rb") as handle:
                data = handle.read()
        except OSError:
            continue
        if b"\x00" in data[:8192]:
            continue
        lines = data.decode("utf-8", errors = "replace").splitlines()
        found = [i for i, line in enumerate(lines) if regex.search(line)]
        if not found:
            continue
        shown_path = _shown(path, session_id)
        matched_files.append(shown_path)
        if files_only:
            continue
        shown = set()
        for index in found:
            for j in range(max(0, index - context), min(len(lines), index + context + 1)):
                if j in shown:
                    continue
                shown.add(j)
                marker = ":" if j == index else "-"
                text = lines[j] if len(lines[j]) <= 300 else lines[j][:300] + " ..."
                hits.append(f"{shown_path}{marker}{j + 1}{marker}{text}")
            count += 1
            if count >= GREP_MAX_MATCHES:
                break
        if count >= GREP_MAX_MATCHES:
            break
    if not matched_files:
        return (
            f"No matches for /{pattern}/"
            + (f" in files matching {include}" if include else "")
            + "."
        )
    if files_only:
        return f"{len(matched_files)} file(s) match:\n" + "\n".join(matched_files)
    more = (
        f"\n(stopped at {GREP_MAX_MATCHES} matches; narrow the pattern or the glob)"
        if count >= GREP_MAX_MATCHES
        else ""
    )
    return f"{count} match(es) in {len(matched_files)} file(s):\n" + "\n".join(hits) + more


def glob(
    arguments: dict,
    session_id: Optional[str],
    disable_sandbox: bool = False,
) -> str:
    arguments = arguments or {}
    pattern = str(arguments.get("pattern") or "**/*").strip()
    root, error = _resolve(arguments.get("path") or ".", session_id, disable_sandbox)
    if error:
        return error
    if not os.path.isdir(root):
        return f"Error: {arguments.get('path')} is not a folder."
    found = []
    for path in _walk(root, include_skipped = any(d in pattern for d in SKIPPED_DIRS)):
        relative = os.path.relpath(path, root).replace(os.sep, "/")
        if _matches_glob(relative, pattern):
            try:
                found.append(
                    (os.path.getmtime(path), _shown(path, session_id), os.path.getsize(path))
                )
            except OSError:
                continue
    if not found:
        return f"No files match {pattern}."
    found.sort(key = lambda item: -item[0])
    shown = found[:GLOB_MAX_RESULTS]
    lines = [f"{relative} ({_size(size)})" for _, relative, size in shown]
    more = (
        f"\n... and {len(found) - len(shown)} more; narrow the pattern."
        if len(found) > len(shown)
        else ""
    )
    return f"{len(found)} file(s), newest first:\n" + "\n".join(lines) + more


def _size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / 1024 / 1024:.1f} MB"


# --- schemas -------------------------------------------------------------------------------

TODO_WRITE_TOOL = {
    "type": "function",
    "function": {
        "name": "todo_write",
        "description": (
            "Write or update your task list for this job; the user sees it as a checklist. Use it "
            "for any task with 3 or more steps: write the plan first (small steps that each end in "
            "something you can run or check), keep exactly one item in_progress, and mark each "
            "item completed as soon as it is done. Call it only when a status changes, never "
            "twice in a row: between two calls there must be real work (a file written, a "
            "command run). Send the whole list every time."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "todos": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "content": {
                                "type": "string",
                                "description": "The step, imperative (e.g. 'Add the camera').",
                            },
                            "status": {"type": "string", "enum": list(TODO_STATUSES)},
                            "activeForm": {
                                "type": "string",
                                "description": "Present tense shown while in progress (e.g. 'Adding the camera').",
                            },
                        },
                        "required": ["content", "status"],
                    },
                }
            },
            "required": ["todos"],
        },
    },
}

READ_FILE_TOOL = {
    "type": "function",
    "function": {
        "name": "read_file",
        "description": (
            "Read a text file with numbered lines. Without offset/limit it returns the first "
            f"{READ_DEFAULT_LINES} lines; for a big file read the part you need (find it with grep "
            "first). Use this instead of cat/sed/head in the terminal."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path, relative to the working directory.",
                },
                "offset": {"type": "integer", "description": "First line to read (1-based)."},
                "limit": {
                    "type": "integer",
                    "description": f"How many lines (max {READ_MAX_LINES}).",
                },
            },
            "required": ["path"],
        },
    },
}

GREP_TOOL = {
    "type": "function",
    "function": {
        "name": "grep",
        "description": (
            "Search file contents with a regular expression and get file:line:text matches. "
            "Skips node_modules, .git, dist and build unless named. Use it to find where something "
            "is defined or used before reading or editing."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Regular expression (Python syntax)."},
                "path": {
                    "type": "string",
                    "description": "Folder or file to search (default: the working directory).",
                },
                "glob": {
                    "type": "string",
                    "description": "Only files matching this, e.g. '*.ts' or 'src/**/*.tsx'; comma-separate several.",
                },
                "ignore_case": {"type": "boolean"},
                "context": {
                    "type": "integer",
                    "description": "Lines of context around each match (0-5).",
                },
                "files_only": {"type": "boolean", "description": "Only list the files that match."},
            },
            "required": ["pattern"],
        },
    },
}

GLOB_TOOL = {
    "type": "function",
    "function": {
        "name": "glob",
        "description": (
            "List files matching a pattern (e.g. 'src/**/*.ts', '*.html'), newest first, with sizes. "
            "Use it to see a project's layout instead of ls/find."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Glob pattern; default '**/*'."},
                "path": {
                    "type": "string",
                    "description": "Folder to search (default: the working directory).",
                },
            },
        },
    },
}


EXIT_PLAN_MODE_TOOL = {
    "type": "function",
    "function": {
        "name": "exit_plan_mode",
        "description": (
            "You are in PLAN MODE: the user wants to approve a plan before anything is changed. "
            "Explore with the read-only tools (read_file, grep, glob, web search) until you know "
            "what to do, then call this once with the plan: the goal, the files you will create "
            "or change, the steps in order with how each will be checked, and the risks or "
            "questions. Do not try to edit files or run commands in plan mode. After this call, "
            "end your turn and wait for the user's approval."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "plan": {"type": "string", "description": "The plan in Markdown."},
            },
            "required": ["plan"],
        },
    },
}

# What plan mode keeps: reading, searching, the web, pages, images, the task list, skills.
PLAN_MODE_TOOL_NAMES = frozenset(
    {
        "read_file",
        "grep",
        "glob",
        "web_search",
        "view_image",
        "check_page",
        "todo_write",
        "read_skill",
    }
)
PLAN_APPROVAL_TAG = "[awaiting_plan_approval]"

# Said in the system prompt, not only in the tool list: a model that sees no terminal or
# edit_file otherwise concludes it cannot write files and pastes the whole program as text.
PLAN_MODE_TIP = (
    "PLAN MODE IS ON (the user switched it on). This turn is for exploring and planning, not "
    "building: you have only read-only tools on purpose, and terminal, edit_file and the other "
    "editing tools come back as soon as the user approves the plan. Look at the project with "
    "glob, grep and read_file (an empty or new folder is fine: then plan from the request), "
    "then call exit_plan_mode with a concrete plan: the files you will create or change, the "
    "steps in order, and how you will check the result. Do not write the code or the contents "
    "of files in your reply and do not ask the user to copy code: after approval you create "
    "and run everything yourself. A plan names files and steps, it does not design the code: "
    "as soon as you know them, call exit_plan_mode instead of thinking further."
)


def plan_mode_on(tools) -> bool:
    return any(
        isinstance(tool, dict) and (tool.get("function") or {}).get("name") == "exit_plan_mode"
        for tool in tools or ()
    )


def apply_plan_mode(tools: list[dict]) -> list[dict]:
    """Read-only tools plus exit_plan_mode; read/grep/glob are added when terminal was offered."""
    names = {tool["function"]["name"] for tool in tools}
    kept = [tool for tool in tools if tool["function"]["name"] in PLAN_MODE_TOOL_NAMES]
    if "terminal" in names or "edit_file" in names:
        have = {tool["function"]["name"] for tool in kept}
        kept += [
            tool
            for tool in (READ_FILE_TOOL, GREP_TOOL, GLOB_TOOL, TODO_WRITE_TOOL)
            if tool["function"]["name"] not in have
        ]
    return kept + [EXIT_PLAN_MODE_TOOL]


def exit_plan_mode(arguments: dict) -> str:
    plan = str((arguments or {}).get("plan") or "").strip()
    if not plan:
        return "Error: give the plan in 'plan'."
    return (
        f"{PLAN_APPROVAL_TAG} The user now sees this plan in a card with an Approve button. End "
        "your turn with one or two short sentences: an open question if you have one, otherwise "
        "ask whether to proceed. Do not repeat or summarise the plan (it is already on screen) "
        "and do not start the work."
    )


def code_agent_tools() -> list[dict]:
    """The tools offered beside terminal (GANJALF_AGENT_TOOLS=0 leaves them out)."""
    if (os.environ.get("GANJALF_AGENT_TOOLS") or "").strip().lower() in ("0", "off", "no", "false"):
        return []
    from .background_jobs import TERMINAL_KILL_TOOL, TERMINAL_OUTPUT_TOOL

    return [
        TODO_WRITE_TOOL,
        READ_FILE_TOOL,
        GREP_TOOL,
        GLOB_TOOL,
        TERMINAL_OUTPUT_TOOL,
        TERMINAL_KILL_TOOL,
    ]


CODE_AGENT_TOOL_NAMES = frozenset(
    {"todo_write", "read_file", "grep", "glob", "terminal_output", "terminal_kill"}
)
