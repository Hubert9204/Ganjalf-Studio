# SPDX-License-Identifier: AGPL-3.0-only
# Copyright 2026-present the Unsloth AI Inc. team. All rights reserved. See /studio/LICENSE.AGPL-3.0

"""`unsloth studio update` on a Ganjalf tree pulls the fork and installs it, never Unsloth's PyPI."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import typer

from unsloth_cli.commands import studio


def _tree(tmp_path: Path, *, git: bool = True) -> Path:
    root = tmp_path / "Ganjalf-Studio"
    (root / "studio" / "ganjalf_skills").mkdir(parents = True)
    (root / "pyproject.toml").write_text("[project]\nname = 'unsloth'\n")
    if git:
        (root / ".git").mkdir()
    return root


@pytest.fixture(autouse = True)
def _env(monkeypatch):
    for name in (
        "GANJALF_UPDATE_SOURCE",
        "GANJALF_UPDATE_REPO",
        "GANJALF_UPDATE_BRANCH",
        "UNSLOTH_STUDIO_REPO",
    ):
        monkeypatch.delenv(name, raising = False)


def test_this_checkout_counts_as_a_ganjalf_tree(monkeypatch):
    monkeypatch.delenv("STUDIO_LOCAL_REPO", raising = False)
    assert studio._ganjalf_checkout() == Path(studio.__file__).resolve().parents[2]


def test_an_upstream_tree_or_the_unsloth_source_keeps_the_upstream_path(tmp_path, monkeypatch):
    upstream = tmp_path / "unsloth"
    (upstream / "studio").mkdir(parents = True)
    (upstream / "pyproject.toml").write_text("")
    monkeypatch.setenv("STUDIO_LOCAL_REPO", str(upstream))
    assert studio._ganjalf_checkout() is None
    monkeypatch.setenv("STUDIO_LOCAL_REPO", str(_tree(tmp_path)))
    monkeypatch.setenv("GANJALF_UPDATE_SOURCE", "unsloth")
    assert studio._ganjalf_checkout() is None


def test_the_checkout_is_fast_forwarded_from_the_ganjalf_repo(tmp_path, monkeypatch):
    root = _tree(tmp_path)
    monkeypatch.setenv("STUDIO_LOCAL_REPO", str(root))
    monkeypatch.setenv("GANJALF_UPDATE_BRANCH", "dev")
    calls = []
    monkeypatch.setattr(
        studio.subprocess,
        "run",
        lambda cmd, **kw: calls.append(cmd) or subprocess.CompletedProcess(cmd, 0),
    )
    assert studio._pull_ganjalf_checkout() is True
    assert calls == [
        [
            "git",
            "-C",
            str(root),
            "pull",
            "--ff-only",
            "https://github.com/Hubert9204/Ganjalf-Studio",
            "dev",
        ]
    ]


def test_a_tree_that_cannot_fast_forward_installs_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("STUDIO_LOCAL_REPO", str(_tree(tmp_path)))
    monkeypatch.setattr(
        studio.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1)
    )
    with pytest.raises(typer.Exit) as exc:
        studio._pull_ganjalf_checkout()
    assert exc.value.exit_code == 1


def test_a_tree_without_git_points_at_the_docker_updater(tmp_path, monkeypatch):
    monkeypatch.setenv("STUDIO_LOCAL_REPO", str(_tree(tmp_path, git = False)))
    with pytest.raises(typer.Exit) as exc:
        studio._pull_ganjalf_checkout()
    assert exc.value.exit_code == 2
