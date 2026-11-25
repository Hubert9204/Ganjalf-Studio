# SPDX-License-Identifier: AGPL-3.0-only
"""Ganjalf: the owner's folder picker walks the whole disk -- up from the home to /home and /."""

import os
import sys
import types

import pytest
from fastapi import HTTPException

if "structlog" not in sys.modules:

    class _DummyLogger:
        def __getattr__(self, _name):
            return lambda *args, **kwargs: None

    sys.modules["structlog"] = types.SimpleNamespace(
        BoundLogger = _DummyLogger,
        get_logger = lambda *args, **kwargs: _DummyLogger(),
    )

import routes.models as models_route

pytestmark = pytest.mark.skipif(os.name != "posix", reason = "POSIX filesystem root")


@pytest.fixture
def home(tmp_path, monkeypatch):
    home = tmp_path / "home" / "me"
    home.mkdir(parents = True)
    monkeypatch.setattr(models_route, "_build_browse_allowlist", lambda *_a, **_k: [home.resolve()])
    monkeypatch.setattr(models_route.account_access, "managed_account", lambda: False)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("GANJALF_BROWSE_ALL", raising = False)
    return home


def test_the_picker_goes_up_past_the_home_to_the_root(home, tmp_path):
    listing = models_route.browse_folders(str(home), False, "owner", False)
    assert listing.parent == str(home.parent)  # /home, not a dead end at the home folder

    other = tmp_path / "data" / "models"
    other.mkdir(parents = True)
    listing = models_route.browse_folders(str(other.parent), False, "owner", False)
    assert [entry.name for entry in listing.entries] == ["models"]

    root = models_route.browse_folders("/", False, "owner", False)
    assert root.current == "/" and root.parent is None
    names = {entry.name for entry in root.entries}
    assert "proc" not in names and "sys" not in names and "dev" not in names
    assert "Computer" in [place.label for place in root.places]


def test_pseudo_filesystems_and_credentials_stay_closed(home):
    with pytest.raises(HTTPException) as exc_info:
        models_route.browse_folders("/proc", False, "owner", False)
    assert exc_info.value.status_code == 403
    (home / ".ssh").mkdir()
    with pytest.raises(HTTPException) as exc_info:
        models_route.browse_folders(str(home / ".ssh"), True, "owner", False)
    assert exc_info.value.status_code == 403


def test_managed_accounts_and_the_switch_keep_the_old_limits(home, tmp_path, monkeypatch):
    outside = tmp_path / "data"
    outside.mkdir()
    monkeypatch.setenv("GANJALF_BROWSE_ALL", "0")
    with pytest.raises(HTTPException) as exc_info:
        models_route.browse_folders(str(outside), False, "owner", False)
    assert exc_info.value.status_code == 403
    assert models_route.browse_folders(str(home), False, "owner", False).parent is None

    monkeypatch.delenv("GANJALF_BROWSE_ALL")
    assert models_route._browse_whole_disk(managed = True) is False
    assert models_route._browse_whole_disk(managed = False) is True
