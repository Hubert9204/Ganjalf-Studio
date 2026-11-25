"""Ganjalf: model-written skills with extra files, replacing its own skill, copy_to templates."""

from __future__ import annotations

import pytest

from core.inference import skills, tools


@pytest.fixture(autouse = True)
def _reset_tool_request_budget():
    context_token = tools._REQUEST_CONTEXT_TOKENS.set(tools._UNSET_CONTEXT_TOKENS)
    budget_token = tools._REQUEST_RESULT_BUDGET.set(None)
    yield
    tools._REQUEST_CONTEXT_TOKENS.reset(context_token)
    tools._REQUEST_RESULT_BUDGET.reset(budget_token)


@pytest.fixture
def home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(skills, "studio_root", lambda: tmp_path / "studio")
    monkeypatch.setenv("HOME", str(home))
    return home


def _skill_dir(home, name):
    return home / ".agents" / "skills" / name


FILES = [
    {"path": "references/formulas.md", "content": "# Damage\npAtk * 70 / pDef\n"},
    {"path": "templates/vite.config.ts", "content": "export default { base: './' };\n"},
    {"path": "scripts/selftest.sh", "content": "#!/bin/sh\nnpx tsc --noEmit\n"},
]


def test_files_are_written_and_listed_when_reading(home):
    record = skills.create_skill(
        "mmo-demo",
        "Build a browser MMO demo.",
        "1. Copy templates/vite.config.ts.",
        files = FILES,
        model_made = True,
        home = home,
    )
    folder = _skill_dir(home, "mmo-demo")
    assert record["name"] == "mmo-demo"
    assert (folder / "references" / "formulas.md").read_text() == FILES[0]["content"]
    assert (folder / "scripts" / "selftest.sh").stat().st_mode & 0o100
    assert (folder / skills.MODEL_SKILL_MARKER).is_file()
    page = skills.read_skill_resource("mmo-demo", home = home)
    assert "[Files in this skill:" in page and "references/formulas.md" in page
    assert skills.MODEL_SKILL_MARKER not in page
    assert "pAtk" in skills.read_skill_resource("mmo-demo", "references/formulas.md", home = home)


@pytest.mark.parametrize(
    "files, message",
    [
        ([{"path": "notes.md", "content": "x"}], "must be inside one of"),
        ([{"path": "references/../SKILL.md", "content": "x"}], "stay inside"),
        ([{"path": "references/.hidden", "content": "x"}], "cannot be hidden"),
        (
            [
                {"path": "references/a.md", "content": "x"},
                {"path": "references/A.md", "content": "y"},
            ],
            "listed twice",
        ),
        (
            [
                {
                    "path": "references/a.md",
                    "content": "x" * (skills.MAX_CREATED_SKILL_FILE_BYTES + 1),
                }
            ],
            "exceeds",
        ),
        ([{"path": "references/a.md"}], "needs its text"),
        ("references/a.md", "must be a list"),
    ],
)
def test_bad_files_are_refused_and_nothing_is_written(home, files, message):
    with pytest.raises(skills.SkillError, match = message):
        skills.create_skill("bad", "Description", "Instructions", files = files, home = home)
    assert not _skill_dir(home, "bad").exists()


def test_replace_keeps_history_and_never_touches_user_skills(home):
    skills.create_skill(
        "mine", "First.", "Version one.", files = FILES[:1], model_made = True, home = home
    )
    record = skills.create_skill(
        "mine", "Second.", "Version two.", replace = True, model_made = True, home = home
    )
    folder = _skill_dir(home, "mine")
    assert record["replaced"] is True
    assert "Version two." in (folder / "SKILL.md").read_text()
    assert not (folder / "references").exists()  # the new version is complete on its own
    history = list((_skill_dir(home, "") / skills.SKILL_HISTORY_DIR).iterdir())
    assert len(history) == 1 and "Version one." in (history[0] / "SKILL.md").read_text()
    # The hidden history is not a skill.
    assert [s["name"] for s in skills.list_skills(home = home) if s["source"] == "agents"] == ["mine"]

    for _ in range(5):
        skills.create_skill("mine", "Again.", "Again.", replace = True, model_made = True, home = home)
    assert (
        len(list((_skill_dir(home, "") / skills.SKILL_HISTORY_DIR).iterdir()))
        == skills.SKILL_HISTORY_KEEP
    )

    skills.create_skill("users-own", "Made in the UI.", "Hands off.", home = home)
    with pytest.raises(skills.SkillExistsError, match = "not written with create_skill"):
        skills.create_skill(
            "users-own", "Model.", "Overwrite.", replace = True, model_made = True, home = home
        )
    assert "Hands off." in (_skill_dir(home, "users-own") / "SKILL.md").read_text()

    fresh = skills.create_skill(
        "brand-new", "New.", "New.", replace = True, model_made = True, home = home
    )
    assert fresh["replaced"] is False


def test_tool_creates_with_files_given_as_a_json_string_and_reports_them(home):
    import json

    result = tools.execute_tool(
        "create_skill",
        {
            "name": "web-game",
            "description": "Build web games.",
            "instructions": "Steps.",
            "files": json.dumps(FILES),
        },
    )
    assert "Created Agent Skill 'web-game'" in result and "with 3 extra files" in result
    again = tools.execute_tool(
        "create_skill",
        {
            "name": "web-game",
            "description": "Build web games.",
            "instructions": "Better steps.",
            "replace": True,
        },
    )
    assert "Updated Agent Skill 'web-game'" in again and ".ganjalf-skill-history" in again


def test_copy_to_writes_a_template_into_the_project_and_asks_like_edit_file(
    home, tmp_path, monkeypatch
):
    tools.execute_tool(
        "create_skill",
        {
            "name": "web-game",
            "description": "Build web games.",
            "instructions": "Steps.",
            "files": FILES,
        },
    )
    workdir = tmp_path / "project"
    workdir.mkdir()
    monkeypatch.setattr(tools, "_get_workdir", lambda *_a, **_k: str(workdir))
    monkeypatch.setattr(tools, "_edit_file_resolve", lambda path, *_a: (str(workdir / path), None))

    result = tools.execute_tool(
        "read_skill",
        {"name": "web-game", "resource": "templates/vite.config.ts", "copy_to": "vite.config.ts"},
        session_id = "s",
    )
    assert result.startswith(
        "Copied templates/vite.config.ts from skill 'web-game' to vite.config.ts"
    )
    assert (workdir / "vite.config.ts").read_text() == FILES[1]["content"]
    again = tools.execute_tool(
        "read_skill",
        {"name": "web-game", "resource": "templates/vite.config.ts", "copy_to": "vite.config.ts"},
        session_id = "s",
    )
    assert again.startswith("Error")

    assert tools.is_high_risk_tool_call("read_skill", {"name": "x", "copy_to": "a.ts"}) is True
    assert (
        tools.is_potentially_unsafe_tool_call("read_skill", {"name": "x", "copy_to": "a.ts"})
        is True
    )
    assert tools.is_high_risk_tool_call("read_skill", {"name": "x"}) is False


def test_bundled_skill_creator_teaches_procedures():
    from pathlib import Path

    text = (
        Path(skills.__file__).parent / "bundled_skills" / "skill-creator" / "SKILL.md"
    ).read_text(encoding = "utf-8")
    for needle in ("checkpoint", "Pitfalls", "copy_to", "replace: true", "files"):
        assert needle in text
    assert "Do not create scripts or reference files" not in text
