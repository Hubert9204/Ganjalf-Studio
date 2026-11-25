# SPDX-License-Identifier: AGPL-3.0-only
# Copyright 2026-present the Unsloth AI Inc. team. All rights reserved. See /studio/LICENSE.AGPL-3.0

"""run_agent: hand a task to one of a plugin's agents, which works in a conversation of its own.

The agent's Markdown body is its system prompt and its ``tools`` line (Claude Code names) picks
Studio tools: Bash, Read, Grep, Glob and LS become ``terminal`` (and ``python``), Edit, Write and
MultiEdit become ``edit_file``, WebSearch and WebFetch ``web_search``. It runs on the GGUF model
already loaded, talking to its llama-server directly, in the chat's working folder and sandbox.
Only its final reply comes back, so a long search or review does not fill the caller's context.

Its tool calls run without asking again: approving run_agent approves the agent's work.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)

RUN_AGENT = "run_agent"
MAX_ROUNDS = 25
MAX_SECONDS = 20 * 60
MAX_TOKENS_PER_TURN = 4096
MAX_TOOL_RESULT_CHARS = 6_000
MAX_REPORT_CHARS = 12_000
# Ganjalf: the sub-agent's own conversation is kept under a budget of its own (characters, ~3 per
# token), so 25 rounds of tool output cannot overflow the model's window. Older tool results are
# shortened to a stub first; the system prompt, the task and the last results always stay.
DEFAULT_CONTEXT_CHARS = 64_000
MIN_CONTEXT_CHARS = 16_000
MAX_CONTEXT_CHARS = 400_000
KEEP_RECENT_RESULTS = 2
MAX_LISTED_AGENTS = 30

_TOOL_MAP = {
    "bash": ("terminal", "python"),
    "read": ("read_file",),
    "grep": ("grep",),
    "glob": ("glob",),
    "ls": ("glob",),
    "edit": ("edit_file",),
    "write": ("edit_file",),
    "multiedit": ("edit_file",),
    "notebookedit": ("edit_file",),
    "websearch": ("web_search",),
    "webfetch": ("web_search",),
}
_DEFAULT_TOOLS = ("terminal", "python", "edit_file", "read_file", "grep", "glob", "web_search")

# Ganjalf: agents every chat with code tools has, like Claude Code's Explore and general-purpose.
BUILT_IN_AGENTS = (
    {
        "id": "explore",
        "name": "explore",
        "builtin": True,
        "read_only": True,
        "description": (
            "Read-only. Finds files, definitions and facts in the project and reports them with paths "
            "and line numbers. Use it to survey a large codebase or answer 'where is X / how does Y "
            "work' without filling your own context."
        ),
        "tools": ["Read", "Grep", "Glob"],
        "body": (
            "You explore a codebase to answer a question. Use glob to see the layout, grep to find "
            "where things are defined and used, and read_file to read only the parts that matter. "
            "Never guess: every claim in your report points to a file and line you read. You cannot "
            "change files."
        ),
    },
    {
        "id": "general-purpose",
        "name": "general-purpose",
        "builtin": True,
        "description": (
            "Does a self-contained multi-step job with the full code tools (read, search, run "
            "commands, edit files, web search) and reports back. Use it for a separate piece of "
            "work, such as researching an error, writing a module with its test, or checking a fix."
        ),
        "tools": None,
        "body": (
            "You complete one self-contained task. Plan briefly, work step by step with your tools, "
            "check what you change by running it, and keep the changes to what the task asks."
        ),
    },
)


def available_agents() -> list[dict]:
    """The built-in agents, then the agents of enabled plugins as ``plugin:agent``."""
    from .inspect import PluginError, inspect_plugin
    from .manager import enabled_records, plugin_dir

    agents = [dict(agent) for agent in BUILT_IN_AGENTS]
    for record in enabled_records():
        if not record.get("agents"):
            continue
        try:
            summary = inspect_plugin(plugin_dir(record["name"]))
        except (PluginError, OSError):
            continue
        for agent in summary.get("agents", []):
            agents.append(
                {**agent, "plugin": record["name"], "id": f"{record['name']}:{agent['name']}"}
            )
    return agents


def tool_definition(agents: Optional[list[dict]] = None) -> Optional[dict]:
    agents = available_agents() if agents is None else agents
    if not agents:
        return None
    listing = "\n".join(
        f"- {agent['id']}: {agent.get('description') or 'no description'}"[:300]
        for agent in agents[:MAX_LISTED_AGENTS]
    )
    return {
        "type": "function",
        "function": {
            "name": RUN_AGENT,
            "description": (
                "Hand a self-contained task to a sub-agent. It works on its own with its own tools "
                "in this chat's working folder and returns only its final report, so use it for "
                "searches, reviews or separate pieces of work that would otherwise fill your "
                "context. Give it everything it needs in `task`: it cannot see this conversation. "
                "Agents:\n" + listing
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "agent": {
                        "type": "string",
                        "description": "The agent's id, e.g. plugin:agent.",
                    },
                    "task": {
                        "type": "string",
                        "description": "The complete task, with paths, goals and constraints.",
                    },
                },
                "required": ["agent", "task"],
            },
        },
    }


def _agent_tools(agent: dict, offered: list[dict]) -> list[dict]:
    wanted: list[str] = []
    names = agent.get("tools")
    if names:
        for name in names:
            for mapped in _TOOL_MAP.get(str(name).strip().lower(), ()):
                if mapped not in wanted:
                    wanted.append(mapped)
    else:
        wanted = list(_DEFAULT_TOOLS)
    by_name = {tool["function"]["name"]: tool for tool in offered}
    return [by_name[name] for name in wanted if name in by_name]


def _system_prompt(agent: dict, body: str, workdir: str, tools: list[dict]) -> str:
    names = ", ".join(tool["function"]["name"] for tool in tools) or "none"
    return (
        f"{body.strip()}\n\n---\n\n"
        f"You are the `{agent['id']}` agent, called by another assistant to do one task. "
        f"Your working folder is {workdir}. Your tools: {names}. Work step by step with the tools "
        "and check results instead of guessing. You cannot ask questions: decide, and note "
        "assumptions. When you are done, reply with the report the caller needs (findings, file "
        "paths and line numbers, what you changed, what is unverified). That reply is all it sees."
    )


class _Stopped(Exception):
    pass


def _post(
    base_url: str,
    headers: Optional[dict],
    payload: dict,
    timeout: float,
    cancel_event = None,
) -> dict:
    """One model turn, streamed so a stop closes the connection (llama-server then ends the
    generation) instead of waiting for the whole reply. Returns {"content", "tool_calls"}."""
    import httpx

    content: list[str] = []
    calls: dict[int, dict] = {}
    started = time.monotonic()
    with httpx.Client(
        timeout = httpx.Timeout(timeout, read = 60.0), headers = headers, trust_env = False
    ) as client:
        with client.stream(
            "POST", f"{base_url}/v1/chat/completions", json = {**payload, "stream": True}
        ) as response:
            if response.status_code >= 400:
                response.read()
                raise RuntimeError(
                    f"the model server answered {response.status_code}: {response.text[:300]}"
                )
            for line in response.iter_lines():
                if cancel_event is not None and cancel_event.is_set():
                    raise _Stopped()
                if time.monotonic() - started > timeout:
                    raise RuntimeError(f"no reply within {timeout:g} s")
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                for choice in chunk.get("choices") or []:
                    delta = choice.get("delta") or {}
                    if isinstance(delta.get("content"), str):
                        content.append(delta["content"])
                    for call in delta.get("tool_calls") or []:
                        slot = calls.setdefault(
                            int(call.get("index") or 0), {"id": "", "name": "", "arguments": ""}
                        )
                        slot["id"] = call.get("id") or slot["id"]
                        function = call.get("function") or {}
                        slot["name"] += function.get("name") or ""
                        slot["arguments"] += function.get("arguments") or ""
    return {
        "content": "".join(content),
        "tool_calls": [
            {
                "id": slot["id"],
                "type": "function",
                "function": {"name": slot["name"], "arguments": slot["arguments"]},
            }
            for _, slot in sorted(calls.items())
        ],
    }


def context_budget_chars(context_tokens: Optional[int] = None) -> int:
    """GANJALF_AGENT_CONTEXT_CHARS, else ~3/4 of the model's window (in chars) minus one reply."""
    import os

    raw = (os.environ.get("GANJALF_AGENT_CONTEXT_CHARS") or "").strip()
    if raw:
        try:
            return max(MIN_CONTEXT_CHARS, int(raw))
        except ValueError:
            pass
    if isinstance(context_tokens, int) and context_tokens > 0:
        budget = (context_tokens - MAX_TOKENS_PER_TURN) * 3 * 3 // 4
        return max(MIN_CONTEXT_CHARS, min(MAX_CONTEXT_CHARS, budget))
    return DEFAULT_CONTEXT_CHARS


