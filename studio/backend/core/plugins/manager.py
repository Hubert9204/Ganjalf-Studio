# SPDX-License-Identifier: AGPL-3.0-only
# Copyright 2026-present the Unsloth AI Inc. team. All rights reserved. See /studio/LICENSE.AGPL-3.0

"""Installed plugins: where they live, what they add to Studio, and turning them on and off.

Layout under ``<studio home>/plugins``:

    registry.json           installed plugins and added marketplaces
    installed/<name>/       the plugin's files (${CLAUDE_PLUGIN_ROOT})
    data/<name>/            its persistent data (${CLAUDE_PLUGIN_DATA}), kept across updates
    skills/<skill>/         its skills and commands as Studio skills (a skill root, rebuilt on change)
    marketplaces/<name>/    a copy of each added marketplace
    staging/<token>/        downloads waiting for the user to confirm

A plugin's skills become ``<plugin>-<skill>`` (just ``<plugin>`` when the names match), its
commands ``<plugin>-<command>`` skills that the user calls with ``/name`` or ``@name``, its MCP
servers rows in the MCP list, its hooks run only after the user switches them on, and its agents
are offered to the model through ``run_agent``.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

import yaml

from .fetch import FetchError, Source, copy_tree, fetch, github_commit, parse_source
from .inspect import PluginError, inspect_plugin, read_markdown, read_marketplace, slug

_LOCK = threading.RLock()
_STAGING_TTL_S = 3600
_ENV_REFERENCE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")

Validate = Callable[[str], str]


def plugins_root() -> Path:
    from utils.paths.storage_roots import studio_root
    override = (os.environ.get("GANJALF_PLUGINS_HOME") or "").strip()
    return Path(override).expanduser() if override else studio_root() / "plugins"


def skills_root() -> Path:
    return plugins_root() / "skills"


def _registry_path() -> Path:
    return plugins_root() / "registry.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec = "seconds")


def load_registry() -> dict:
    try:
        data = json.loads(_registry_path().read_text(encoding = "utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, UnicodeDecodeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("plugins", {})
    data.setdefault("marketplaces", {})
    return data


def _save_registry(data: dict) -> None:
    path = _registry_path()
    path.parent.mkdir(parents = True, exist_ok = True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(data, indent = 2, ensure_ascii = False), encoding = "utf-8")
    os.replace(temp, path)


def plugin_dir(name: str) -> Path:
    return plugins_root() / "installed" / name


def data_dir(name: str) -> Path:
    path = plugins_root() / "data" / name
    path.mkdir(parents = True, exist_ok = True)
    return path


def expand(
    value: str,
    name: str,
    missing: Optional[set] = None,
) -> str:
    """${CLAUDE_PLUGIN_ROOT}, ${CLAUDE_PLUGIN_DATA} and ${VAR} / ${VAR:-default} from the environment."""

    def replace(match: re.Match) -> str:
        key, default = match[1], match[2]
        if key == "CLAUDE_PLUGIN_ROOT":
            return str(plugin_dir(name))
        if key == "CLAUDE_PLUGIN_DATA":
            return str(data_dir(name))
        if key == "CLAUDE_PROJECT_DIR":
            return os.environ.get("CLAUDE_PROJECT_DIR", "")
        if key in os.environ:
            return os.environ[key]
        if default is not None:
            return default
        if missing is not None:
            missing.add(key)
        return ""

    return _ENV_REFERENCE.sub(replace, value)


def _expand_tree(value: Any, name: str, missing: set) -> Any:
    if isinstance(value, str):
        return expand(value, name, missing)
    if isinstance(value, list):
        return [_expand_tree(item, name, missing) for item in value]
    if isinstance(value, dict):
        return {key: _expand_tree(item, name, missing) for key, item in value.items()}
    return value


# ---------------------------------------------------------------- staging and preview


def _cleanup_staging() -> None:
    root = plugins_root() / "staging"
    if not root.is_dir():
        return
    cutoff = time.time() - _STAGING_TTL_S
    for entry in root.iterdir():
        try:
            if entry.stat().st_mtime < cutoff:
                shutil.rmtree(entry, ignore_errors = True)
        except OSError:
            pass


def _stage(source: Source) -> tuple[str, Path, dict]:
    _cleanup_staging()
    token = uuid.uuid4().hex
    dest = plugins_root() / "staging" / token
    result = fetch(source, dest)
    return token, dest / "content", result


def _staged(token: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{32}", token or ""):
        raise PluginError("That download is no longer available; start again.")
    path = plugins_root() / "staging" / token
    if not (path / "meta.json").is_file():
        raise PluginError("That download is no longer available; start again.")
    return path


def _write_meta(token: str, meta: dict) -> None:
    (plugins_root() / "staging" / token / "meta.json").write_text(
        json.dumps(meta), encoding = "utf-8"
    )


def _marketplace_entry_source(market: dict, entry_source: Any) -> tuple[Source, Optional[Path]]:
    """(source to fetch, or a folder inside the marketplace copy)."""
    folder = plugins_root() / "marketplaces" / market["name"]
    if isinstance(entry_source, str):
        relative = entry_source.strip()
        target = (folder / relative).resolve()
        if folder.resolve() not in target.parents and target != folder.resolve():
            raise PluginError("The marketplace points outside itself.")
        return Source("local", url = str(target)), target
    if isinstance(entry_source, dict):
        kind = entry_source.get("source")
        if kind == "github" and entry_source.get("repo"):
            owner, _, repo = str(entry_source["repo"]).partition("/")
            return (
                Source(
                    "github",
                    owner = owner,
                    repo = repo,
                    ref = str(entry_source.get("ref") or entry_source.get("sha") or ""),
                    path = str(entry_source.get("path") or ""),
                ),
                None,
            )
        if kind in ("url", "git-subdir") and entry_source.get("url"):
            source = parse_source(str(entry_source["url"]))
            source.ref = str(entry_source.get("ref") or entry_source.get("sha") or source.ref)
            if entry_source.get("path"):
                source.path = str(entry_source["path"]).strip("/")
            return source, None
        raise PluginError(
            f"Marketplace source type {kind!r} is not supported (npm and pip sources are not)."
        )
    raise PluginError("The marketplace entry has no source.")


def preview(source_text: str) -> dict:
    """Downloads into staging and says what it is. `plugin@marketplace` installs from an added
    marketplace. A plugin comes back with a token for install(); a marketplace with its listing."""
    with _LOCK:
        text = (source_text or "").strip()
        registry = load_registry()
        if (
            "@" in text
            and "/" not in text.split("@", 1)[0]
            and text.split("@", 1)[1] in registry["marketplaces"]
        ):
            plugin_name, market_name = text.split("@", 1)
            return _preview_from_marketplace(
                registry["marketplaces"][market_name], slug(plugin_name)
            )
        source = parse_source(text)
        token, content, result = _stage(source)
        market = read_marketplace(content)
        manifest_present = (content / ".claude-plugin" / "plugin.json").is_file()
        if market and not manifest_present:
            shutil.rmtree(plugins_root() / "staging" / token, ignore_errors = True)
            return {
                "kind": "marketplace",
                "source": source.to_dict(),
                "marketplace": _market_view(market),
            }
        summary = inspect_plugin(content)
        _write_meta(
            token, {"source": source.to_dict(), "commit": result.get("commit"), "marketplace": None}
        )
        return {"kind": "plugin", "token": token, "plugin": _with_install_state(summary)}


def preview_archive(data: bytes) -> dict:
    """A plugin (or marketplace) uploaded as a zip or tar archive."""
    from .fetch import _single_top_folder, unpack
    with _LOCK:
        _cleanup_staging()
        token = uuid.uuid4().hex
        staging = plugins_root() / "staging" / token
        unpack(data, staging / "raw")
        top = _single_top_folder(staging / "raw")
        os.replace(top, staging / "content")
        shutil.rmtree(staging / "raw", ignore_errors = True)
        content = staging / "content"
        if read_marketplace(content) and not (content / ".claude-plugin" / "plugin.json").is_file():
            shutil.rmtree(staging, ignore_errors = True)
            raise PluginError("This archive is a marketplace; add it from its repository instead.")
        summary = inspect_plugin(content)
        _write_meta(token, {"source": None, "commit": None, "marketplace": None})
        return {"kind": "plugin", "token": token, "plugin": _with_install_state(summary)}


def _preview_from_marketplace(market: dict, plugin_name: str) -> dict:
    entry = next((item for item in market.get("plugins", []) if item["name"] == plugin_name), None)
    if entry is None:
        raise PluginError(f"The marketplace {market['name']} has no plugin {plugin_name}.")
    source, folder = _marketplace_entry_source(market, entry["source"])
    token = uuid.uuid4().hex
    dest = plugins_root() / "staging" / token
    if folder is not None:
        if not folder.is_dir():
            raise PluginError(
                f"The marketplace folder for {plugin_name} is missing; refresh the marketplace."
            )
        copy_tree(folder, dest / "content")
        result = {"commit": market.get("commit")}
    else:
        result = fetch(source, dest)
    summary = inspect_plugin(dest / "content", entry.get("entry"))
    _write_meta(
        token,
        {
            "source": source.to_dict() if folder is None else None,
            "commit": result.get("commit"),
            "marketplace": market["name"],
            "marketplace_plugin": plugin_name,
            "entry": entry.get("entry"),
        },
    )
    return {"kind": "plugin", "token": token, "plugin": _with_install_state(summary)}


def _with_install_state(summary: dict) -> dict:
    installed = load_registry()["plugins"].get(summary["name"])
    return {
        **summary,
        "installed_version": installed.get("version") if installed else None,
        "installed": bool(installed),
    }


# ---------------------------------------------------------------- install, update, remove


def _skill_name(plugin: str, part: str) -> Optional[str]:
    piece = slug(part.replace(":", "-"))
    if not piece:
        return None
    name = plugin if piece == plugin else f"{plugin}-{piece}"
    if len(name) > 64:
        digest = hashlib.sha1(name.encode()).hexdigest()[:6]
        name = f"{name[:57].rstrip('-')}-{digest}"
    return name


def _clean_frontmatter(
    frontmatter: dict, name: str, description: str, extra_metadata: dict
) -> dict:
    keep = {"name": name, "description": description[:1024]}
    for key in ("license", "compatibility"):
        value = frontmatter.get(key)
        if isinstance(value, str) and value.strip():
            keep[key] = value[: 500 if key == "compatibility" else 1024]
    tools = frontmatter.get("allowed-tools")
    if isinstance(tools, list):
        tools = " ".join(str(tool) for tool in tools)
    if isinstance(tools, str) and tools.strip():
        keep["allowed-tools"] = tools[:1024]
    metadata = frontmatter.get("metadata")
    merged = (
        {str(k): str(v)[:500] for k, v in metadata.items()} if isinstance(metadata, dict) else {}
    )
    merged.update(extra_metadata)
    keep["metadata"] = merged
    return keep


def _write_skill(dest: Path, frontmatter: dict, body: str) -> None:
    dest.mkdir(parents = True, exist_ok = True)
    head = yaml.safe_dump(frontmatter, sort_keys = False, allow_unicode = True).strip()
    (dest / "SKILL.md").write_text(f"---\n{head}\n---\n\n{body.strip()}\n", encoding = "utf-8")


def _substitute_body(
    body: str,
    plugin: str,
    skill_dir: Optional[Path] = None,
) -> str:
    body = body.replace("${CLAUDE_PLUGIN_ROOT}", str(plugin_dir(plugin)))
    body = body.replace("${CLAUDE_PLUGIN_DATA}", str(plugins_root() / "data" / plugin))
    if skill_dir is not None:
        body = body.replace("${CLAUDE_SKILL_DIR}", str(skill_dir))
    return body


def _remove_generated(record: dict) -> None:
    root = skills_root()
    for name in record.get("skills", []) + record.get("commands", []):
        target = root / name
        if target.is_dir() and target.parent == root:
            shutil.rmtree(target, ignore_errors = True)


def _materialize(name: str, summary: dict, warnings: list[str]) -> tuple[list[str], list[str]]:
    """The plugin's skills and commands as Studio skills in the plugin skill root."""
    root = plugin_dir(name)
    out = skills_root()
    out.mkdir(parents = True, exist_ok = True)
    taken = {entry.name for entry in out.iterdir() if entry.is_dir()}
    skills, commands = [], []
    for skill in summary.get("skills", []):
        generated = _skill_name(name, skill["name"])
        if not generated or generated in taken:
            warnings.append(f"skill {skill['name']} clashes with another plugin's and was skipped")
            continue
        source_dir = (root / skill["path"]).resolve()
        dest = out / generated
        copy_tree(source_dir, dest)
        try:
            frontmatter, body = read_markdown(source_dir / "SKILL.md")
        except PluginError as exc:
            warnings.append(str(exc))
            shutil.rmtree(dest, ignore_errors = True)
            continue
        description = str(frontmatter.get("description") or skill.get("description") or generated)
        _write_skill(
            dest,
            _clean_frontmatter(
                frontmatter, generated, description, {"plugin": name, "plugin-skill": skill["name"]}
            ),
            _substitute_body(body, name, dest),
        )
        taken.add(generated)
        skills.append(generated)
    for command in summary.get("commands", []):
        generated = _skill_name(name, command["name"])
        if not generated or generated in taken:
            warnings.append(f"command {command['name']} clashes with a skill and was skipped")
            continue
        try:
            if command.get("path"):
                frontmatter, body = read_markdown(root / command["path"])
            else:
                frontmatter, body = {}, str(command.get("content") or "")
        except PluginError as exc:
            warnings.append(str(exc))
            continue
        hint = f" Arguments: {command['argument_hint']}." if command.get("argument_hint") else ""
        description = (
            command.get("description") or f"The {command['name']} command"
        ) + f" (command /{generated}).{hint}"
        preface = (
            f"This is the `/{generated}` command of the {name} plugin. The user called it; follow it now. "
            "`$ARGUMENTS` (and `$1`, `$2`, ...) stand for what the user wrote after the command name. "
            "A command written as !`...` is shell output Claude Code fills in before reading: run it "
            "with the terminal tool if you have one.\n\n"
        )
        _write_skill(
            out / generated,
            _clean_frontmatter(
                frontmatter,
                generated,
                description,
                {"plugin": name, "plugin-command": command["name"]},
            ),
            preface + _substitute_body(body, name),
        )
        taken.add(generated)
        commands.append(generated)
    return skills, commands


