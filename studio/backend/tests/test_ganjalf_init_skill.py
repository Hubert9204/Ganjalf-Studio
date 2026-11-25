"""/init: a shipped skill the user calls by name; never picked on its own."""

from pathlib import Path

import yaml

from core.inference.skill_mentions import mentioned_skill_names
from core.inference.skill_relevance import suggest_skill_names

SKILL = Path(__file__).resolve().parents[2] / "ganjalf_skills" / "init" / "SKILL.md"


def _record():
    front = yaml.safe_load(SKILL.read_text(encoding = "utf-8").split("---")[1])
    return {**front, "valid": True, "shadowed": False, "enabled": True}


def test_init_is_called_by_slash_and_never_auto_loaded():
    record = _record()
    assert record["name"] == "init" and record["metadata"]["auto-load"] == "false"
    assert mentioned_skill_names("/init") == ["init"]
    assert suggest_skill_names("init the project and write AGENTS.md init", [record]) == []
    body = SKILL.read_text(encoding = "utf-8")
    for step in ("AGENTS.md", "edit_file", "Commands", "not checked", "run_agent"):
        assert step in body