def _message_chars(message: dict) -> int:
    size = len(str(message.get("content") or ""))
    if message.get("tool_calls"):
        size += len(json.dumps(message["tool_calls"], ensure_ascii = False))
    return size


def trim_history(messages: list[dict], budget: int) -> int:
    """Shorten the oldest tool results until the conversation fits ``budget``; returns how many."""
    total = sum(_message_chars(message) for message in messages)
    if total <= budget:
        return 0
    results = [index for index, message in enumerate(messages) if message.get("role") == "tool"]
    trimmed = 0
    for index in results[: max(0, len(results) - KEEP_RECENT_RESULTS)]:
        old = str(messages[index].get("content") or "")
        if old.startswith("[older result shortened"):
            continue
        stub = f"[older result shortened to save context; it was {len(old)} chars: {old[:200]}]"
        if len(stub) >= len(old):
            continue
        messages[index] = {**messages[index], "content": stub}
        total -= len(old) - len(stub)
        trimmed += 1
        if total <= budget:
            break
    return trimmed


def _clip_result(text: str) -> str:
    """Head and tail: a build or test log ends with what matters."""
    if len(text) <= MAX_TOOL_RESULT_CHARS:
        return text
    tail = MAX_TOOL_RESULT_CHARS // 3
    head = MAX_TOOL_RESULT_CHARS - tail
    return f"{text[:head]}\n... ({len(text) - head - tail} chars cut) ...\n{text[-tail:]}"


