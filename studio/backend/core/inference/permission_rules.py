"""Ganjalf: remembered permission rules per project, as Claude Code's allow rules.

From an approval card the user can say "always allow `npm run build` in this project" or
"accept file edits in this project". The rule is stored per account and per project folder
(the chat's working directory) and checked by the server before it asks, so it holds across
chats and devices and cannot be widened by the model.

A terminal rule is a command prefix matched on whole words. A command made of several
commands (`a && b`, `a | b`, `a; b`) is allowed only when every part matches a rule, and a
command that builds another command (`$(...)`, backticks, `eval`, `sh -c`) never matches.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import tempfile
import threading
from pathlib import Path
from typing import Any, Optional

from utils.paths import ensure_dir, workspace_root

RULES_FILE = "permission_rules.json"
MAX_RULES_PER_PROJECT = 100
MAX_PREFIX_CHARS = 200
# Tools a rule can allow outright (no arguments to match).
TOOL_RULES = frozenset({"edit_file"})
_lock = threading.Lock()
_SPLIT_RE = re.compile(r"&&|\|\||;|\||\n")
_NEVER_RE = re.compile(
    r"\$\(|`|<\(|>\(|\beval\b|\b(?:ba|z|da|k)?sh\s+-c\b|\bexec\b|\bsource\b|^\s*\.\s"
)
# Prefix words that only name a tool runner: a one-word rule on them would allow everything.
_RUNNERS = frozenset(
    {
        "npm",
        "npx",
        "pnpm",
        "yarn",
        "bun",
        "node",
        "python",
        "python3",
        "pip",
        "pip3",
        "uv",
        "git",
        "cargo",
        "go",
        "make",
        "docker",
        "sudo",
        "env",
        "bash",
        "sh",
        "deno",
        "dotnet",
    }
)


def _store() -> Path:
    return workspace_root() / ".ganjalf" / RULES_FILE


def _load() -> dict[str, Any]:
    try:
        data = json.loads(_store().read_text(encoding = "utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(data: dict[str, Any]) -> None:
    path = _store()
    ensure_dir(path.parent)
    fd, tmp = tempfile.mkstemp(dir = path.parent, prefix = ".rules.", suffix = ".tmp")
    try:
        with os.fdopen(fd, "w", encoding = "utf-8") as handle:
            json.dump(data, handle, indent = 1, sort_keys = True)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def project_key(session_id: Optional[str]) -> str:
    """The project a rule belongs to: the real path of the chat's working directory."""
    from core.inference.tools import _get_workdir
    return os.path.realpath(_get_workdir(session_id))


def _words(text: str) -> list[str]:
    try:
        return shlex.split(text, posix = True)
    except ValueError:
        return text.split()


def normalize_prefix(prefix: str) -> str:
    prefix = " ".join(_words(str(prefix or "").strip()))
    if prefix.endswith(":*"):
        prefix = prefix[:-2].rstrip()
    return prefix[:MAX_PREFIX_CHARS]


def suggested_prefix(command: str) -> str:
    """What the card offers: the command up to its first argument that looks like data."""
    parts = [p for p in _SPLIT_RE.split(command or "") if p.strip()]
    if len(parts) != 1 or _NEVER_RE.search(command or ""):
        return ""
    words = _words(parts[0])
    while words and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=\S*", words[0]):
        words = words[1:]  # FOO=1 npm test -> npm test
    if words and words[0] == "cd":
        return ""
    taken: list[str] = []
    for word in words:
        if word == "-m" and taken and taken[-1].startswith("python"):
            taken.append(word)  # python -m pytest
            continue
        if word.startswith(("-", "~")) or "/" in word or "=" in word or ("." in word and taken):
            break
        taken.append(word)
        if len([w for w in taken if w != "-m"]) == 3:
            break
    if not taken or (len(taken) == 1 and taken[0] in _RUNNERS):
        return ""
    return " ".join(taken)


