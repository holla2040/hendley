"""Fusion Electronics integration (read-only) — design-direct part extraction.

Hendley pulls part information **directly from Autodesk Fusion** via the Fusion
API rather than from an exported BOM. The Fusion Electronics API is currently
read-only, which is sufficient for our purpose: enumerate the components placed
in an electronics design, read their part attributes (manufacturer part number
and/or LCSC/JLC code), and hand those identifiers to Hendley's JLC query layer
to report availability, stock, price tiers, and assembly (basic/extended)
status before a PCBA order is submitted.

Runtime note
------------
The Fusion API (``adsk.core`` / ``adsk.fusion``) is only importable inside
Fusion 360's embedded Python, so the live extraction runs as a Fusion add-in /
script — not in this standalone package's interpreter. This module therefore
defines the data contract and the (Fusion-side) extraction entry point; the
JLC-side enrichment lives in :mod:`hendley.reporting.stock` and runs anywhere.

Planned flow
------------
1. (Inside Fusion) ``extract_components()`` walks the active electronics design
   and yields :class:`DesignPart` records (designator, MPN, LCSC code, qty).
2. (Anywhere) :func:`hendley.reporting.stock.enrich_with_jlc` batches the
   LCSC/JLC codes through ``JLCClient.get_component_detail_by_code`` and merges
   the stock/price/availability back onto each part.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Data contract — the JSON the Fusion side (hendrix) produces and Hendley reads.
#
#   {
#     "source": "fusion-electronics",
#     "schemaVersion": 1,
#     "design": "<active document name>",
#     "generatedAt": "<ISO-8601, optional>",
#     "parts": [
#       {
#         "designator": "R1",            # required
#         "manufacturerPart": "RC0402FR-0710KL",  # optional (MPN)
#         "jlcCode": "C25744",           # optional (JLC/LCSC 'Cxxxx' code)
#         "value": "10k",                # optional
#         "package": "0402",             # optional
#         "quantity": 1,                 # optional, default 1
#         "attributes": { ... }          # optional raw Fusion attributes
#       }
#     ]
#   }
#
# Only "designator" is strictly required per part. "jlcCode" is what JLC
# enrichment keys on; parts without it are passed through as found=false.
# ---------------------------------------------------------------------------

SCHEMA_VERSION = 1


@dataclass
class DesignPart:
    """A component instance read from a Fusion Electronics design."""

    designator: str  # e.g. "R1", "U3"
    manufacturer_part: str | None = None  # MPN, if set on the part
    jlc_code: str | None = None  # JLC/LCSC code (e.g. "C2040"), if set
    quantity: int = 1
    value: str | None = None
    package: str | None = None  # the PACKAGE *attribute* — often a placeholder
    # The library FOOTPRINT the device actually carries, read schematic-side by
    # joining electronics.Device → electronics.Package. Distinct from `package`
    # above (a library-authored attribute string, frequently absent or "Package ").
    footprint: str | None = None  # e.g. "SO16", "SOIC127P1032X265-16N"
    # …and the footprint's own GEOMETRY, which is the only honest narrow-vs-wide
    # discriminator. "SO16" is a local name that means nothing; its headline says
    # "Small Outline package 150 mil", and SOIC127P1032X265-16N's says "10.30 X
    # 7.50" — a 300-mil body. Without this a ULN2003 in SO16 is a coin-flip
    # between SOIC-16 (3.9mm) and SO-16-208mil, and they are different parts.
    footprint_headline: str | None = None
    library_identity: dict | None = None
    attributes: dict[str, str] = field(default_factory=dict)  # raw Fusion attrs

    @classmethod
    def from_dict(cls, d: dict) -> "DesignPart":
        if not d.get("designator"):
            raise ValueError(f"part is missing required 'designator': {d!r}")
        return cls(
            designator=str(d["designator"]),
            manufacturer_part=d.get("manufacturerPart") or d.get("mpn"),
            jlc_code=d.get("jlcCode") or d.get("lcsc"),
            quantity=int(d.get("quantity", 1) or 1),
            value=d.get("value"),
            package=d.get("package"),
            footprint=d.get("footprint"),
            footprint_headline=d.get("footprintHeadline"),
            library_identity=(dict(d["libraryIdentity"])
                              if isinstance(d.get("libraryIdentity"), dict) else None),
            attributes=dict(d.get("attributes") or {}),
        )


def load_parts_json(path: str | Path) -> list[DesignPart]:
    """Load a Fusion parts-export JSON file into :class:`DesignPart` records."""
    doc = json.loads(Path(path).read_text())
    parts = doc.get("parts") if isinstance(doc, dict) else doc
    if not isinstance(parts, list):
        raise ValueError("parts JSON must be a list, or an object with a 'parts' list")
    return [DesignPart.from_dict(p) for p in parts]


def extract_components(design=None) -> list[DesignPart]:  # pragma: no cover - Fusion-only
    """Enumerate components from the active Fusion electronics design.

    Implemented as a Fusion add-in: uses ``adsk.fusion`` to walk the schematic /
    PCB and read each component's part attributes. Raises here because the
    Fusion API is unavailable outside Fusion 360's embedded interpreter.
    """
    raise NotImplementedError(
        "extract_components() runs inside Fusion 360 (adsk.fusion). "
        "See the Fusion add-in entry point; this package consumes its output."
    )