def _strip_images(result: str) -> str:
    from core.inference.mcp_images import SENTINEL
    if isinstance(result, str) and SENTINEL in result:
        return result.split(SENTINEL, 1)[0].rstrip() + "\n(image omitted)"
    return result if isinstance(result, str) else json.dumps(result)[:MAX_TOOL_RESULT_CHARS]


def run_agent(
    arguments: Any,
    *,
    session_id: Optional[str],
    cancel_event = None,
    disable_sandbox: bool = False,
    website_policy: Optional[dict] = None,
    server: Optional[tuple[str, Optional[dict]]] = None,
) -> str:
    """`server`: (base_url, headers) of the model server; the loaded llama.cpp model when None."""
    from .inspect import PluginError, read_markdown
    from .manager import plugin_dir

    if not isinstance(arguments, dict):
        return 'Error: run_agent takes {"agent": ..., "task": ...}.'
    wanted = str(arguments.get("agent") or "").strip()
    task = str(arguments.get("task") or "").strip()
    if not wanted or not task:
        return "Error: give both 'agent' (an id from the list) and 'task'."
    agents = available_agents()
    agent = next(
        (
            item
            for item in agents
            if wanted in (item["id"], item["name"], item["id"].replace(":", "-"))
        ),
        None,
    )
    if agent is None:
        known = ", ".join(item["id"] for item in agents[:MAX_LISTED_AGENTS]) or "none"
        return f"Error: no agent {wanted!r}. Agents: {known}."
    if agent.get("builtin"):
        body = agent["body"]
    else:
        try:
            _frontmatter, body = read_markdown(plugin_dir(agent["plugin"]) / agent["path"])
        except (PluginError, OSError) as exc:
            return f"Error: the agent's file could not be read: {exc}"
        from .manager import expand
        body = expand(body, agent["plugin"]) if "${" in body else body

    if server is None:
        try:
            from routes.inference import get_llama_cpp_backend

            backend = get_llama_cpp_backend()
            if not backend.is_loaded:
                return "Error: run_agent needs a GGUF model loaded in llama.cpp; none is loaded."
            server = (backend.base_url, backend._auth_headers)
            context_tokens = getattr(backend, "context_length", None)
        except Exception as exc:
            return f"Error: run_agent needs a GGUF model running in llama.cpp ({exc})."
    else:
        context_tokens = None
    base_url, headers = server
    budget = context_budget_chars(context_tokens)

    from core.inference.agent_tools import GLOB_TOOL, GREP_TOOL, READ_FILE_TOOL
    from core.inference.llama_tool_schema import llama_grammar_tools
    from core.inference.tools import ALL_TOOLS, _get_workdir, execute_tool

    workdir = _get_workdir(session_id)
    pool = [tool for tool in ALL_TOOLS if tool["function"]["name"] != RUN_AGENT]
    pool += [READ_FILE_TOOL, GREP_TOOL, GLOB_TOOL]
    tools = _agent_tools(agent, pool)
    messages: list[dict] = [
        {"role": "system", "content": _system_prompt(agent, body, workdir, tools)},
        {"role": "user", "content": task},
    ]
    started = time.monotonic()
    steps: list[str] = []
    for round_number in range(MAX_ROUNDS):
        if cancel_event is not None and cancel_event.is_set():
            return "Error: run_agent was cancelled."
        if time.monotonic() - started > MAX_SECONDS:
            return _report(
                agent, steps, "", f"stopped after {MAX_SECONDS // 60} minutes without finishing"
            )
        trim_history(messages, budget)
        payload: dict = {
            "model": "ganjalf",
            "messages": messages,
            "max_tokens": MAX_TOKENS_PER_TURN,
            "temperature": 0.6,
            "top_p": 0.95,
            "top_k": 20,
        }
        if tools:
            payload["tools"] = llama_grammar_tools(tools)
            payload["tool_choice"] = "auto"
        try:
            reply = _post(base_url, headers, payload, timeout = 600, cancel_event = cancel_event)
        except _Stopped:
            return "Error: run_agent was cancelled."
        except Exception as exc:
            return _report(agent, steps, "", f"the model call failed: {exc}")
        calls = [call for call in reply["tool_calls"] if call["function"]["name"]]
        content = reply["content"]
        if not calls:
            return _report(agent, steps, content, None)
        messages.append({"role": "assistant", "content": content, "tool_calls": calls})
        for index, call in enumerate(calls):
            function = call.get("function") or {}
            name = str(function.get("name") or "")
            raw = function.get("arguments")
            try:
                call_args = json.loads(raw) if isinstance(raw, str) else (raw or {})
            except json.JSONDecodeError:
                call_args = None
            allowed = {tool["function"]["name"] for tool in tools}
            if name not in allowed:
                result = f"Error: {name or 'that tool'} is not one of your tools ({', '.join(sorted(allowed))})."
            elif not isinstance(call_args, dict):
                result = "Error: the arguments were not valid JSON; call again with a JSON object."
            else:
                result = execute_tool(
                    name,
                    call_args,
                    cancel_event = cancel_event,
                    session_id = session_id,
                    disable_sandbox = disable_sandbox,
                    website_policy = website_policy,
                )
            steps.append(name)
            if cancel_event is not None and cancel_event.is_set():
                return "Error: run_agent was cancelled."
            text = _clip_result(_strip_images(result))
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": str(call.get("id") or f"call_{round_number}_{index}"),
                    "content": text,
                }
            )
    return _report(agent, steps, "", f"stopped after {MAX_ROUNDS} rounds without a final report")


def _report(agent: dict, steps: list[str], text: str, problem: Optional[str]) -> str:
    used = f"{len(steps)} tool call{'s' if len(steps) != 1 else ''}"
    head = (
        f"Agent {agent['id']} finished ({used})."
        if not problem
        else f"Agent {agent['id']} {problem} ({used})."
    )
    text = (text or "").strip()
    if len(text) > MAX_REPORT_CHARS:
        text = text[:MAX_REPORT_CHARS] + "\n... (cut)"
    if not text:
        return head + (
            " It gave no report; do the task yourself or ask it again more narrowly."
            if not problem
            else ""
        )
    return f"{head}\n\nIts report:\n{text}"
