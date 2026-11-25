# SPDX-License-Identifier: AGPL-3.0-only
# Copyright 2026-present the Unsloth AI Inc. team. All rights reserved. See /studio/LICENSE.AGPL-3.0

"""Ganjalf checks for updates against its own repository, never Unsloth's PyPI package."""

from __future__ import annotations

import json

import pytest

from utils import ganjalf_update as gu
from utils import update_status

LOCAL = "a" * 40
HEAD = "b" * 40


@pytest.fixture(autouse = True)
def _clean(monkeypatch):
    for name in (
        "GANJALF_UPDATE_SOURCE",
        "GANJALF_UPDATE_REPO",
        "GANJALF_UPDATE_BRANCH",
        "GANJALF_STUDIO_REVISION",
        "UNSLOTH_DISABLE_UPDATE_CHECK",
        "UNSLOTH_STUDIO_FAKE_UPDATE",
        "UNSLOTH_STUDIO_APP",
        "UNSLOTH_STUDIO_REPO",
    ):
        monkeypatch.delenv(name, raising = False)
    gu.reset_cache()
    # The PyPI path must never run for a Ganjalf tree.
    monkeypatch.setattr(
        update_status, "get_latest_pypi_version", lambda: pytest.fail("Unsloth's PyPI was asked")
    )
    yield
    gu.reset_cache()


def _github(
    monkeypatch,
    ahead_by,
    head = HEAD,
    calls = None,
):
    def fake(repo, branch, local):
        if calls is not None:
            calls.append((repo, branch, local))
        return gu.GanjalfComparison(head = head, ahead_by = ahead_by)

    monkeypatch.setattr(gu, "_fetch_comparison", fake)


def test_this_checkout_is_a_ganjalf_install():
    assert gu.is_ganjalf_install()


def test_an_upstream_tree_is_not(tmp_path):
    (tmp_path / "studio").mkdir()
    assert not gu.is_ganjalf_install(tmp_path)


def test_repo_and_branch_default_to_ganjalf_and_take_urls(monkeypatch):
    assert gu.update_repo() == "Hubert9204/Ganjalf-Studio" and gu.update_branch() == "main"
    monkeypatch.setenv("GANJALF_UPDATE_REPO", "https://github.com/me/my-fork.git")
    monkeypatch.setenv("GANJALF_UPDATE_BRANCH", "dev")
    assert gu.repo_url() == "https://github.com/me/my-fork" and gu.update_branch() == "dev"
    monkeypatch.delenv("GANJALF_UPDATE_REPO")
    monkeypatch.setenv("UNSLOTH_STUDIO_REPO", "https://github.com/docker/built-from")
    assert gu.update_repo() == "docker/built-from"
    monkeypatch.setenv("GANJALF_UPDATE_REPO", "not a repo; rm -rf")
    monkeypatch.setenv("GANJALF_UPDATE_BRANCH", "../../etc")
    assert gu.update_repo() == "Hubert9204/Ganjalf-Studio" and gu.update_branch() == "main"


def test_revision_file_wins_over_git(tmp_path):
    (tmp_path / gu.REVISION_FILE).write_text(LOCAL + "\n")
    assert gu.local_revision(tmp_path) == LOCAL
    (tmp_path / gu.REVISION_FILE).write_text("garbage")
    assert gu.local_revision(tmp_path) is None


def test_an_install_behind_its_branch_offers_the_ganjalf_update(monkeypatch):
    monkeypatch.setenv("GANJALF_STUDIO_REVISION", LOCAL)
    calls = []
    _github(monkeypatch, 3, calls = calls)
    status = update_status.get_studio_update_status("2026.11.1")
    assert calls == [("Hubert9204/Ganjalf-Studio", "main", LOCAL)]
    assert status["install_source"] == "ganjalf"
    assert status["update_available"] is True and status["can_show_web_notification"] is True
    assert (status["current_version"], status["latest_version"]) == (LOCAL[:7], HEAD[:7])
    assert status["commits_behind"] == 3
    assert status["update_repo"] == "https://github.com/Hubert9204/Ganjalf-Studio"
    assert (
        status["release_notes_url"]
        == f"https://github.com/Hubert9204/Ganjalf-Studio/compare/{LOCAL[:12]}...main"
    )
    assert "unsloth.ai" not in json.dumps(status["update_command"])


def test_an_up_to_date_install_shows_nothing(monkeypatch):
    monkeypatch.setenv("GANJALF_STUDIO_REVISION", LOCAL)
    _github(monkeypatch, 0)
    status = update_status.get_studio_update_status("2026.11.1")
    assert status["update_available"] is False and status["can_show_web_notification"] is False
    assert status["commits_behind"] == 0


def test_the_answer_is_cached(monkeypatch):
    monkeypatch.setenv("GANJALF_STUDIO_REVISION", LOCAL)
    calls = []
    _github(monkeypatch, 1, calls = calls)
    update_status.get_studio_update_status("x")
    update_status.get_studio_update_status("x")
    assert len(calls) == 1


def test_offline_is_reported_not_raised(monkeypatch):
    monkeypatch.setenv("GANJALF_STUDIO_REVISION", LOCAL)

    def boom(*_args):
        raise OSError("no network")

    monkeypatch.setattr(gu, "_fetch_comparison", boom)
    status = update_status.get_studio_update_status("x")
    assert status["reason"] == "offline" and status["update_available"] is False


def test_off_and_the_upstream_kill_switch_stop_the_check(monkeypatch):
    monkeypatch.setenv("GANJALF_STUDIO_REVISION", LOCAL)
    _github(monkeypatch, 5, calls = (calls := []))
    monkeypatch.setenv("GANJALF_UPDATE_SOURCE", "off")
    assert update_status.get_studio_update_status("x")["reason"] == "disabled"
    monkeypatch.delenv("GANJALF_UPDATE_SOURCE")
    monkeypatch.setenv("UNSLOTH_DISABLE_UPDATE_CHECK", "1")
    assert update_status.get_studio_update_status("x")["reason"] == "disabled"
    assert calls == []


def test_unsloth_source_falls_back_to_upstream_behaviour(monkeypatch):
    monkeypatch.setenv("GANJALF_UPDATE_SOURCE", "unsloth")
    _github(monkeypatch, 5, calls = (calls := []))
    status = update_status.get_studio_update_status("x")
    assert status["install_source"] != "ganjalf" and calls == []


def test_the_command_fits_the_install(monkeypatch):
    monkeypatch.setattr(gu, "in_container", lambda: True)
    assert gu.update_command() == "docker exec <container> unsloth-studio-update"
    monkeypatch.setattr(gu, "in_container", lambda: False)
    assert gu.update_command() == "git pull && bash scripts/ganjalf-launch.sh"
