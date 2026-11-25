# SPDX-License-Identifier: AGPL-3.0-only
# Copyright 2026-present the Unsloth AI Inc. team. All rights reserved. See /studio/LICENSE.AGPL-3.0

"""Importing a bare SKILL.md, several loose files, or a folder of skills."""

from pathlib import Path

import pytest

from core.inference import skills
from core.inference.skill_md_import import (
    files_to_archive,
    looks_like_markdown_upload,
    markdown_to_archive,
)


def manifest(name: str) -> bytes:
    return f"---\nname: {name}\ndescription: Test skill.\n---\nBody for {name}.\n".encode()


@pytest.fixture
def skills_root(tmp_path, monkeypatch):
    root = tmp_path / "skills"
    root.mkdir()
    monkeypatch.setattr(skills, "_skill_roots", lambda home = None: (("agents", root),))
    # Imports write through _agents_base (base / root / name), not _skill_roots.
    monkeypatch.setattr(skills, "_agents_base", lambda home = None: (tmp_path, Path("skills")))
    monkeypatch.setattr(skills, "studio_root", lambda: tmp_path / "studio")
    return root


@pytest.mark.parametrize(
    "filename, data, expected",
    [
        ("SKILL.md", manifest("a"), True),
        ("notes.MARKDOWN", b"plain", True),
        ("upload.bin", manifest("a"), True),
        (None, b"\xef\xbb\xbf---\nname: a\n---\n", True),
        ("skill.md", b"PK\x03\x04rest", False),
        ("skill.zip", b"PK\x05\x06", False),
        ("data.bin", b"\x00\x01\x02", False),
    ],
)
def test_markdown_detection(filename, data, expected):
    assert looks_like_markdown_upload(filename, data) is expected


def test_bare_manifest_imports(skills_root):
    result = skills.import_skill_archive(markdown_to_archive(manifest("demo-skill")))
    assert [skill["name"] for skill in result["imported"]] == ["demo-skill"]
    assert not result["failed"]
    assert (skills_root / "demo-skill" / "SKILL.md").read_bytes() == manifest("demo-skill")


def test_manifest_without_frontmatter_is_rejected():
    with pytest.raises(skills.SkillError):
        markdown_to_archive(b"no frontmatter here")


def test_loose_files_land_beside_the_manifest(skills_root):
    archive = files_to_archive(
        [("SKILL.md", manifest("demo-skill")), ("notes.md", b"reference text")]
    )
    result = skills.import_skill_archive(archive)
    assert [skill["name"] for skill in result["imported"]] == ["demo-skill"]
    assert (skills_root / "demo-skill" / "notes.md").read_bytes() == b"reference text"


def test_folder_upload_keeps_subfolders_and_uses_manifest_name(skills_root):
    # Folder named differently from the skill: the manifest name wins.
    archive = files_to_archive(
        [
            ("my-download/SKILL.md", manifest("demo-skill")),
            ("my-download/agents/grader.md", b"grader"),
            ("unrelated/readme.txt", b"outside any skill"),
        ]
    )
    skills.import_skill_archive(archive)
    assert (skills_root / "demo-skill" / "agents" / "grader.md").read_bytes() == b"grader"
    assert not (skills_root / "unrelated").exists()
    assert not (skills_root / "my-download").exists()


def test_two_folders_import_two_skills(skills_root):
    archive = files_to_archive(
        [
            ("first/SKILL.md", manifest("first-skill")),
            ("first/a.md", b"a"),
            ("second/SKILL.md", manifest("second-skill")),
        ]
    )
    result = skills.import_skill_archive(archive)
    assert sorted(skill["name"] for skill in result["imported"]) == ["first-skill", "second-skill"]
    assert (skills_root / "first-skill" / "a.md").is_file()


@pytest.mark.parametrize(
    "items",
    [
        [],
        [("notes.md", b"no manifest")],
        [("SKILL.md", manifest("a-skill")), ("nested/SKILL.md", manifest("b-skill"))],
        [("x/SKILL.md", manifest("same-skill")), ("y/SKILL.md", manifest("same-skill"))],
        [("SKILL.md", manifest("a-skill")), ("SKILL.md", manifest("a-skill"))],
        [("SKILL.md", manifest("a-skill")), ("../escape.md", b"x")],
        [("SKILL.md", manifest("a-skill")), ("/abs/escape.md", b"x")],
        [("SKILL.md", manifest("a-skill")), ("C:\\escape.md", b"x")],
    ],
)
def test_invalid_selections_are_rejected(items):
    with pytest.raises(skills.SkillError):
        files_to_archive(items)
