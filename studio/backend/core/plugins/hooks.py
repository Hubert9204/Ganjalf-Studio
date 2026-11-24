# SPDX-License-Identifier: AGPL-3.0-only
# Copyright 2026-present the Unsloth AI Inc. team. All rights reserved. See /studio/LICENSE.AGPL-3.0

"""Plugin hooks: commands run on agent events, with Claude Code's input and output contract.

Only plugins the user switched hooks on for take part. Each hook gets the event as JSON on stdin
and ``CLAUDE_PLUGIN_ROOT``, ``CLAUDE_PLUGIN_DATA`` and ``CLAUDE_PROJECT_DIR`` (the chat's working
folder) in its environment, and runs there with its timeout (60 s by default).

    exit 0   stdout may be JSON: {"decision": "block", "reason"}, {"continue": false, "stopReason"},
             {"hookSpecificOutput": {"permissionDecision": "deny", "permissionDecisionReason",
             "additionalContext"}}, {"systemMessage"}; plain stdout of UserPromptSubmit and
             SessionStart becomes context for the model
    exit 2   blocks; stderr is the reason
    other    a non-blocking error, logged

Studio's tools are shown to hooks under Claude Code's names where one exists (terminal is Bash,
edit_file is Edit, MultiEdit or Write, view_image is Read, web_search is WebSearch), so matchers
like ``Edit|Write`` and ``if: "Bash(git commit*)"`` work unchanged.
"""

from __future__ import annotations

import fnmatch
import json
import logging
import os
import re
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_S = 60
MAX_TIMEOUT_S = 600
MAX_OUTPUT_CHARS = 8_000
MAX_STOP_BLOCKS = 3

_cache_lock = threading.Lock()
_cache: dict = {"key": None, "hooks": {}}


@dataclass
class Outcome:
    blocked: bool = False
    reasons: list[str] = field(default_factory = list)
    context: list[str] = field(default_factory = list)
    messages: list[str] = field(default_factory = list)
    cancelled: bool = False

    @property
    def reason(self) -> str:
        return "\n".join(self.reasons)


def _registry_key() -> Optional[tuple]:
    from .manager import _registry_path

    path = _registry_path()
    try:
        stat = path.stat()
    except OSError:
        return None
    return (str(path), stat.st_mtime_ns, stat.st_size)


def _all_hooks() -> dict[str, list[tuple[str, str, dict]]]:
    """event -> [(plugin, matcher, hook)] for plugins that are on with hooks on; cached on the registry."""
    key = _registry_key()
    if key is None:
        return {}
    with _cache_lock:
        if _cache["key"] == key:
            return _cache["hooks"]
    from .inspect import PluginError, inspect_plugin
    from .manager import enabled_records, plugin_dir

    hooks: dict[str, list[tuple[str, str, dict]]] = {}
    for record in enabled_records():
        if not record.get("hooks_enabled"):
            continue
        try:
            summary = inspect_plugin(plugin_dir(record["name"]))
        except (PluginError, OSError) as exc:
            logger.warning("Plugin %s hooks unreadable: %s", record["name"], exc)
            continue
        for event, groups in summary.get("hooks", {}).items():
            for group in groups:
                for hook in group["hooks"]:
                    hooks.setdefault(event, []).append((record["name"], group.get("matcher", ""), hook))
    with _cache_lock:
        _cache["key"] = key
        _cache["hooks"] = hooks
    return hooks


def has_hooks(event: Optional[str] = None) -> bool:
    hooks = _all_hooks()
    return bool(hooks.get(event)) if event else bool(hooks)


# ---------------------------------------------------------------- tool names


def claude_tool(name: str, arguments: Any, workdir: Optional[str]) -> tuple[str, dict]:
    """Studio's tool call as Claude Code would name it, for matchers and hook input."""
    args = arguments if isinstance(arguments, dict) else {}

    def absolute(path: Any) -> str:
        text = str(path or "")
        if text and workdir and not os.path.isabs(text):
            return os.path.normpath(os.path.join(workdir, text))
        return text

    if name == "terminal":
        return "Bash", {"command": str(args.get("command") or ""), "description": ""}
    if name == "edit_file":
        path = absolute(args.get("path"))
        edits = [edit for edit in args.get("edits") or [] if isinstance(edit, dict)]
        if len(edits) == 1 and not edits[0].get("old_string"):
            return "Write", {"file_path": path, "content": str(edits[0].get("new_string") or "")}
        if len(edits) == 1:
            edit = edits[0]
            return "Edit", {
                "file_path": path,
                "old_string": str(edit.get("old_string") or ""),
                "new_string": str(edit.get("new_string") or ""),
                "replace_all": bool(edit.get("replace_all")),
            }
        return "MultiEdit", {"file_path": path, "edits": edits}
    if name == "view_image":
        return "Read", {"file_path": absolute(args.get("path"))}
    if name == "web_search":
        return "WebSearch", {"query": str(args.get("query") or "")}
    if name == "python":
        return "python", {"code": str(args.get("code") or "")}
    return name, args


