"""What this shop knows about a class of part — read into the agent's prompt.

There is no one way to search for a part. A resistor's ``resistance`` column has
the same name as the catalog's ``Resistance``, so asking for both spells "10000
= 10kΩ" and rejects every part alive; an electrolytic hides its can dimensions
inside the package string; a diode's family — small-signal, Schottky, zener,
avalanche — is something the index cannot tell you at all. Every class has its
own traps, and the cost of not knowing one is a search that returns the wrong
parts, or none, while looking like it worked.

That knowledge does not belong in Python (ADR-0006: Python composes nothing and
judges nothing) and it does not belong buried in a prompt string. It belongs in
``docs/parts/`` — one markdown note per class, written by whoever learned it,
read by the agent the moment it opens a part of that class.

A note opens with a fenced ``applies-to`` block naming the CATALOG's own class
strings::

    ```applies-to
    catalogType: Aluminum Electrolytic Capacitors - SMD
    catalogType: Aluminum Electrolytic Capacitors - Leaded
    category: capacitors
    ```

``catalogType`` is ``secondTypeName`` from the live catalog record — the only
honest name for what a part IS. ``category`` is the jlcsearch slug, and matches
only when there is no catalog record to key on (a part the schematic never
pinned). Everything after the block is the note, handed to the agent verbatim.

**No note is not a failure.** A class nobody has written up yet simply gets no
special knowledge, and the agent stays conservative. Never invent one.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

FENCE = re.compile(r"^```applies-to\s*$(.*?)^```\s*$", re.S | re.M)


def notes_dir() -> Path | None:
    """``HENDLEY_PART_NOTES`` → ``docs/parts`` beside the source → nothing."""
    env = os.environ.get("HENDLEY_PART_NOTES")
    if env:
        got = Path(env).expanduser()
        return got if got.is_dir() else None
    here = Path(__file__).resolve()
    for parent in here.parents:
        got = parent / "docs" / "parts"
        if got.is_dir():
            return got
    return None


def _applies_to(text: str) -> tuple[dict[str, list[str]], str]:
    """Split a note into its ``applies-to`` keys and its body."""
    m = FENCE.search(text)
    if not m:
        return {}, text
    keys: dict[str, list[str]] = {}
    for line in m.group(1).splitlines():
        key, _, value = line.partition(":")
        key, value = key.strip(), value.strip()
        if key and value:
            keys.setdefault(key, []).append(value)
    return keys, (text[: m.start()] + text[m.end():]).strip()


def _hit(values: list[str], want: str) -> bool:
    return any(v.strip().casefold() == want.strip().casefold() for v in values)


def note_for(second_type: str | None = None,
             category: str | None = None) -> str | None:
    """The note for this part class, or None if nobody has written one.

    The CATALOG's class wins: it is the only thing that knows a TVS from a
    zener. A category slug matches only when there is no catalog record —
    a part the schematic never pinned — because a slug is far coarser (every
    capacitor, electrolytic or not, is "capacitors").
    """
    directory = notes_dir()
    if not directory:
        return None
    weak: str | None = None
    for path in sorted(directory.glob("*.md")):
        if path.name.lower() == "readme.md":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        keys, body = _applies_to(text)
        if not body:
            continue
        if second_type and _hit(keys.get("catalogType", []), second_type):
            return body
        if not second_type and category and _hit(keys.get("category", []),
                                                 category):
            weak = weak or body
    return weak
