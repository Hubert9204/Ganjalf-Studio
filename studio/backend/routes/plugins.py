# SPDX-License-Identifier: AGPL-3.0-only
# Copyright 2026-present the Unsloth AI Inc. team. All rights reserved. See /studio/LICENSE.AGPL-3.0

"""Plugins (Claude Code format): install, inspect, switch on and off, update, remove.

A plugin can run commands on this machine (hooks, stdio MCP servers), so every route needs a
signed-in UI session of the owner account; API keys and managed accounts are refused. Install is
two steps: preview downloads and lists what the plugin holds, install applies it.
"""

from __future__ import annotations

from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from pydantic import BaseModel

from auth.authentication import authenticated_via_api_key, get_current_subject
from core.plugins import manager
from core.plugins.fetch import FetchError
from core.plugins.inspect import PluginError

router = APIRouter()

ViaApiKey = Annotated[bool, Depends(authenticated_via_api_key)]
MAX_UPLOAD_BYTES = 50 * 1024 * 1024


def _owner_ui(via_api_key: bool) -> None:
    from utils.account_context import is_owner_context
    if via_api_key:
        raise HTTPException(
            status_code = 403,
            detail = "Plugins can only be managed from the Studio window, not with an API key.",
        )
    if not is_owner_context():
        raise HTTPException(status_code = 403, detail = "Only the owner account can manage plugins.")


def _validate_mcp(url: str) -> str:
    from routes.mcp_servers import _validate_url
    return _validate_url(url)


def _run(action):
    try:
        result = action()
    except (PluginError, FetchError) as exc:
        raise HTTPException(status_code = 400, detail = str(exc)) from exc
    except OSError as exc:
        raise HTTPException(
            status_code = 500, detail = f"Could not write the plugin files: {exc}"
        ) from exc
    # Skills, commands and agents changed: the chat's skill list is cached for a second.
    try:
        from routes.inference import _invalidate_agent_skills_cache
        _invalidate_agent_skills_cache()
    except Exception:
        pass
    return result


class SourceRequest(BaseModel):
    source: str


class InstallRequest(BaseModel):
    token: str
    enable_hooks: bool = False


class EnabledRequest(BaseModel):
    enabled: bool


@router.get("")
def list_all(
    current_subject: str = Depends(get_current_subject), via_api_key: ViaApiKey = False
) -> dict[str, Any]:
    _owner_ui(via_api_key)
    return {"plugins": manager.list_plugins(), "marketplaces": manager.list_marketplaces()}


@router.post("/preview")
def preview(
    payload: SourceRequest,
    current_subject: str = Depends(get_current_subject),
    via_api_key: ViaApiKey = False,
):
    _owner_ui(via_api_key)
    return _run(lambda: manager.preview(payload.source))


@router.post("/upload")
async def upload(
    file: UploadFile = File(...),
    current_subject: str = Depends(get_current_subject),
    via_api_key: ViaApiKey = False,
):
    _owner_ui(via_api_key)
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code = 413, detail = "The archive is larger than 50 MB.")
    import asyncio

    return await asyncio.to_thread(_run, lambda: manager.preview_archive(data))


@router.post("/install")
def install(
    payload: InstallRequest,
    current_subject: str = Depends(get_current_subject),
    via_api_key: ViaApiKey = False,
):
    _owner_ui(via_api_key)
    return _run(
        lambda: manager.install(
            payload.token, validate = _validate_mcp, enable_hooks = payload.enable_hooks
        )
    )


@router.get("/updates")
def updates(
    current_subject: str = Depends(get_current_subject), via_api_key: ViaApiKey = False
) -> dict[str, bool]:
    _owner_ui(via_api_key)
    return manager.check_updates()


@router.post("/marketplaces")
def add_marketplace(
    payload: SourceRequest,
    current_subject: str = Depends(get_current_subject),
    via_api_key: ViaApiKey = False,
):
    _owner_ui(via_api_key)
    return _run(lambda: manager.add_marketplace(payload.source))


@router.post("/marketplaces/{name}/refresh")
def refresh_marketplace(
    name: str,
    current_subject: str = Depends(get_current_subject),
    via_api_key: ViaApiKey = False,
):
    _owner_ui(via_api_key)
    return _run(lambda: manager.refresh_marketplace(name))


@router.delete("/marketplaces/{name}", status_code = 204, response_class = Response)
def remove_marketplace(
    name: str,
    current_subject: str = Depends(get_current_subject),
    via_api_key: ViaApiKey = False,
):
    _owner_ui(via_api_key)
    _run(lambda: manager.remove_marketplace(name))
    return Response(status_code = 204)


@router.get("/{name}")
def details(
    name: str,
    current_subject: str = Depends(get_current_subject),
    via_api_key: ViaApiKey = False,
):
    _owner_ui(via_api_key)
    return _run(lambda: manager.plugin_details(name))


@router.put("/{name}/enabled")
def set_enabled(
    name: str,
    payload: EnabledRequest,
    current_subject: str = Depends(get_current_subject),
    via_api_key: ViaApiKey = False,
):
    _owner_ui(via_api_key)
    return _run(lambda: manager.set_enabled(name, payload.enabled))


@router.put("/{name}/hooks")
def set_hooks(
    name: str,
    payload: EnabledRequest,
    current_subject: str = Depends(get_current_subject),
    via_api_key: ViaApiKey = False,
):
    _owner_ui(via_api_key)
    return _run(lambda: manager.set_hooks_enabled(name, payload.enabled))


@router.post("/{name}/update")
def update(
    name: str,
    current_subject: str = Depends(get_current_subject),
    via_api_key: ViaApiKey = False,
):
    _owner_ui(via_api_key)
    return _run(lambda: manager.update(name, validate = _validate_mcp))


@router.delete("/{name}", status_code = 204, response_class = Response)
def uninstall(
    name: str,
    keep_data: Optional[bool] = False,
    current_subject: str = Depends(get_current_subject),
    via_api_key: ViaApiKey = False,
):
    _owner_ui(via_api_key)
    _run(lambda: manager.uninstall(name, keep_data = bool(keep_data)))
    return Response(status_code = 204)