def _mcp_rows(
    name: str, summary: dict, enabled: bool, validate: Optional[Validate], warnings: list[str]
) -> dict:
    from core.inference.mcp_config_import import parse_mcp_config
    from storage import mcp_servers_db

    created: dict[str, str] = {}
    for server, spec in summary.get("mcp_servers", {}).items():
        missing: set = set()
        expanded = _expand_tree(spec, name, missing)
        if missing:
            warnings.append(
                f"MCP server {server}: set {', '.join(sorted(missing))} in the environment Studio runs in, then update the plugin"
            )
            continue
        label = f"{name} · {server}"
        entries, errors = parse_mcp_config({"mcpServers": {label: expanded}})
        warnings.extend(errors)
        for entry in entries:
            try:
                url = validate(entry.url) if validate else entry.url
            except Exception as exc:  # HTTPException from the route's checks
                warnings.append(f"MCP server {server}: {getattr(exc, 'detail', exc)}")
                continue
            server_id = uuid.uuid4().hex[:16]
            try:
                mcp_servers_db.create_server(
                    id = server_id,
                    display_name = label,
                    url = url,
                    headers_json = json.dumps(entry.headers) if entry.headers else None,
                    is_enabled = enabled and entry.is_enabled,
                    use_oauth = entry.use_oauth and not entry.is_stdio,
                )
            except Exception as exc:
                warnings.append(f"MCP server {server}: {exc}")
                continue
            created[server] = server_id
    return created


