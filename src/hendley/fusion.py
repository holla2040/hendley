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
JLC-side enrichment below is plain Python and runs anywhere.

Planned flow
------------
1. (Inside Fusion) ``extract_components()`` walks the active electronics design
   and yields :class:`DesignPart` records (designator, MPN, LCSC code, qty).
2. (Anywhere) ``enrich_with_jlc()`` batches the LCSC/JLC codes through
   :meth:`hendley.client.JLCClient.get_component_detail_by_code` and merges the
   stock/price/availability back onto each part.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from .client import JLCClient

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
    package: str | None = None
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


def enrich_with_jlc(parts: Iterable[DesignPart], client: JLCClient | None = None) -> list[dict]:
    """Look up JLC stock/price/availability for parts that carry a JLC code."""
    client = client or JLCClient()
    parts = list(parts)
    codes = sorted({p.jlc_code for p in parts if p.jlc_code})
    details = {d.get("componentCode"): d for d in (client.get_component_detail_by_code(codes) or [])} if codes else {}

    enriched: list[dict] = []
    for p in parts:
        detail = details.get(p.jlc_code)
        enriched.append(
            {
                "designator": p.designator,
                "manufacturerPart": p.manufacturer_part,
                "jlcCode": p.jlc_code,
                "quantity": p.quantity,
                "found": detail is not None,
                "stockCount": (detail or {}).get("stockCount"),
                "libraryType": (detail or {}).get("libraryType"),
                "priceRanges": (detail or {}).get("priceRanges"),
                "datasheetUrl": (detail or {}).get("datasheetUrl"),
            }
        )
    return enriched


# Stock-status classification used by the inventory check. Ordered worst → best.
STOCK_STATUSES = ("out", "not_found", "no_code", "low", "ok")
# Statuses that should block a board submission (a real catalog stock problem).
STOCK_BLOCKERS = ("out", "not_found")


def check_stock(
    parts: Iterable[DesignPart], client: JLCClient | None = None, min_stock: int = 1
) -> list[dict]:
    """Classify each part's availability against the JLC catalog.

    Looks up live stock via :func:`enrich_with_jlc` (one batched
    ``getComponentDetailByCode`` call) and tags each part with a ``status``:

    - ``out`` — code found but ``stockCount`` is 0
    - ``low`` — in stock but below ``min_stock`` (default 1 ⇒ no low band)
    - ``not_found`` — has a JLC code, but the catalog doesn't return it
    - ``no_code`` — the part carries no JLC code, so it can't be checked
    - ``ok`` — in stock at or above ``min_stock``
    """
    parts = list(parts)
    enriched = enrich_with_jlc(parts, client)  # order-preserving, 1:1 with parts
    rows: list[dict] = []
    for p, e in zip(parts, enriched):
        stock = e["stockCount"]
        if not p.jlc_code:
            status = "no_code"
        elif not e["found"]:
            status = "not_found"
        elif (stock or 0) <= 0:
            status = "out"
        elif (stock or 0) < min_stock:
            status = "low"
        else:
            status = "ok"
        rows.append(
            {
                "designator": p.designator,
                "jlcCode": p.jlc_code,
                "value": p.value,
                "package": p.package,
                "quantity": p.quantity,
                "stockCount": stock,
                "libraryType": e["libraryType"],
                "status": status,
            }
        )
    return rows


def format_stock_report(rows: list[dict], min_stock: int = 1) -> str:
    """Render :func:`check_stock` rows as a grouped, human-readable report."""
    groups: dict[str, list[dict]] = {s: [] for s in STOCK_STATUSES}
    for r in rows:
        groups[r["status"]].append(r)

    coded = sum(1 for r in rows if r["jlcCode"])
    blockers = sum(len(groups[s]) for s in STOCK_BLOCKERS)
    headline = f"Inventory check — {len(rows)} part(s), {coded} with JLC codes"
    headline += "  →  ALL OK" if blockers == 0 else f"  →  {blockers} blocker(s)"
    lines = [headline]

    def fmt(r: dict) -> str:
        bits = [r["designator"]]
        for key in ("jlcCode", "value", "package"):
            if r.get(key):
                bits.append(str(r[key]))
        sc = r["stockCount"]
        stock = f"stock {sc}" if sc is not None else "stock —"
        lib = f", {r['libraryType']}" if r["libraryType"] else ""
        return f"  {' '.join(bits)}  ({stock}{lib}, qty {r['quantity']})"

    labels = (
        ("out", "OUT OF STOCK"),
        ("not_found", "NOT FOUND in JLC catalog"),
        ("no_code", "NO JLC CODE (uncheckable)"),
        ("low", f"LOW (< {min_stock})"),
        ("ok", "In stock"),
    )
    for key, label in labels:
        g = groups[key]
        if g:
            lines.append("")
            lines.append(f"{label} ({len(g)})")
            lines.extend(fmt(r) for r in g)
    return "\n".join(lines)
