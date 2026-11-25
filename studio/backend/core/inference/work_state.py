"""Ganjalf: the state of the work, kept when a long agent run is compacted.

When older turns leave the context (rolling window or a checkpoint reset), the model loses
what it did: which files it wrote, its task list, the checks it ran, the servers it left
running. A Nemotron run spent 13 tool calls after a compaction just finding its place again.

This block is rebuilt from the full message list on every fit, like the checkpoint's record
of standing instructions: nothing is stored, nothing is summarised by a model that could
fail. It is appended to the system message only when the fit actually dropped turns.
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional

MAX_BLOCK_CHARS = 2400
MAX_FILES = 30
MAX_CHECKS = 5
HEADER = (
    "[Work so far, kept when older turns were compacted. It is a record of what you already "
    "did in this task: continue from it instead of exploring again, and read a file only when "
    "you need its current contents.]"
)
_CHECK_RE = re.compile(
    r"\b(?:tsc|vite\s+build|npm\s+(?:run\s+)?(?:build|test|lint|check)|pnpm\s+\S+|yarn\s+\S+|"
    r"pytest|python\s+-m\s+(?:pytest|unittest)|cargo\s+(?:build|test|check)|go\s+(?:build|test)|"
    r"make\b|eslint|ruff|mypy|node\s+--test)\b",
    re.IGNORECASE,
)
_ERROR_RE = re.compile(
    r"\berror\b|\bfailed\b|\bTraceback\b|\bnot ok\b|exit code [1-9]", re.IGNORECASE
)
_STARTED_RE = re.compile(r"Started background job (bg\d+): (.+)")
_STOPPED_RE = re.compile(r"\b(?:Stopped|stopped)\b[^\n]*?\b(bg\d+)\b")
_ENDED_RE = re.compile(r"Background job (bg\d+) already ended")
_URL_RE = re.compile(r"https?://(?:localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\]):\d+[^\s'\"<>)]*")


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(part.get("text") or "") for part in content if isinstance(part, dict))
    return "" if content is None else str(content)


def _arguments(call: dict) -> dict:
    raw = (call.get("function") or {}).get("arguments")
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            value = json.loads(raw)
        except ValueError:
            return {}
        return value if isinstance(value, dict) else {}
    return {}


def _calls_and_results(messages: list[dict]) -> list[tuple[str, dict, str]]:
    """(tool name, arguments, result text) in order; a call without a result gets ""."""
    results: dict[str, str] = {}
    for message in messages:
        if isinstance(message, dict) and message.get("role") == "tool":
            results[str(message.get("tool_call_id") or "")] = _text(message.get("content"))
    out: list[tuple[str, dict, str]] = []
    for message in messages:
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        for call in message.get("tool_calls") or ():
            if not isinstance(call, dict):
                continue
            name = str((call.get("function") or {}).get("name") or "")
            if name:
                out.append((name, _arguments(call), results.get(str(call.get("id") or ""), "")))
    return out


def _short(text: str, limit: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def work_state_block(messages: list[dict]) -> str:
    """The record, or "" when the conversation holds no tool work worth keeping."""
    calls = _calls_and_results(messages or [])
    if not calls:
        return ""
    todos: Optional[list] = None
    files: dict[str, str] = {}
    checks: list[str] = []
    jobs: dict[str, str] = {}
    addresses: dict[str, str] = {}
    for name, args, result in calls:
        if name == "todo_write":
            items = args.get("todos")
            if isinstance(items, str):
                try:
                    items = json.loads(items)
                except ValueError:
                    items = None
            if isinstance(items, list) and items and not result.startswith("Error"):
                todos = items
        elif name == "edit_file":
            path = str(args.get("path") or "").strip()
            if path and not result.startswith("Error"):
                edits = args.get("edits") if isinstance(args.get("edits"), list) else []
                created = any(
                    isinstance(e, dict) and not str(e.get("old_string") or "") for e in edits
                )
                # A file created earlier stays "created"; a later edit only moves it to the end.
                how = files.pop(path, "created" if created else "edited")
                files[path] = how
        elif name == "terminal":
            command = str(args.get("command") or "")
            for match in _STARTED_RE.finditer(result):
                jobs[match.group(1)] = match.group(2).strip()
                url = _URL_RE.search(result)
                if url:
                    addresses[match.group(1)] = url.group(0).replace("0.0.0.0", "localhost")
            if _CHECK_RE.search(command) and not args.get("run_in_background"):
                verdict = "errors in output" if _ERROR_RE.search(result[:6000]) else "no errors"
                checks.append(f"`{_short(command, 90)}` → {verdict}")
        elif name == "check_page":
            target = str(args.get("path") or args.get("url") or "")
            verdict = (
                "page errors"
                if re.search(
                    r"(?im)^\s*(?:javascript errors|page errors|errors)\s*:\s*[1-9]|uncaught|TypeError|ReferenceError",
                    result,
                )
                else "loaded"
            )
            checks.append(f"check_page {_short(target, 60)} → {verdict}")
        elif name == "terminal_output":
            job = str(args.get("id") or "")
            url = _URL_RE.search(result)
            if job and url:
                addresses[job] = url.group(0).replace("0.0.0.0", "localhost")
            if job and re.search(r"Status: (?:ended|exited|stopped)", result):
                jobs.pop(job, None)
        if name in ("terminal_kill", "terminal_output", "terminal"):
            for pattern in (_STOPPED_RE, _ENDED_RE):
                for match in pattern.finditer(result):
                    jobs.pop(match.group(1), None)
    lines: list[str] = []
    if todos:
        marks = {"completed": "x", "in_progress": "~"}
        lines.append("Task list:")
        for item in todos[:20]:
            if isinstance(item, dict):
                mark = marks.get(str(item.get("status") or ""), " ")
                lines.append(f"- [{mark}] {_short(item.get('content') or '', 120)}")
    if files:
        shown = list(files.items())[-MAX_FILES:]
        lines.append("Files you wrote: " + ", ".join(f"{path} ({how})" for path, how in shown))
    if checks:
        lines.append("Latest checks:")
        lines.extend(f"- {check}" for check in checks[-MAX_CHECKS:])
    if jobs:
        lines.append("Still running in the background:")
        for job, command in jobs.items():
            where = f" at {addresses[job]}" if job in addresses else ""
            lines.append(f"- {job}: {_short(command, 90)}{where}")
    if not lines:
        return ""
    block = HEADER + "\n" + "\n".join(lines)
    if len(block) > MAX_BLOCK_CHARS:
        block = block[: MAX_BLOCK_CHARS - 1] + "…"
    return block


def with_work_state(messages: list[dict], block: str) -> list[dict]:
    """``messages`` with ``block`` appended to the system message (one is added if absent)."""
    if not block:
        return messages
    out = list(messages)
    for index, message in enumerate(out):
        if isinstance(message, dict) and message.get("role") == "system":
            content = message.get("content")
            if isinstance(content, list):
                new_content: Any = [*content, {"type": "text", "text": "\n\n" + block}]
            else:
                new_content = (_text(content).rstrip() + "\n\n" + block).lstrip()
            out[index] = {**message, "content": new_content}
            return out
    return [{"role": "system", "content": block}, *out]
