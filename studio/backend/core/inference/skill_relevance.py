# SPDX-License-Identifier: AGPL-3.0-only
# Copyright 2026-present the Unsloth AI Inc. team. All rights reserved. See /studio/LICENSE.AGPL-3.0

"""Picks the enabled skills that fit a request, so a small local model does not have to.

Local models often skip read_skill or open an unrelated skill. This scores each skill's name and
description against the request by plain term overlap (no model, no network) and names at most a
few; the caller loads them the way it loads an explicit @mention.

Environment: GANJALF_AUTO_SKILLS=0 turns it off, GANJALF_AUTO_SKILLS_MAX sets how many load at
once (default 1). A skill opts out with `metadata: {auto-load: "false"}` in its frontmatter.
"""

from __future__ import annotations

import math
import os
import re
from typing import Iterable, Mapping, Sequence


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


AUTO_SKILLS_ENABLED = os.environ.get("GANJALF_AUTO_SKILLS", "1").strip().lower() not in {
    "0",
    "false",
    "off",
    "no",
}
MAX_AUTO_SKILLS = max(0, _env_int("GANJALF_AUTO_SKILLS_MAX", 1))
# Three distinct shared terms and a weighted score: one generic word ("write") never selects a skill.
MIN_MATCHED_TERMS = 3
MIN_SCORE = 4.5
NAME_TERM_BOOST = 1.5
# A multi-word skill name said outright ("deep research") selects it on its own.
NAME_PHRASE_BONUS = 6.0
# The top skill must lead the runner-up by this factor, or the request is ambiguous and nothing loads.
LEAD_FACTOR = 1.25

_TERM = re.compile(r"[^\W_]+")
_FALSE_VALUES = frozenset({"0", "false", "off", "no"})

# English and Italian filler: words that say nothing about the subject of a request.
_STOPWORDS = frozenset(
    """
the and for with from that this these those have has had are was were been being not but can could
will would should may might shall into onto over under about after before then than there their
they them what when where which while who whom whose why how you your yours our ours his her its
any all some one two just only also very more most much many such each other another same too
please want need make get let use using used like help show tell give take put set run does did
done out off again further once here both few own nor per via
che per con una uno non del della delle dello dei degli gli nel nella nelle nello sul sulla sulle
sono come alla alle allo dal dalla dalle dallo questo questa questi queste quello quella quelli
quelle fare fai fatto puoi puo posso voglio vorrei solo anche molto piu poi quando dove perche
cosa cose essere stato stata sono sei siamo siete mio mia miei mie tuo tua tuoi tue suo sua suoi
sue noi voi loro ogni tutto tutti tutte ciao grazie favore
""".split()
)


def _terms(text: str) -> set[str]:
    """Lower-cased words of 3+ letters without filler, plural 's' dropped and cut to six letters.

    The cut is a cheap stemmer: generate, generating and generation all become 'genera'.
    """
    found: set[str] = set()
    for word in _TERM.findall((text or "").lower()):
        if len(word) < 3 or word in _STOPWORDS:
            continue
        if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
            word = word[:-1]
        found.add(word[:6])
    return found


def _usable(skill: Mapping) -> bool:
    return bool(skill.get("valid")) and not skill.get("shadowed") and bool(skill.get("enabled"))


def _auto_allowed(skill: Mapping) -> bool:
    metadata = skill.get("metadata") or {}
    return str(metadata.get("auto-load", "true")).strip().lower() not in _FALSE_VALUES


def suggest_skill_names(
    request: str,
    skills: Sequence[Mapping],
    *,
    exclude: Iterable[str] = (),
) -> list[str]:
    """Names of the usable skills that clearly fit ``request``; usually none, rarely more than one.

    Terms shared by every skill count less than terms only one skill uses, so the score reflects
    what sets a skill apart. Nothing is returned when two skills fit about equally.
    """
    if not AUTO_SKILLS_ENABLED or MAX_AUTO_SKILLS <= 0:
        return []
    wanted = _terms(request)
    if not wanted:
        return []
    usable = [skill for skill in skills if _usable(skill)]
    if not usable:
        return []

    profiles = []
    document_frequency: dict[str, int] = {}
    for skill in usable:
        name_terms = _terms(str(skill["name"]).replace("-", " "))
        terms = name_terms | _terms(str(skill.get("description", "")))
        profiles.append((skill, name_terms, terms))
        for term in terms:
            document_frequency[term] = document_frequency.get(term, 0) + 1

    total = len(usable)
    skipped = set(exclude)
    scored: list[tuple[float, str]] = []
    for skill, name_terms, terms in profiles:
        if skill["name"] in skipped or not _auto_allowed(skill):
            continue
        matched = wanted & terms
        score = sum(
            (1.0 + math.log(total / document_frequency[term]))
            * (NAME_TERM_BOOST if term in name_terms else 1.0)
            for term in matched
        )
        phrase = len(name_terms) >= 2 and name_terms <= wanted
        if phrase:
            score += NAME_PHRASE_BONUS
        if (len(matched) >= MIN_MATCHED_TERMS or phrase) and score >= MIN_SCORE:
            scored.append((score, str(skill["name"])))
    if not scored:
        return []

    scored.sort(key = lambda item: (-item[0], item[1]))
    top_score = scored[0][0]
    if MAX_AUTO_SKILLS == 1:
        if len(scored) > 1 and scored[1][0] * LEAD_FACTOR > top_score:
            return []
        return [scored[0][1]]
    return [name for score, name in scored if score >= top_score * 0.5][:MAX_AUTO_SKILLS]
