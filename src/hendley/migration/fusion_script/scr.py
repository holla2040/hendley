"""Generate Fusion Electronics command-line scripts (``.scr``) for part swaps.

The Fusion Electronics API is read-only (see :mod:`hendley.fusion`), so Hendley
cannot mutate a design directly. The one channel that *can* edit the schematic
is the EAGLE-heritage command line, driven by a ``.scr`` script the user runs
in Fusion (``File > Execute Script``, or paste into the command line). This
module turns a list of part swaps into exactly that script.

A single swap maps to the verified-working command block::

    CHANGE PACKAGE '-0402' R4;
    ATTRIBUTE R4 LCSC 'C25768';
    ATTRIBUTE R4 MANUFACTURER 'UNI-ROYAL';
    ATTRIBUTE R4 MPN '0402WGF2202TCE';

``CHANGE PACKAGE`` is emitted **before** the ``ATTRIBUTE`` lines on purpose:
switching the device/package variant can reset the variant's library-defined
attributes, so the attribute values must be written *after* the package change.

Accumulate many swaps (across a migration session, or several swap files) into
one combo script that the user executes once to apply every change at once.

Input contract (JSON), object-with-``swaps`` or a bare list::

    {
      "design": "comet",                 # optional, for the script header
      "swaps": [
        {
          "designator": "R2",            # required
          "package": "-0402",            # optional; the library variant NAME
                                         #   (note the leading hyphen) — omit to
                                         #   leave the footprint unchanged
          "lcsc": "C25768",              # convenience alias -> LCSC attribute
          "manufacturer": "UNI-ROYAL",   # alias -> MANUFACTURER
          "mpn": "0402WGF2202TCE",       # alias -> MPN
          "attributes": {"DESC": "1%"}   # any extra/explicit attrs (override)
        }
      ]
    }
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

# Convenience top-level keys -> canonical Fusion attribute names, in the order
# they should appear in the script (mirrors docs/comet-0402-migration.md).
_ALIAS_ATTRS = (("lcsc", "LCSC"), ("manufacturer", "MANUFACTURER"), ("mpn", "MPN"))

# Characters that would break an EAGLE command line or let one swap's value
# bleed into another command. The script mutates a live design, so we refuse to
# emit anything questionable rather than risk a broken/partial run.
_FORBIDDEN = set("'\";") | {chr(c) for c in range(0x00, 0x20)}


def _reject(text: str, *, what: str, allow_space: bool) -> str:
    bad = _FORBIDDEN | (set() if allow_space else set(" \t"))
    found = sorted({c for c in text if c in bad})
    if found or text == "":
        shown = "".join(repr(c) for c in found) or "(empty)"
        raise ValueError(f"invalid {what} {text!r}: contains {shown}")
    return text


def _quote(value: str) -> str:
    """Wrap a validated value in the single quotes the command line expects."""
    return f"'{value}'"


@dataclass
class PartSwap:
    """One part's worth of changes: an optional package variant + attributes."""

    designator: str  # e.g. "R2" — the trailing arg to CHANGE PACKAGE
    package: str | None = None  # library variant NAME, e.g. "-0402"; None = leave as-is
    attributes: dict[str, str] = field(default_factory=dict)  # name -> value, ordered

    @classmethod
    def from_dict(cls, d: dict) -> "PartSwap":
        if not d.get("designator"):
            raise ValueError(f"swap is missing required 'designator': {d!r}")
        attrs: dict[str, str] = {}
        for alias, name in _ALIAS_ATTRS:
            if d.get(alias) is not None:
                attrs[name] = str(d[alias])
        for k, v in (d.get("attributes") or {}).items():  # explicit wins, keeps order
            if v is not None:
                attrs[str(k)] = str(v)
        pkg = d.get("package") or d.get("variant")
        return cls(
            designator=str(d["designator"]),
            package=(str(pkg) if pkg else None),
            attributes=attrs,
        )

    def render(self) -> list[str]:
        """Render this swap to command-line statements (validated)."""
        ref = _reject(self.designator, what="designator", allow_space=False)
        lines: list[str] = []
        if self.package:
            pkg = _reject(self.package, what="package variant", allow_space=True)
            lines.append(f"CHANGE PACKAGE {_quote(pkg)} {ref};")
        for name, value in self.attributes.items():
            attr = _reject(name, what="attribute name", allow_space=False)
            val = _reject(value, what=f"value for {name}", allow_space=True)
            lines.append(f"ATTRIBUTE {ref} {attr} {_quote(val)};")
        if not lines:
            raise ValueError(f"swap for {ref!r} changes nothing (no package and no attributes)")
        return lines


def load_swaps_json(path: str | Path) -> list[PartSwap]:
    """Load a swaps JSON file (object-with-``swaps`` or bare list) into PartSwaps."""
    doc = json.loads(Path(path).read_text())
    swaps = doc.get("swaps") if isinstance(doc, dict) else doc
    if not isinstance(swaps, list):
        raise ValueError("swaps JSON must be a list, or an object with a 'swaps' list")
    return [PartSwap.from_dict(s) for s in swaps]


def render_script(swaps: Iterable[PartSwap], design: str | None = None) -> str:
    """Render swaps into one ``.scr`` script ready to run in Fusion's command line."""
    swaps = list(swaps)
    header = [
        "# Hendley-generated Fusion Electronics migration script (.scr)",
        "# Run in the schematic: File > Execute Script  (or paste into the command line).",
        "# CHANGE PACKAGE precedes ATTRIBUTE per part: switching the variant can reset",
        "# variant-default attributes, so attribute values are written afterward.",
    ]
    if design:
        header.append(f"# Design: {design}")
    header.append(f"# Parts: {len(swaps)}")

    blocks = [header, []]  # blank line after header
    for swap in swaps:
        blocks.append(swap.render())
    body = "\n".join("\n".join(block) for block in blocks).rstrip("\n")
    return body + "\n"
