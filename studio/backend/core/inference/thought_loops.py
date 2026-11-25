"""Ganjalf: a thought going in circles, caught while it streams.

Local models under an agent loop sometimes repeat the same few sentences for minutes ("Actually,
I think the issue might be ... This should work. ... OK, I'm going in circles.") until the
thinking budget runs out: at 12 tokens a second that was 8-9 minutes per round in a Qwen3.6
35B-A3B session, three times in one task. The tool loop cuts such a thought as if the window had
ended it, keeps what was new in it, and asks the model to act.
"""

from __future__ import annotations

import re

# How much new reasoning arrives between two checks (the check is cheap, the stream is not).
CHECK_EVERY_CHARS = 1500
# A sentence this long that comes back this often is a loop, not a recap.
MIN_SENTENCE_CHARS = 40
MIN_REPEATS = 4
# And the repeats must be a real share of the thought, not one phrase in a long one.
MIN_REPEATED_SHARE = 0.25
_PROGRESS_CHARS = 700

_SPLIT = re.compile(r"(?<=[.!?:])\s+|\n+")
_SPACES = re.compile(r"\s+")


def _sentences(text: str) -> list[str]:
    return [
        _SPACES.sub(" ", part).strip() for part in _SPLIT.split(text or "") if part and part.strip()
    ]


def _key(sentence: str) -> str:
    return sentence.lower().rstrip(".!?:")


def is_looping(reasoning: str) -> bool:
    """Whether the thought repeats the same long sentences over and over."""
    sentences = [s for s in _sentences(reasoning) if len(s) >= MIN_SENTENCE_CHARS]
    if len(sentences) < MIN_REPEATS * 2:
        return False
    counts: dict[str, int] = {}
    for sentence in sentences:
        key = _key(sentence)
        counts[key] = counts.get(key, 0) + 1
    if max(counts.values()) < MIN_REPEATS:
        return False
    repeated = sum(len(key) * (n - 1) for key, n in counts.items() if n >= 2)
    total = sum(len(s) for s in sentences)
    return total > 0 and repeated / total >= MIN_REPEATED_SHARE


def loop_progress(reasoning: str) -> str:
    """What the thought had, each sentence once, for the note that stands in for it."""
    seen: set[str] = set()
    kept: list[str] = []
    for sentence in _sentences(reasoning):
        key = _key(sentence)
        if key in seen:
            continue
        seen.add(key)
        kept.append(sentence)
    text = " ".join(kept)
    if len(text) > _PROGRESS_CHARS:
        text = "… " + text[-_PROGRESS_CHARS:].lstrip()
    return f"Where I had got to (my thinking was repeating itself, so it was stopped):\n{text}"


def loop_message() -> str:
    """The user turn after a cut loop: act on evidence, do not think the same thing again."""
    return (
        "Your thinking was going in circles (the same sentences over and over), so it was "
        "stopped. Do not reason about it again from memory. Act now with a tool that gives you "
        "new facts: read the code you suspect, run the check again, or add a console.log / print "
        "at the suspected spot and run it. If you already know the fix, make it."
    )
