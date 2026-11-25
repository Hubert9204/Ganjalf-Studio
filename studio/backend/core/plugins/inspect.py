# SPDX-License-Identifier: AGPL-3.0-only
# Copyright 2026-present the Unsloth AI Inc. team. All rights reserved. See /studio/LICENSE.AGPL-3.0

"""Reading a plugin folder or a marketplace in Claude Code's plugin format.

A plugin: optional `.claude-plugin/plugin.json`, then `skills/<name>/SKILL.md`, `commands/*.md`,
`agents/*.md`, `hooks/hooks.json` and `.mcp.json` (or the paths the manifest names). Every path
must stay inside the plugin folder. What Ganjalf can't use (LSP servers, `bin/`, monitors, themes,
output styles, workflows, settings, user config) is listed, not loaded.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Optional

MANIFEST = ".claude-plugin/plugin.json"
MARKETPLACE = ".claude-plugin/marketplace.json"
MAX_JSON_BYTES = 1024 * 1024
MAX_MARKDOWN_BYTES = 512 * 1024
MAX_COMPONENTS = 500

HOOK_EVENTS = (
    "PreToolUse",
    "PostToolUse",
    "UserPromptSubmit",
    "Stop",
    "SessionStart",
    "SessionEnd",
    "Notification",
    "SubagentStop",
    "PreCompact",
)

# bin/, output-styles/ and monitors are supported (see below); these two have no Ganjalf meaning:
# workflows run on Claude Code's own JavaScript runtime, themes colour its terminal.
_UNSUPPORTED_DIRS = {
    "themes": "themes (Claude Code's terminal colours)",
    "workflows": "workflows (Claude Code's JavaScript runtime)",
}
MAX_MONITORS = 10


class PluginError(ValueError):
    pass


def _inside(root: Path, path: Path) -> Optional[Path]:
    try:
        resolved = path.resolve()
        root_resolved = root.resolve()
    except OSError:
        return None
    if resolved != root_resolved and root_resolved not in resolved.parents:
        return None
    return resolved


def _rel(root: Path, value: Any) -> Optional[Path]:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("${CLAUDE_PLUGIN_ROOT}", ".")
    if text.startswith("/"):
        return None
    return _inside(root, root / text)


def read_json(path: Path) -> Any:
    if path.stat().st_size > MAX_JSON_BYTES:
        raise PluginError(f"{path.name} is larger than 1 MB.")
    try:
        return json.loads(path.read_text(encoding = "utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PluginError(f"{path.name} is not valid JSON: {exc}") from exc


def read_markdown(path: Path) -> tuple[dict, str]:
    """(frontmatter, body). A file without frontmatter is all body."""
    from core.inference.skills import SkillError, _split_skill_markdown

    raw = path.read_bytes()[: MAX_MARKDOWN_BYTES + 1]
    if len(raw) > MAX_MARKDOWN_BYTES:
        raise PluginError(f"{path.name} is larger than 512 KB.")
    text = raw.decode("utf-8-sig", errors = "replace")
    if not text.lstrip().startswith("---"):
        return {}, text
    try:
        frontmatter, body = _split_skill_markdown(text.lstrip().encode("utf-8"))
    except SkillError as exc:
        raise PluginError(f"{path.name}: {exc}") from exc
    return (frontmatter if isinstance(frontmatter, dict) else {}), body


def _paths(value: Any) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def slug(text: str) -> str:
    """A Ganjalf skill-name piece: lowercase letters, digits and single hyphens."""
    value = re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")
    return re.sub(r"-{2,}", "-", value)


def _description(frontmatter: dict, body: str) -> str:
    value = frontmatter.get("description")
    if isinstance(value, str) and value.strip():
        return " ".join(value.split())[:1000]
    for line in body.splitlines():
        line = line.strip().lstrip("#").strip()
        if line:
            return line[:1000]
    return ""


def _skills(root: Path, manifest: dict, warnings: list[str]) -> list[dict]:
    folders: list[Path] = []
    default = root / "skills"
    if default.is_dir():
        folders.append(default)
    for value in _paths(manifest.get("skills")):
        path = "." if value == "." else value
        resolved = _rel(root, path)
        if resolved is None or not resolved.is_dir():
            warnings.append(f"skills path {value!r} is missing or outside the plugin")
            continue
        folders.append(resolved)
    if not folders and "skills" not in manifest and (root / "SKILL.md").is_file():
        folders.append(root)
    found: dict[str, dict] = {}
    for folder in folders:
        candidates = (
            [folder]
            if (folder / "SKILL.md").is_file()
            else sorted(p for p in folder.iterdir() if p.is_dir())
        )
        for skill_dir in candidates:
            manifest_path = skill_dir / "SKILL.md"
            if not manifest_path.is_file() or _inside(root, manifest_path) is None:
                continue
            try:
                frontmatter, body = read_markdown(manifest_path)
            except PluginError as exc:
                warnings.append(str(exc))
                continue
            name = str(frontmatter.get("name") or skill_dir.name)
            if name in found or len(found) >= MAX_COMPONENTS:
                continue
            found[name] = {
                "name": name,
                "path": skill_dir.relative_to(root).as_posix() or ".",
                "description": _description(frontmatter, body),
            }
    return list(found.values())


def _markdown_files(root: Path, folder: Path) -> list[Path]:
    files = []
    for current, dirs, names in os.walk(folder, followlinks = False):
        dirs.sort()
        for name in sorted(names):
            if name.lower().endswith(".md"):
                path = Path(current) / name
                if _inside(root, path) is not None and not path.is_symlink():
                    files.append(path)
    return files[:MAX_COMPONENTS]


def _commands(root: Path, manifest: dict, warnings: list[str]) -> list[dict]:
    entries: list[tuple[str, Optional[Path], Optional[str]]] = []
    spec = manifest.get("commands")
    if isinstance(spec, dict):
        for name, item in spec.items():
            if isinstance(item, dict) and isinstance(item.get("content"), str):
                entries.append((str(name), None, item["content"]))
            elif isinstance(item, dict) and _rel(root, item.get("source")):
                entries.append((str(name), _rel(root, item.get("source")), None))
            else:
                warnings.append(f"command {name!r} has no readable source")
    else:
        sources = (
            _paths(spec)
            if spec is not None
            else (["./commands"] if (root / "commands").is_dir() else [])
        )
        for value in sources:
            resolved = _rel(root, value)
            if resolved is None or not resolved.exists():
                warnings.append(f"commands path {value!r} is missing or outside the plugin")
                continue
            files = [resolved] if resolved.is_file() else _markdown_files(root, resolved)
            for path in files:
                base = resolved if resolved.is_dir() else resolved.parent
                name = ":".join(path.relative_to(base).with_suffix("").parts)
                entries.append((name, path, None))
    commands = []
    for name, path, content in entries[:MAX_COMPONENTS]:
        try:
            frontmatter, body = read_markdown(path) if path else ({}, content or "")
        except PluginError as exc:
            warnings.append(str(exc))
            continue
        hint = frontmatter.get("argument-hint")
        if isinstance(hint, list):
            # YAML reads an unquoted `[name]` as a list.
            hint = "[" + " ".join(str(item) for item in hint) + "]"
        commands.append(
            {
                "name": name,
                "path": path.relative_to(root.resolve()).as_posix() if path else None,
                "description": _description(frontmatter, body),
                **({"argument_hint": str(hint)[:200]} if hint else {}),
                **({"content": content} if path is None else {}),
            }
        )
    return commands


def _agents(root: Path, manifest: dict, warnings: list[str]) -> list[dict]:
    spec = manifest.get("agents")
    if spec is not None:
        files = []
        for value in _paths(spec):
            resolved = _rel(root, value)
            if resolved is None or not resolved.is_file():
                warnings.append(f"agent file {value!r} is missing or outside the plugin")
                continue
            files.append((resolved, resolved.stem))
    else:
        folder = root / "agents"
        files = (
            [
                (path, ":".join(path.relative_to(folder).with_suffix("").parts))
                for path in _markdown_files(root, folder)
            ]
            if folder.is_dir()
            else []
        )
    agents = []
    for path, default_name in files[:MAX_COMPONENTS]:
        try:
            frontmatter, body = read_markdown(path)
        except PluginError as exc:
            warnings.append(str(exc))
            continue
        tools = frontmatter.get("tools")
        if isinstance(tools, str):
            tools = [tool.strip() for tool in tools.split(",") if tool.strip()]
        agents.append(
            {
                "name": str(frontmatter.get("name") or default_name),
                "path": path.relative_to(root.resolve()).as_posix(),
                "description": _description(frontmatter, body),
                **(
                    {"tools": [str(tool) for tool in tools][:50]} if isinstance(tools, list) else {}
                ),
                **({"model": str(frontmatter["model"])[:100]} if frontmatter.get("model") else {}),
            }
        )
    return agents


def _merge_hooks(target: dict, config: Any, origin: str, warnings: list[str]) -> None:
    if isinstance(config, dict) and isinstance(config.get("hooks"), dict):
        config = config["hooks"]
    if not isinstance(config, dict):
        warnings.append(f"{origin}: hooks must be an object of events")
        return
    for event, groups in config.items():
        if not isinstance(groups, list):
            warnings.append(f"{origin}: {event} must be a list")
            continue
        for group in groups:
            if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
                continue
            hooks = [
                {
                    "type": "command",
                    "command": hook["command"],
                    **(
                        {"timeout": hook["timeout"]}
                        if isinstance(hook.get("timeout"), (int, float))
                        else {}
                    ),
                    **({"if": hook["if"]} if isinstance(hook.get("if"), str) else {}),
                }
                for hook in group["hooks"]
                if isinstance(hook, dict)
                and hook.get("type", "command") == "command"
                and isinstance(hook.get("command"), str)
                # Background hooks that wake the agent later have no counterpart here.
                and not hook.get("async")
                and not hook.get("asyncRewake")
            ]
            skipped = len(group["hooks"]) - len(hooks)
            if skipped:
                warnings.append(
                    f"{origin}: {skipped} {event} hook(s) are skipped (not commands, or run in the background)"
                )
            if hooks:
                target.setdefault(str(event), []).append(
                    {"matcher": str(group.get("matcher") or ""), "hooks": hooks}
                )


def _hooks(root: Path, manifest: dict, warnings: list[str]) -> dict:
    hooks: dict = {}
    default = root / "hooks" / "hooks.json"
    if default.is_file():
        try:
            _merge_hooks(hooks, read_json(default), "hooks/hooks.json", warnings)
        except PluginError as exc:
            warnings.append(str(exc))
    for value in _paths(manifest.get("hooks")):
        if isinstance(value, dict):
            _merge_hooks(hooks, value, "plugin.json hooks", warnings)
            continue
        resolved = _rel(root, value)
        if resolved is None or not resolved.is_file() or resolved == default.resolve():
            if resolved != default.resolve():
                warnings.append(f"hooks file {value!r} is missing or outside the plugin")
            continue
        try:
            _merge_hooks(hooks, read_json(resolved), str(value), warnings)
        except PluginError as exc:
            warnings.append(str(exc))
    unknown = [event for event in hooks if event not in HOOK_EVENTS]
    if unknown:
        warnings.append("hook events Ganjalf does not run: " + ", ".join(sorted(unknown)))
    return hooks


def _server_map(config: Any) -> dict:
    if isinstance(config, dict) and isinstance(config.get("mcpServers"), dict):
        return config["mcpServers"]
    if isinstance(config, dict) and all(isinstance(value, dict) for value in config.values()):
        return config
    return {}


def _bin(root: Path) -> list[str]:
    """Executables in bin/: on the terminal's PATH while the plugin is on."""
    folder = root / "bin"
    if not folder.is_dir():
        return []
    names = []
    for path in sorted(folder.iterdir())[:MAX_COMPONENTS]:
        try:
            if (
                path.is_file()
                and not path.is_symlink()
                and path.resolve().is_relative_to(root.resolve())
            ):
                names.append(path.name)
        except OSError:
            continue
    return names


