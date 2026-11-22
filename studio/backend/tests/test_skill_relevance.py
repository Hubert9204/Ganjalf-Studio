# SPDX-License-Identifier: AGPL-3.0-only
# Copyright 2026-present the Unsloth AI Inc. team. All rights reserved. See /studio/LICENSE.AGPL-3.0

"""Choosing the skill that fits a request, so a small local model does not have to."""

import pytest

from core.inference import skill_relevance as relevance
from core.inference.skill_relevance import suggest_skill_names


def rec(name, description, **extra):
    return {
        "name": name,
        "description": description,
        "valid": True,
        "shadowed": False,
        "enabled": True,
        **extra,
    }


CODING = (
    "Work on code in a project folder. Explore files, read large files in chunks, fix bugs and "
    "compile errors, edit source code, build, run programs and verify the result. Use for "
    "debugging, programming, scripts, refactoring, crashes and broken builds. Italiano - codice, "
    "programma, errore, bug, correggere, compilare, progetto, file di sorgente."
)
OPENGL_BUG = "fix the OpenGL rendering bug in src/render.c, the program shows only a diagonal line"
SKILLS = [
    rec("coding-agent", CODING),
    rec("deep-research", "Conduct multi-source web research and write a long cited report on a topic."),
    rec(
        "morning",
        "Render the user's morning brief as a styled HTML artifact, or set it up as a recurring weekday task.",
    ),
    rec(
        "import-memory",
        "Import a memory export from another AI assistant into the assistant's memory.",
    ),
    rec(
        "image-prompting",
        "Write detailed prompts for image generation models, with style, lighting and composition.",
    ),
]


@pytest.mark.parametrize(
    "request_text, expected",
    [
        (OPENGL_BUG, ["coding-agent"]),
        ("correggi il bug nel codice del programma, non compila", ["coding-agent"]),
        ("Write a long cited report researching the history of tokenization", ["deep-research"]),
        ("do some deep research on GPUs", ["deep-research"]),
        ("ok continua", []),
        ("what is the weather today", []),
        ("write me a poem about the sea", []),
        ("create a document with the meeting notes", []),
        ("", []),
    ],
)
def test_picks_the_skill_that_fits(request_text, expected):
    assert suggest_skill_names(request_text, SKILLS) == expected


def test_explicit_mentions_are_not_suggested_again():
    assert suggest_skill_names(OPENGL_BUG, SKILLS, exclude = ["coding-agent"]) == []


def test_disabled_shadowed_and_invalid_skills_are_ignored():
    for change in ({"enabled": False}, {"shadowed": True}, {"valid": False}):
        skills = [rec("coding-agent", CODING, **change), *SKILLS[1:]]
        assert suggest_skill_names(OPENGL_BUG, skills) == []


def test_a_skill_can_opt_out():
    skills = [rec("coding-agent", CODING, metadata = {"auto-load": "false"}), *SKILLS[1:]]
    assert suggest_skill_names(OPENGL_BUG, skills) == []


def test_two_equally_good_skills_load_nothing():
    skills = [*SKILLS, rec("coding-helper", CODING)]
    assert suggest_skill_names(OPENGL_BUG, skills) == []


def test_switch_off(monkeypatch):
    monkeypatch.setattr(relevance, "AUTO_SKILLS_ENABLED", False)
    assert suggest_skill_names("do some deep research on GPUs", SKILLS) == []


def test_a_lone_skill_still_matches_a_clear_request():
    assert suggest_skill_names(OPENGL_BUG, [rec("coding-agent", CODING)]) == ["coding-agent"]