def _segment_allowed(segment: str, prefixes: list[str]) -> bool:
    words = _words(segment.strip())
    while words and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=\S*", words[0]):
        words = words[1:]
    if not words:
        return True
    if words[0] == "cd" and len(words) <= 2:
        return True  # moving inside the project is how commands are written
    # Output plumbing after the command does not change what runs.
    text = " ".join(words)
    for prefix in prefixes:
        if text == prefix or text.startswith(prefix + " "):
            return True
    return False


_PLUMBING_RE = re.compile(
    r"^\s*(?:head|tail|grep|wc|sort|uniq|cat|tee\s+-a?\s*\S+|tr|cut)\b[^;&|]*$"
)


def command_allowed(command: str, prefixes: list[str]) -> bool:
    if not command or not prefixes or _NEVER_RE.search(command):
        return False
    parts = [p for p in _SPLIT_RE.split(command) if p.strip()]
    if not parts:
        return False
    # `2>&1` and `>&2` are redirections, not separators the regex should have split on.
    if "&" in re.sub(r"\d?>&\d|&>|&&", "", command):
        return False
    first, rest = parts[0], parts[1:]
    if not _segment_allowed(first, prefixes):
        return False
    return all(_segment_allowed(p, prefixes) or _PLUMBING_RE.match(p) for p in rest)


def rules_for(project: str) -> dict[str, Any]:
    entry = _load().get(project) or {}
    commands = [str(p) for p in entry.get("commands") or () if str(p).strip()]
    tools = [str(t) for t in entry.get("tools") or () if str(t) in TOOL_RULES]
    return {"commands": commands, "tools": tools}


def all_rules() -> dict[str, dict[str, Any]]:
    """Every project's rules for this account, for the rules menu."""
    return {project: rules_for(project) for project in sorted(_load())}


def allows(session_id: Optional[str], name: str, arguments: Any) -> bool:
    """Whether a stored rule lets this call run without asking."""
    if name not in ("terminal", "edit_file"):
        return False
    try:
        rules = rules_for(project_key(session_id))
    except Exception:  # noqa: BLE001 -- a rule store problem means "ask", never "allow"
        return False
    if name in rules["tools"]:
        return True
    if name == "terminal" and isinstance(arguments, dict):
        return command_allowed(str(arguments.get("command") or ""), rules["commands"])
    return False


def add_rule(
    project: str,
    *,
    command_prefix: str = "",
    tool: str = "",
) -> dict[str, Any]:
    prefix = normalize_prefix(command_prefix) if command_prefix else ""
    if prefix:
        words = prefix.split()
        if (
            _NEVER_RE.search(prefix)
            or _SPLIT_RE.search(prefix)
            or (len(words) == 1 and words[0] in _RUNNERS)
        ):
            raise ValueError(
                "That rule would allow too much: name the command, e.g. 'npm run build'."
            )
    if tool and tool not in TOOL_RULES:
        raise ValueError(f"Rules can allow only: {', '.join(sorted(TOOL_RULES))}.")
    if not prefix and not tool:
        raise ValueError("Give a command or a tool.")
    with _lock:
        data = _load()
        entry = data.get(project) or {}
        commands = [c for c in entry.get("commands") or () if c != prefix]
        tools = [t for t in entry.get("tools") or () if t != tool]
        if prefix:
            commands.append(prefix)
        if tool:
            tools.append(tool)
        if len(commands) + len(tools) > MAX_RULES_PER_PROJECT:
            raise ValueError(f"At most {MAX_RULES_PER_PROJECT} rules per project.")
        data[project] = {"commands": commands, "tools": tools}
        _save(data)
    return rules_for(project)


def remove_rule(
    project: str,
    *,
    command_prefix: str = "",
    tool: str = "",
) -> dict[str, Any]:
    with _lock:
        data = _load()
        entry = data.get(project) or {}
        entry = {
            "commands": [
                c for c in entry.get("commands") or () if c != normalize_prefix(command_prefix)
            ],
            "tools": [t for t in entry.get("tools") or () if t != tool],
        }
        if entry["commands"] or entry["tools"]:
            data[project] = entry
        else:
            data.pop(project, None)
        _save(data)
    return rules_for(project)
