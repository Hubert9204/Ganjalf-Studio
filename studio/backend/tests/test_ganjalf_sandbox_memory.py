# SPDX-License-Identifier: AGPL-3.0-only
# Copyright 2026-present the Unsloth AI Inc. team. All rights reserved. See /studio/LICENSE.AGPL-3.0

"""Ganjalf's sandbox memory cap on Linux: room for Node's WebAssembly reservations, RSS for the limit."""

from __future__ import annotations

import shutil
import sys

import pytest

from core.inference import tools
from utils import sandbox_memory_limit

_SESSION = "ganjalf-sandbox-memory"
linux = pytest.mark.skipif(sys.platform != "linux", reason = "RLIMIT_AS is the Linux cap")


@pytest.fixture(autouse = True)
def _limit(monkeypatch):
    monkeypatch.setenv(sandbox_memory_limit.MEMORY_LIMIT_ENV, "8")
    monkeypatch.delenv("GANJALF_SANDBOX_AS_HEADROOM_GB", raising = False)
    yield
    tools._refresh_sandbox_memory_limit()


@linux
def test_the_cap_is_the_limit_plus_headroom_with_the_watchdog_on():
    tools._refresh_sandbox_memory_limit()
    assert tools._sandbox_as_bytes == (8 + 48) * 1024**3
    assert tools._linux_rss_watchdog is True


@linux
def test_headroom_is_configurable_and_zero_restores_the_strict_cap(monkeypatch):
    monkeypatch.setenv("GANJALF_SANDBOX_AS_HEADROOM_GB", "16")
    tools._refresh_sandbox_memory_limit()
    assert tools._sandbox_as_bytes == 24 * 1024**3
    monkeypatch.setenv("GANJALF_SANDBOX_AS_HEADROOM_GB", "0")
    tools._refresh_sandbox_memory_limit()
    assert tools._sandbox_as_bytes == 8 * 1024**3 and tools._linux_rss_watchdog is False


@linux
def test_without_psutil_the_strict_cap_stays(monkeypatch):
    monkeypatch.setattr(tools, "_psutil_available", lambda: False)
    tools._refresh_sandbox_memory_limit()
    assert tools._sandbox_as_bytes == 8 * 1024**3 and tools._linux_rss_watchdog is False


@linux
@pytest.mark.skipif(shutil.which("node") is None, reason = "needs node")
def test_node_can_instantiate_webassembly_under_the_default_limit():
    """What `vite build` does first; under a strict 8 GiB address-space cap it dies with
    'Cannot allocate Wasm memory'."""
    out = tools._bash_exec(
        """node -e "new WebAssembly.Memory({initial: 1}); console.log('WASM OK')" """,
        None,
        60,
        _SESSION,
    )
    assert "WASM OK" in out, out


@pytest.mark.skipif(shutil.which("node") is None, reason = "needs node")
def test_node_writes_no_compile_cache_into_the_project(tmp_path):
    out = tools._bash_exec(
        """node -e "console.log(require('module').enableCompileCache().status)" """,
        None,
        60,
        _SESSION,
    )
    assert "3" in out.split(), out  # 3 = disabled by NODE_DISABLE_COMPILE_CACHE