def _output_styles(root: Path, manifest: dict, warnings: list[str]) -> list[dict]:
    """Output styles: Markdown that changes how the model writes (Claude Code's /output-style)."""
    spec = manifest.get("outputStyles")
    candidates: list[Path] = []
    for value in _paths(spec) if spec is not None else ["./output-styles"]:
        resolved = _rel(root, value) if isinstance(value, str) else None
        if resolved is None or not resolved.exists():
            if spec is not None:
                warnings.append(f"output style {value!r} is missing or outside the plugin")
            continue
        candidates += _markdown_files(root, resolved) if resolved.is_dir() else [resolved]
    styles = []
    for path in candidates[:MAX_COMPONENTS]:
        try:
            frontmatter, body = read_markdown(path)
        except PluginError as exc:
            warnings.append(str(exc))
            continue
        if not body.strip():
            continue
        styles.append(
            {
                "name": str(frontmatter.get("name") or path.stem)[:64],
                "path": path.relative_to(root.resolve()).as_posix(),
                "description": _description(frontmatter, body),
                "keep_coding_instructions": bool(frontmatter.get("keep-coding-instructions")),
            }
        )
    return styles


def _monitors(root: Path, manifest: dict, warnings: list[str]) -> list[dict]:
    """Monitors: commands that run in the background for the whole chat (or from a skill on)."""
    experimental = (
        manifest.get("experimental") if isinstance(manifest.get("experimental"), dict) else {}
    )
    spec = experimental.get("monitors", manifest.get("monitors"))
    entries: Any = None
    if isinstance(spec, list):
        entries = spec
    else:
        path = _rel(root, spec) if isinstance(spec, str) else root / "monitors" / "monitors.json"
        if path is not None and path.is_file():
            try:
                entries = read_json(path)
            except PluginError as exc:
                warnings.append(str(exc))
        elif spec is not None:
            warnings.append(f"monitors {spec!r} is missing or outside the plugin")
    monitors = []
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict):
            continue
        name, command = (
            str(entry.get("name") or "").strip(),
            str(entry.get("command") or "").strip(),
        )
        if not name or not command:
            warnings.append("a monitor needs a name and a command")
            continue
        if "${user_config." in command:
            warnings.append(f"monitor {name} uses userConfig, which Ganjalf does not have")
            continue
        when = str(entry.get("when") or "always")
        monitors.append(
            {
                "name": name[:64],
                "command": command[:2000],
                "description": str(entry.get("description") or "")[:300],
                "when": when
                if when == "always" or when.startswith("on-skill-invoke:")
                else "always",
            }
        )
    return monitors[:MAX_MONITORS]