def _matches(matcher: str, names: tuple[str, ...]) -> bool:
    if not matcher or matcher == "*":
        return True
    try:
        pattern = re.compile(f"^(?:{matcher})$")
    except re.error:
        return matcher in names
    return any(pattern.match(name) for name in names)


def _if_matches(condition: str, tool: str, tool_input: dict) -> bool:
    """`Bash(git*commit*)`, `Edit(*.py)`, `Write`: a permission-rule style test of one call."""
    match = re.fullmatch(r"\s*([A-Za-z0-9_*|-]+)\s*(?:\((.*)\))?\s*", condition or "")
    if not match:
        return False
    if not fnmatch.fnmatchcase(tool, match[1]):
        return False
    if match[2] is None:
        return True
    subject = tool_input.get("command") or tool_input.get("file_path") or tool_input.get("url") or ""
    pattern = match[2].replace(":*", "*")
    return fnmatch.fnmatchcase(str(subject), pattern)


# ---------------------------------------------------------------- running


def _parse(stdout: str) -> Optional[dict]:
    text = stdout.strip()
    if not text.startswith("{"):
        return None
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _clip(text: str) -> str:
    text = (text or "").strip()
    return text if len(text) <= MAX_OUTPUT_CHARS else text[:MAX_OUTPUT_CHARS] + "\n... (cut)"


def _kill(process: subprocess.Popen) -> None:
    try:
        if os.name != "nt":
            import signal

            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
    except (OSError, ProcessLookupError):
        pass
    try:
        process.communicate(timeout = 5)
    except Exception:
        pass


def _run_one(
    plugin: str, hook: dict, event: str, payload: dict, cwd: str, outcome: Outcome, cancel_event = None
) -> None:
    from .manager import data_dir, expand, plugin_dir

    command = expand(hook["command"], plugin)
    timeout = min(MAX_TIMEOUT_S, max(1, float(hook.get("timeout") or DEFAULT_TIMEOUT_S)))
    env = {
        **os.environ,
        "CLAUDE_PLUGIN_ROOT": str(plugin_dir(plugin)),
        "CLAUDE_PLUGIN_DATA": str(data_dir(plugin)),
        "CLAUDE_PROJECT_DIR": cwd,
        "GANJALF_STUDIO": "1",
    }
    started = time.monotonic()
    try:
        process = subprocess.Popen(
            command,
            shell = True,
            stdin = subprocess.PIPE,
            stdout = subprocess.PIPE,
            stderr = subprocess.PIPE,
            text = True,
            cwd = cwd if os.path.isdir(cwd) else None,
            env = env,
            # Its own process group, so a stop or a timeout takes the whole hook down.
            start_new_session = os.name != "nt",
        )
    except OSError as exc:
        outcome.messages.append(f"{plugin}: {event} hook could not start: {exc}")
        return
    stdin: Optional[str] = json.dumps(payload)
    stdout = stderr = ""
    while True:
        try:
            out, err = process.communicate(input = stdin, timeout = 0.25)
            stdout, stderr = out or "", err or ""
            break
        except subprocess.TimeoutExpired:
            stdin = None
        except ValueError:
            # The input was already sent on an earlier round.
            stdin = None
            continue
        if cancel_event is not None and cancel_event.is_set():
            _kill(process)
            outcome.messages.append(f"{plugin}: {event} hook stopped with the run")
            outcome.cancelled = True
            return
        if time.monotonic() - started > timeout:
            _kill(process)
            logger.warning("Plugin %s %s hook timed out after %ss", plugin, event, timeout)
            outcome.messages.append(f"{plugin}: {event} hook timed out after {timeout:g} s")
            return
    result = subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
    logger.info("Plugin %s %s hook exit %s in %.1fs", plugin, event, result.returncode, time.monotonic() - started)
    stdout, stderr = _clip(result.stdout), _clip(result.stderr)
    if result.returncode == 2:
        outcome.blocked = True
        outcome.reasons.append(f"[{plugin}] {stderr or 'blocked by a hook'}")
        return
    if result.returncode != 0:
        outcome.messages.append(f"{plugin}: {event} hook failed ({result.returncode}): {stderr[:500]}")
        return
    data = _parse(stdout)
    if data is None:
        if stdout and event in ("UserPromptSubmit", "SessionStart"):
            outcome.context.append(f"[{plugin}] {stdout}")
        return
    specific = data.get("hookSpecificOutput") if isinstance(data.get("hookSpecificOutput"), dict) else {}
    if data.get("continue") is False:
        outcome.blocked = True
        outcome.reasons.append(f"[{plugin}] {data.get('stopReason') or 'stopped by a hook'}")
    if data.get("decision") == "block":
        outcome.blocked = True
        outcome.reasons.append(f"[{plugin}] {data.get('reason') or 'blocked by a hook'}")
    if specific.get("permissionDecision") == "deny":
        outcome.blocked = True
        outcome.reasons.append(f"[{plugin}] {specific.get('permissionDecisionReason') or 'denied by a hook'}")
    context = specific.get("additionalContext")
    if isinstance(context, str) and context.strip():
        outcome.context.append(f"[{plugin}] {_clip(context)}")
    message = data.get("systemMessage")
    if isinstance(message, str) and message.strip():
        outcome.messages.append(f"{plugin}: {_clip(message)}")