def _drop_mcp_rows(record: dict) -> None:
    from storage import mcp_servers_db
    for server_id in (record.get("mcp_server_ids") or {}).values():
        old = mcp_servers_db.get_server(server_id)
        if not old:
            continue
        mcp_servers_db.delete_server(server_id)
        try:
            from core.inference.mcp_client import (
                close_mcp_sessions,
                invalidate_tool_cache,
                parse_server_headers,
            )
            invalidate_tool_cache(server_id)
            close_mcp_sessions(old["url"], parse_server_headers(old))
        except Exception:
            pass


def _set_mcp_enabled(record: dict, enabled: bool) -> None:
    from storage import mcp_servers_db
    for server_id in (record.get("mcp_server_ids") or {}).values():
        mcp_servers_db.update_server(server_id, {"is_enabled": enabled})
        try:
            from core.inference.mcp_client import invalidate_tool_cache
            invalidate_tool_cache(server_id)
        except Exception:
            pass


def install(
    token: str,
    *,
    validate: Optional[Validate] = None,
    enable_hooks: bool = False,
) -> dict:
    """Moves a previewed plugin into place and adds its parts to Studio. Replaces an installed
    plugin of the same name (an update), keeping its on/off choices and its data folder."""
    with _LOCK:
        staged = _staged(token)
        meta = json.loads((staged / "meta.json").read_text(encoding = "utf-8"))
        summary = inspect_plugin(staged / "content", meta.get("entry"))
        name = summary["name"]
        registry = load_registry()
        previous = registry["plugins"].get(name)
        if previous:
            _remove_generated(previous)
            _drop_mcp_rows(previous)
        target = plugin_dir(name)
        if target.exists():
            shutil.rmtree(target)
        target.parent.mkdir(parents = True, exist_ok = True)
        os.replace(staged / "content", target)
        shutil.rmtree(staged, ignore_errors = True)
        data_dir(name)
        enabled = previous.get("enabled", True) if previous else True
        warnings = list(summary.get("warnings", []))
        skills, commands = _materialize(name, summary, warnings) if enabled else ([], [])
        record = {
            "name": name,
            "display_name": summary["display_name"],
            "version": summary["version"],
            "description": summary["description"],
            "author": summary["author"],
            "homepage": summary["homepage"],
            "source": meta.get("source"),
            "marketplace": meta.get("marketplace"),
            "marketplace_plugin": meta.get("marketplace_plugin"),
            "commit": meta.get("commit"),
            "installed_at": previous.get("installed_at") if previous else _now(),
            "updated_at": _now(),
            "enabled": enabled,
            "hooks_enabled": bool(previous.get("hooks_enabled"))
            if previous
            else bool(enable_hooks),
            "skills": skills,
            "commands": commands,
            "agents": [agent["name"] for agent in summary.get("agents", [])],
            "hook_events": sorted(summary.get("hooks", {})),
            "mcp_servers": sorted(summary.get("mcp_servers", {})),
            "unsupported": summary.get("unsupported", []),
        }
        record["mcp_server_ids"] = _mcp_rows(name, summary, enabled, validate, warnings)
        record["warnings"] = warnings[:50]
        registry["plugins"][name] = record
        _save_registry(registry)
        return plugin_view(record)