def _mcp_servers(root: Path, manifest: dict, warnings: list[str]) -> dict:
    servers: dict = {}
    default = root / ".mcp.json"
    if default.is_file():
        try:
            servers.update(_server_map(read_json(default)))
        except PluginError as exc:
            warnings.append(str(exc))
    for value in _paths(manifest.get("mcpServers")):
        if isinstance(value, dict):
            servers.update(_server_map(value))
            continue
        if isinstance(value, str) and value.lower().endswith((".mcpb", ".dxt")):
            warnings.append(f"MCP bundle {value} is not supported; add that server by hand")
            continue
        resolved = _rel(root, value)
        if resolved is None or not resolved.is_file():
            warnings.append(f"MCP config {value!r} is missing or outside the plugin")
            continue
        try:
            servers.update(_server_map(read_json(resolved)))
        except PluginError as exc:
            warnings.append(str(exc))
    return {str(name): spec for name, spec in list(servers.items())[:50] if isinstance(spec, dict)}


def inspect_plugin(root: Path, entry: Optional[dict] = None) -> dict:
    """Everything the plugin holds, for the confirmation screen and the installer.

    `entry`: its marketplace entry, whose component fields stand in for a missing manifest."""
    root = root.resolve()
    warnings: list[str] = []
    manifest: dict = {}
    manifest_path = root / MANIFEST
    if manifest_path.is_file():
        data = read_json(manifest_path)
        if not isinstance(data, dict):
            raise PluginError("plugin.json must be an object.")
        manifest = data
    elif entry:
        manifest = {key: value for key, value in entry.items() if key != "source"}
    raw_name = manifest.get("name") or (entry or {}).get("name") or root.name
    name = slug(raw_name)
    if not name or len(name) > 48:
        raise PluginError("The plugin needs a name of 1-48 letters, digits or hyphens.")
    author = manifest.get("author")
    unsupported = [label for folder, label in _UNSUPPORTED_DIRS.items() if (root / folder).is_dir()]
    if (root / ".lsp.json").is_file() or manifest.get("lspServers"):
        unsupported.append("LSP servers")
    if manifest.get("userConfig"):
        unsupported.append("user configuration (userConfig)")
    if manifest.get("channels"):
        unsupported.append("channels")
    if (root / "settings.json").is_file() or manifest.get("settings"):
        unsupported.append("settings")
    if (root / "CLAUDE.md").is_file():
        warnings.append("CLAUDE.md at the plugin root is not loaded (Claude Code ignores it too)")
    summary = {
        "name": name,
        "display_name": str(manifest.get("displayName") or raw_name)[:100],
        "version": str(manifest.get("version") or "")[:50],
        "description": " ".join(
            str(manifest.get("description") or (entry or {}).get("description") or "").split()
        )[:1000],
        "author": str(author.get("name") if isinstance(author, dict) else author or "")[:200],
        "homepage": str(manifest.get("homepage") or "")[:500],
        "license": str(manifest.get("license") or "")[:100],
        "skills": _skills(root, manifest, warnings),
        "commands": _commands(root, manifest, warnings),
        "agents": _agents(root, manifest, warnings),
        "hooks": _hooks(root, manifest, warnings),
        "mcp_servers": _mcp_servers(root, manifest, warnings),
        "bin": _bin(root),
        "output_styles": _output_styles(root, manifest, warnings),
        "monitors": _monitors(root, manifest, warnings),
        "unsupported": unsupported,
        "warnings": warnings[:50],
    }
    if not any(
        summary[key]
        for key in (
            "skills",
            "commands",
            "agents",
            "hooks",
            "mcp_servers",
            "bin",
            "output_styles",
            "monitors",
        )
    ):
        raise PluginError(
            "This folder has no skills, commands, agents, hooks or MCP servers Ganjalf can use."
        )
    return summary