def run_event(
    event: str,
    payload: dict,
    *,
    cwd: str,
    tool_names: tuple[str, ...] = (),
    tool_input: Optional[dict] = None,
    cancel_event = None,
) -> Outcome:
    outcome = Outcome()
    entries = _all_hooks().get(event) or []
    if not entries:
        return outcome
    payload = {"hook_event_name": event, "cwd": cwd, **payload}
    for plugin, matcher, hook in entries:
        if tool_names and not _matches(matcher, tool_names):
            continue
        if hook.get("if") and not (tool_names and _if_matches(hook["if"], tool_names[0], tool_input or {})):
            continue
        if cancel_event is not None and cancel_event.is_set():
            outcome.cancelled = True
            break
        _run_one(plugin, hook, event, payload, cwd, outcome, cancel_event)
    for message in outcome.messages:
        logger.info("Plugin hook: %s", message)
    return outcome


# ---------------------------------------------------------------- the three places Studio calls


def before_tool(
    name: str, arguments: Any, *, session_id: Optional[str], workdir: str, cancel_event = None
) -> Optional[str]:
    """None to run the call, or the text that replaces its result."""
    if not has_hooks("PreToolUse"):
        return None
    tool, tool_input = claude_tool(name, arguments, workdir)
    outcome = run_event(
        "PreToolUse",
        {"session_id": session_id or "", "tool_name": tool, "tool_input": tool_input},
        cwd = workdir,
        tool_names = (tool, name),
        tool_input = tool_input,
        cancel_event = cancel_event,
    )
    if outcome.cancelled:
        return "Error: the run was stopped before this call."
    if outcome.blocked:
        return f"Error: a plugin hook blocked this call.\n{outcome.reason}"
    return None


def after_tool(
    name: str, arguments: Any, result: str, *, session_id: Optional[str], workdir: str, cancel_event = None
) -> str:
    if not has_hooks("PostToolUse") or not isinstance(result, str):
        return result
    tool, tool_input = claude_tool(name, arguments, workdir)
    response = {"output": result[:MAX_OUTPUT_CHARS]}
    if tool == "Bash":
        response["stdout"] = response["output"]
    outcome = run_event(
        "PostToolUse",
        {"session_id": session_id or "", "tool_name": tool, "tool_input": tool_input, "tool_response": response},
        cwd = workdir,
        tool_names = (tool, name),
        tool_input = tool_input,
        cancel_event = cancel_event,
    )
    notes = [*(outcome.reasons if outcome.blocked else []), *outcome.context]
    if not notes:
        return result
    # Kept outside a trailing image block (mcp_images.SENTINEL), which must stay last.
    from core.inference.mcp_images import SENTINEL

    note = "\n\nPlugin hook feedback:\n" + "\n".join(notes)
    if SENTINEL in result:
        head, tail = result.split(SENTINEL, 1)
        return head.rstrip() + note + "\n" + SENTINEL + tail
    return result + note


def prompt_context(messages: list[dict], *, session_id: Optional[str], workdir: str) -> Optional[str]:
    """SessionStart (first user message) and UserPromptSubmit: text for the system prompt, or None."""
    if not (has_hooks("UserPromptSubmit") or has_hooks("SessionStart")) or not messages:
        return None
    if messages[-1].get("role") != "user":
        return None
    content = messages[-1].get("content")
    prompt = content if isinstance(content, str) else "\n".join(
        part.get("text", "") for part in content or [] if isinstance(part, dict) and part.get("type") == "text"
    )
    parts: list[str] = []
    if sum(1 for message in messages if message.get("role") == "user") == 1:
        start = run_event("SessionStart", {"session_id": session_id or "", "source": "startup"}, cwd = workdir)
        parts.extend(start.context)
    submit = run_event("UserPromptSubmit", {"session_id": session_id or "", "prompt": prompt}, cwd = workdir)
    parts.extend(submit.context)
    if submit.blocked:
        parts.append(
            "A plugin hook refused this request. Do not carry it out; tell the user why, quoting: "
            + submit.reason
        )
    return "Plugin hooks:\n" + "\n\n".join(parts) if parts else None


def stop_check(last_text: str, *, session_id: Optional[str], workdir: str, rounds: int) -> Optional[str]:
    """When the agent is about to finish: a reason to keep working, or None."""
    if rounds >= MAX_STOP_BLOCKS or not has_hooks("Stop"):
        return None
    outcome = run_event(
        "Stop",
        {"session_id": session_id or "", "stop_hook_active": rounds > 0, "last_assistant_message": last_text[:MAX_OUTPUT_CHARS]},
        cwd = workdir,
    )
    if not outcome.blocked:
        return None
    return "A plugin hook asks you to keep working before you finish:\n" + outcome.reason


def workdir_for(session_id: Optional[str]) -> str:
    try:
        from core.inference.tools import _get_workdir

        return _get_workdir(session_id)
    except Exception:
        return str(Path.cwd())