def set_enabled(name: str, enabled: bool) -> dict:
    with _LOCK:
        registry = load_registry()
        record = _record(registry, name)
        if record["enabled"] == enabled:
            return plugin_view(record)
        record["enabled"] = enabled
        warnings: list[str] = []
        if enabled:
            summary = inspect_plugin(plugin_dir(name))
            record["skills"], record["commands"] = _materialize(name, summary, warnings)
        else:
            _remove_generated(record)
            record["skills"], record["commands"] = [], []
        _set_mcp_enabled(record, enabled)
        record["warnings"] = warnings or record.get("warnings", [])
        _save_registry(registry)
        return plugin_view(record)


def set_hooks_enabled(name: str, enabled: bool) -> dict:
    with _LOCK:
        registry = load_registry()
        record = _record(registry, name)
        record["hooks_enabled"] = bool(enabled)
        _save_registry(registry)
        return plugin_view(record)


def uninstall(name: str, *, keep_data: bool = False) -> None:
    with _LOCK:
        registry = load_registry()
        record = _record(registry, name)
        _remove_generated(record)
        _drop_mcp_rows(record)
        shutil.rmtree(plugin_dir(name), ignore_errors = True)
        if not keep_data:
            shutil.rmtree(plugins_root() / "data" / name, ignore_errors = True)
        del registry["plugins"][name]
        _save_registry(registry)


