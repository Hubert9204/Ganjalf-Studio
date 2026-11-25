#!/usr/bin/env python3
"""Assemble the copy-paste system prompts from sections/: core.md plus one model addendum each.

python3 studio/ganjalf_prompts/build.py          # rewrite agentic-*.md
python3 studio/ganjalf_prompts/build.py --check  # exit 1 if a file is out of date
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PARTS = HERE / "sections"
VARIANTS = {
    "agentic-generic.md": [],
    "agentic-qwen.md": ["qwen.md"],
    "agentic-nemotron.md": ["nemotron.md"],
    "agentic-gemma.md": ["gemma.md"],
}


def render(addenda: list[str]) -> str:
    pieces = [(PARTS / "core.md").read_text(encoding = "utf-8").strip()]
    pieces += [(PARTS / name).read_text(encoding = "utf-8").strip() for name in addenda]
    return "\n\n".join(pieces) + "\n"


def main() -> int:
    check = "--check" in sys.argv[1:]
    stale = []
    for target, addenda in VARIANTS.items():
        path = HERE / target
        text = render(addenda)
        if check:
            if not path.exists() or path.read_text(encoding = "utf-8") != text:
                stale.append(target)
        else:
            path.write_text(text, encoding = "utf-8")
    if stale:
        print("Out of date, run build.py: " + ", ".join(stale))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
