"""JLC stock reporting — enrichment and the inventory check.

Consumes :class:`~hendley.ingestion.fusion.parts_json.DesignPart` records and
the live JLC catalog (one batched ``getComponentDetailByCode`` call) to
classify each part's availability and render the submission-gating report.
"""

from __future__ import annotations

from typing import Iterable

from ..datasources.jlc.client import JLCClient
from ..ingestion.fusion.parts_json import DesignPart


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