def _record(registry: dict, name: str) -> dict:
    record = registry["plugins"].get(slug(name))
    if record is None:
        raise PluginError(f"No plugin named {name} is installed.")
    return record


def update(name: str, *, validate: Optional[Validate] = None) -> dict:
    """Fetches the plugin again from where it came from and reinstalls it."""
    with _LOCK:
        record = _record(load_registry(), name)
        if record.get("marketplace"):
            refresh_marketplace(record["marketplace"])
            result = preview(
                f"{record.get('marketplace_plugin') or record['name']}@{record['marketplace']}"
            )
        elif record.get("source"):
            source = Source.from_dict(record["source"])
            if source.kind == "local":
                raise PluginError(
                    "A plugin installed from a folder is updated by installing that folder again."
                )
            result = preview(source.label() if source.kind == "github" else source.url)
        else:
            raise PluginError("This plugin does not record where it came from; install it again.")
        if result.get("kind") != "plugin":
            raise PluginError("The source no longer holds a plugin.")
        return install(result["token"], validate = validate)


def check_updates() -> dict[str, bool]:
    """Plugins from GitHub whose branch moved since install (others are left out)."""
    out: dict[str, bool] = {}
    for name, record in load_registry()["plugins"].items():
        source = record.get("source") or {}
        if record.get("marketplace"):
            market = load_registry()["marketplaces"].get(record["marketplace"], {})
            source = market.get("source") or {}
            commit = market.get("commit")
        else:
            commit = record.get("commit")
        if source.get("kind") != "github" or not commit:
            continue
        latest = github_commit(source["owner"], source["repo"], source.get("ref", ""))
        if latest:
            out[name] = not latest.startswith(commit) and not commit.startswith(latest)
    return out