def read_marketplace(root: Path) -> Optional[dict]:
    """The marketplace listing at `root`, or None when there is none."""
    path = root / MARKETPLACE
    if not path.is_file():
        return None
    data = read_json(path)
    if not isinstance(data, dict) or not isinstance(data.get("plugins"), list):
        raise PluginError("marketplace.json needs a plugins list.")
    owner = data.get("owner")
    plugin_root = (
        str((data.get("metadata") or {}).get("pluginRoot") or "")
        if isinstance(data.get("metadata"), dict)
        else ""
    )
    plugins = []
    for item in data["plugins"][:MAX_COMPONENTS]:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        source = item.get("source")
        if isinstance(source, str) and plugin_root and not source.startswith(("./", "../", "/")):
            source = f"{plugin_root.rstrip('/')}/{source}"
        plugins.append(
            {
                "name": slug(item["name"]),
                "description": " ".join(str(item.get("description") or "").split())[:500],
                "version": str(item.get("version") or "")[:50],
                "category": str(item.get("category") or "")[:50],
                "source": source,
                "entry": item,
            }
        )
    return {
        "name": slug(data.get("name") or root.name) or "marketplace",
        "owner": str(owner.get("name") if isinstance(owner, dict) else owner or "")[:200],
        "description": str(
            (data.get("metadata") or {}).get("description") or data.get("description") or ""
        )[:500]
        if isinstance(data.get("metadata"), dict) or data.get("description")
        else "",
        "plugins": plugins,
    }
