# SPDX-License-Identifier: AGPL-3.0-only
# Copyright 2026-present the Unsloth AI Inc. team. All rights reserved. See /studio/LICENSE.AGPL-3.0

"""The skills shipped in studio/ganjalf_skills must each win their own requests and not steal the others'."""

from pathlib import Path

import pytest
import yaml

from core.inference.skill_relevance import suggest_skill_names

STUDIO = Path(__file__).resolve().parents[2]
SKILL_FILES = sorted((STUDIO / "ganjalf_skills").glob("*/SKILL.md")) + sorted(
    (STUDIO / "backend" / "core" / "inference" / "bundled_skills").glob("*/SKILL.md")
)


def _record(path: Path) -> dict:
    front = yaml.safe_load(path.read_text(encoding = "utf-8").split("---")[1])
    return {
        "name": front["name"],
        "description": front["description"],
        "metadata": front.get("metadata"),
        "valid": True,
        "shadowed": False,
        "enabled": True,
    }


SKILLS = [_record(path) for path in SKILL_FILES]


def test_every_shipped_skill_is_named_after_its_folder():
    for path, skill in zip(SKILL_FILES, SKILLS):
        assert skill["name"] == path.parent.name


@pytest.mark.parametrize(
    "request_text, expected",
    [
        (
            "fix the OpenGL rendering bug in src/render.c, the program shows only a diagonal line",
            ["coding-agent"],
        ),
        (
            "creami un gioco in stile tekken 3. lavora nella cartella di lavoro del progetto",
            ["coding-agent"],
        ),
        ("correggi il bug nel codice del programma, non compila", ["coding-agent"]),
        # Fits both coding-agent and data-analysis about equally, so nothing loads on its own.
        ("scrivi uno script python che legge un csv e lo converte in json", []),
        ("cerca online le ultime notizie su Qwen 3.8 e dimmi le fonti", ["web-research"]),
        ("qual è il prezzo aggiornato oggi della RTX 5090? cerca su internet", ["web-research"]),
        (
            "verifica se è vero che è uscito llama.cpp con supporto MTP, cerca le fonti",
            ["web-research"],
        ),
        (
            "analizza il file vendite.csv e dimmi il totale e la media per regione",
            ["data-analysis"],
        ),
        (
            "ho un foglio di calcolo excel con le spese, fammi un grafico dell'andamento mensile",
            ["data-analysis"],
        ),
        ("load sales.xlsx and compute averages per column, then plot the trend", ["data-analysis"]),
        ("ok continua", []),
        ("ciao come stai", []),
    ],
)
def test_shipped_skills_route_requests(request_text, expected):
    assert suggest_skill_names(request_text, SKILLS) == expected
