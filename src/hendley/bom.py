"""Render an agent-composed resolution into the JLCPCB PCBA upload BOM (CSV).

By the time this module runs, all judgment is done: the agent has interpreted
each design part's spec, resolved it (house-parts DB → live verify → alternates
pick), and composed a *resolution JSON*. This module is a dumb, deterministic
renderer of that JSON into (a) the CSV JLCPCB's PCBA BOM upload expects —
columns ``Comment, Designator, Footprint, LCSC Part #`` — and (b) a
human-readable resolution report for traceability of what was mounted and why.

Input contract (JSON), object-with-``lines`` or a bare list — the output of
``hendley resolve`` satisfies it directly::

    {
      "design": "comet",                    # optional, for the report header
      "productionQuantity": 25,             # optional, boards built (report-only)
      "lines": [
        {
          "designators": ["R1", "R4"],      # required, non-empty
          "comment": "22k",                 # value/description column
          "footprint": "0603",              # footprint column
          "lcsc": "C31850",                 # LCSC code; null/missing = UNRESOLVED
          "source": "db",                   # db | pick | explicit (provenance)
          "requiredQty": 50,                # optional: designators × qtyPer × N
          "note": "house part since 2026-05"  # optional, report-only
        }
      ]
    }

A line with no ``lcsc`` still renders (blank cell) so the gap is visible, but
callers must treat any unresolved line as a submission blocker — the CLI exits
nonzero so a half-resolved BOM can't slip into an upload unnoticed.
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

# JLCPCB PCBA BOM upload header, in their documented column order.
CSV_COLUMNS = ("Comment", "Designator", "Footprint", "LCSC Part #")

# Provenance labels: where each line's part came from.
LINE_SOURCES = ("db", "pick", "explicit")


@dataclass
class BomLine:
    """One BOM row: a group of designators mounting the same part."""

    designators: list[str]  # e.g. ["R1", "R4"] — required, non-empty
    comment: str | None = None  # the value/description column, e.g. "22k"
    footprint: str | None = None  # e.g. "0603"
    lcsc: str | None = None  # LCSC code; None = unresolved (blocker)
    source: str | None = None  # db | pick | explicit
    required_qty: int | None = None  # designators × qtyPer × N (report-only)
    note: str | None = None  # report-only context (why / since when)

    @classmethod
    def from_dict(cls, d: dict) -> "BomLine":
        designators = d.get("designators")
        if not isinstance(designators, list) or not designators:
            raise ValueError(f"line is missing required non-empty 'designators': {d!r}")
        source = d.get("source")
        if source is not None and source not in LINE_SOURCES:
            raise ValueError(
                f"line source {source!r} not one of {LINE_SOURCES}: {d!r}"
            )
        required_qty = d.get("requiredQty")
        return cls(
            designators=[str(x) for x in designators],
            comment=d.get("comment"),
            footprint=d.get("footprint"),
            lcsc=d.get("lcsc"),
            source=source,
            required_qty=int(required_qty) if required_qty is not None else None,
            note=d.get("note"),
        )


def load_resolution_json(
    path: str | Path,
) -> tuple[str | None, int | None, list[BomLine]]:
    """Load a resolution JSON file → (design name, production quantity, BOM lines)."""
    doc = json.loads(Path(path).read_text())
    lines = doc.get("lines") if isinstance(doc, dict) else doc
    design = doc.get("design") if isinstance(doc, dict) else None
    n = doc.get("productionQuantity") if isinstance(doc, dict) else None
    if not isinstance(lines, list):
        raise ValueError("resolution JSON must be a list, or an object with a 'lines' list")
    if n is not None and (not isinstance(n, int) or n < 1):
        raise ValueError(f"'productionQuantity' must be a positive integer, got {n!r}")
    return (str(design) if design else None), n, [BomLine.from_dict(x) for x in lines]


def render_bom_csv(lines: Iterable[BomLine]) -> str:
    """Render BOM lines as the JLCPCB PCBA upload CSV."""
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(CSV_COLUMNS)
    for line in lines:
        writer.writerow(
            (line.comment or "", ",".join(line.designators), line.footprint or "",
             line.lcsc or "")
        )
    return buf.getvalue()


def unresolved_lines(lines: Iterable[BomLine]) -> list[BomLine]:
    """Lines with no LCSC code — submission blockers."""
    return [x for x in lines if not x.lcsc]


def format_resolution_report(
    design: str | None, lines: list[BomLine], production_quantity: int | None = None
) -> str:
    """Human-readable trace of where every BOM line's part came from."""
    unresolved = unresolved_lines(lines)
    parts = sum(len(x.designators) for x in lines)
    what = f"{len(lines)} line(s), {parts} part(s)/board"
    if production_quantity:
        what += f" × {production_quantity} board(s)"
    headline = f"BOM resolution — {what}"
    if design:
        headline = f"BOM resolution for {design} — {what}"
    headline += "  →  ALL RESOLVED" if not unresolved else f"  →  {len(unresolved)} UNRESOLVED"
    out = [headline]

    by_source = {s: sum(1 for x in lines if x.source == s) for s in LINE_SOURCES}
    tagged = ", ".join(f"{n} {s}" for s, n in by_source.items() if n)
    if tagged:
        out.append(f"Sources: {tagged}")

    def fmt(line: BomLine) -> str:
        bits = [",".join(line.designators)]
        if line.comment:
            bits.append(line.comment)
        if line.footprint:
            bits.append(line.footprint)
        bits.append(line.lcsc or "— NO PART —")
        if line.required_qty is not None:
            bits.append(f"need {line.required_qty}")
        tail = []
        if line.source:
            tail.append(line.source)
        if line.note:
            tail.append(line.note)
        return f"  {'  '.join(bits)}" + (f"  ({'; '.join(tail)})" if tail else "")

    if unresolved:
        out.append("")
        out.append(f"UNRESOLVED ({len(unresolved)}) — do not upload until fixed")
        out.extend(fmt(x) for x in unresolved)
    resolved = [x for x in lines if x.lcsc]
    if resolved:
        out.append("")
        out.append(f"Resolved ({len(resolved)})")
        out.extend(fmt(x) for x in resolved)
    return "\n".join(out)