# ---------------------------------------------------------------- marketplaces


def _market_view(market: dict) -> dict:
    installed = load_registry()["plugins"]
    return {
        "name": market["name"],
        "owner": market.get("owner", ""),
        "description": market.get("description", ""),
        "source": market.get("source"),
        "commit": market.get("commit"),
        "plugins": [
            {key: item[key] for key in ("name", "description", "version", "category")}
            | {"installed": item["name"] in installed}
            for item in market.get("plugins", [])
        ],
    }


def add_marketplace(source_text: str) -> dict:
    with _LOCK:
        source = parse_source(source_text)
        token, content, result = _stage(source)
        listing = read_marketplace(content)
        if listing is None:
            shutil.rmtree(plugins_root() / "staging" / token, ignore_errors = True)
            raise PluginError(
                "No .claude-plugin/marketplace.json there. To install a single plugin, use Install."
            )
        folder = plugins_root() / "marketplaces" / listing["name"]
        if folder.exists():
            shutil.rmtree(folder)
        folder.parent.mkdir(parents = True, exist_ok = True)
        os.replace(content, folder)
        shutil.rmtree(plugins_root() / "staging" / token, ignore_errors = True)
        registry = load_registry()
        market = {
            **{key: value for key, value in listing.items()},
            "source": source.to_dict(),
            "commit": result.get("commit"),
            "added_at": _now(),
        }
        registry["marketplaces"][listing["name"]] = market
        _save_registry(registry)
        return _market_view(market)


def refresh_marketplace(name: str) -> dict:
    with _LOCK:
        market = load_registry()["marketplaces"].get(name)
        if market is None:
            raise PluginError(f"No marketplace named {name}.")
        source = Source.from_dict(market["source"])
        return add_marketplace(source.label() if source.kind == "github" else source.url)


def remove_marketplace(name: str) -> None:
    with _LOCK:
        registry = load_registry()
        if registry["marketplaces"].pop(name, None) is None:
            raise PluginError(f"No marketplace named {name}.")
        shutil.rmtree(plugins_root() / "marketplaces" / name, ignore_errors = True)
        _save_registry(registry)


def list_marketplaces() -> list[dict]:
    return [_market_view(market) for market in load_registry()["marketplaces"].values()]


# ---------------------------------------------------------------- reading


def plugin_view(record: dict) -> dict:
    return {key: value for key, value in record.items() if key != "mcp_server_ids"} | {
        "mcp_server_count": len(record.get("mcp_server_ids") or {})
    }


def list_plugins() -> list[dict]:
    return [
        plugin_view(record)
        for record in sorted(load_registry()["plugins"].values(), key = lambda r: r["name"])
    ]


def plugin_details(name: str) -> dict:
    record = _record(load_registry(), name)
    try:
        summary = inspect_plugin(plugin_dir(record["name"]))
    except (PluginError, OSError) as exc:
        summary = {"warnings": [str(exc)]}
    return {**plugin_view(record), "contents": summary}


def enabled_records() -> list[dict]:
    return [record for record in load_registry()["plugins"].values() if record.get("enabled")]


__all__ = [
    "FetchError",
    "PluginError",
    "add_marketplace",
    "check_updates",
    "enabled_records",
    "expand",
    "install",
    "list_marketplaces",
    "list_plugins",
    "load_registry",
    "plugin_details",
    "plugin_dir",
    "plugins_root",
    "preview",
    "preview_archive",
    "refresh_marketplace",
    "remove_marketplace",
    "set_enabled",
    "set_hooks_enabled",
    "skills_root",
    "uninstall",
    "update",
]
