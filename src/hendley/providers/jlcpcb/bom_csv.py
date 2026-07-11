"""Render a resolution into the JLCPCB PCBA upload BOM (CSV).

By the time this module runs, all judgment is done: the requirement lines
have been resolved (house-parts DB → live verify → approved picks) into a
*resolution JSON*. This module is a dumb, deterministic renderer of that JSON
into (a) the CSV JLCPCB's PCBA BOM upload expects — columns ``Comment,
Designator, Footprint, LCSC Part #`` — and (b) a human-readable resolution
report for traceability of what was mounted and why.

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
          "ref": "C31850",                  # provider ref ("lcsc" accepted);
                                            # null/missing = UNRESOLVED
          "source": "db",                   # db | pick | explicit (provenance)
          "dnp": false,                     # true = carried, not rendered
          "requiredQty": 50,                # optional: designators × qtyPer × N
          "note": "house part since 2026-05"  # optional, report-only
        }
      ]
    }

A populated line with no ref still renders (blank cell) so the gap is
visible, but callers must treat any unresolved line as a submission blocker —
the CLI exits nonzero so a half-resolved BOM can't slip into an upload
unnoticed. DNP lines are excluded from the CSV and are never blockers.
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from ...domain.model import CHECK_SEVERITIES

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
    ref: str | None = None  # provider ref (LCSC code); None = unresolved (blocker)
    source: str | None = None  # db | pick | explicit
    dnp: bool = False  # carried for the record; not rendered, never a blocker
    required_qty: int | None = None  # designators × qtyPer × N (report-only)
    note: str | None = None  # report-only context (why / since when)
    checks: list | None = None  # BOM Check dicts {check, severity, message}

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
        checks = d.get("checks")
        if checks is not None and not (
            isinstance(checks, list)
            and all(isinstance(c, dict) and c.get("check")
                    and c.get("severity") in CHECK_SEVERITIES
                    for c in checks)
        ):
            raise ValueError(
                f"line 'checks' must be a list of "
                f"{{check, severity: {'|'.join(CHECK_SEVERITIES)}, message}} dicts: {d!r}")
        return cls(
            designators=[str(x) for x in designators],
            comment=d.get("comment"),
            footprint=d.get("footprint"),
            ref=d.get("ref") or d.get("lcsc"),
            source=source,
            dnp=bool(d.get("dnp", False)),
            required_qty=int(required_qty) if required_qty is not None else None,
            note=d.get("note"),
            checks=checks,
        )


def load_resolution_json(
    path: str | Path,
) -> tuple[str | None, int | None, list[BomLine], dict]:
    """Load a resolution JSON file → (design, production quantity, lines, raw doc).

    The raw doc is the parsed (bare lists normalized to ``{"lines": …}``)
    document — the thing a release snapshot embeds. Returning it here means
    the snapshot records exactly the document that was validated and
    rendered, from one read.
    """
    doc = json.loads(Path(path).read_text())
    if not isinstance(doc, dict):
        doc = {"lines": doc}
    lines = doc.get("lines")
    design = doc.get("design")
    n = doc.get("productionQuantity")
    if not isinstance(lines, list):
        raise ValueError("resolution JSON must be a list, or an object with a 'lines' list")
    if n is not None and (not isinstance(n, int) or n < 1):
        raise ValueError(f"'productionQuantity' must be a positive integer, got {n!r}")
    return (str(design) if design else None), n, [BomLine.from_dict(x) for x in lines], doc


def render_bom_csv(lines: Iterable[BomLine]) -> str:
    """Render BOM lines as the JLCPCB PCBA upload CSV (DNP lines excluded)."""
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(CSV_COLUMNS)
    for line in lines:
        if line.dnp:
            continue
        writer.writerow(
            (line.comment or "", ",".join(line.designators), line.footprint or "",
             line.ref or "")
        )
    return buf.getvalue()


def unresolved_lines(lines: Iterable[BomLine]) -> list[BomLine]:
    """Populated lines with no provider ref — submission blockers."""
    return [x for x in lines if not x.ref and not x.dnp]


def error_checks(lines: Iterable[BomLine]) -> list[tuple[BomLine, dict]]:
    """Every error-severity BOM Check carried by the lines."""
    return [(x, c) for x in lines for c in (x.checks or [])
            if c.get("severity") == "error"]


def warning_checks(lines: Iterable[BomLine]) -> list[tuple[BomLine, dict]]:
    """Every warning-severity BOM Check — reported, never blocking."""
    return [(x, c) for x in lines for c in (x.checks or [])
            if c.get("severity") == "warning"]


def blocking_checks(lines: Iterable[BomLine]) -> list[tuple[BomLine, dict]]:
    """THE submission gate: every reason this BOM must not be uploaded.

    All carried error-severity checks, plus a synthesized ``unresolved``
    check for each populated line with no ref (so hand-composed JSON without
    ``checks`` blocks exactly as before, and every blocker — whatever its
    origin — surfaces in one pass with one shape). DNP lines never block.
    """
    lines = list(lines)
    blockers = error_checks(lines)
    for x in unresolved_lines(lines):
        blockers.append((x, {
            "check": "unresolved", "severity": "error",
            "message": f"{','.join(x.designators)}: no LCSC code",
        }))
    return blockers


def format_resolution_report(
    design: str | None, lines: list[BomLine], production_quantity: int | None = None
) -> str:
    """Human-readable trace of where every BOM line's part came from."""
    unresolved = unresolved_lines(lines)
    blockers = blocking_checks(lines)
    dnp = [x for x in lines if x.dnp]
    parts = sum(len(x.designators) for x in lines if not x.dnp)
    what = f"{len(lines)} line(s), {parts} part(s)/board"
    if dnp:
        what += f" ({len(dnp)} DNP line(s) excluded)"
    if production_quantity:
        what += f" × {production_quantity} board(s)"
    headline = f"BOM resolution — {what}"
    if design:
        headline = f"BOM resolution for {design} — {what}"
    headline += ("  →  READY TO UPLOAD" if not blockers
                 else f"  →  {len(blockers)} BLOCKER(S) — DO NOT UPLOAD")
    out = [headline]

    by_source = {s: sum(1 for x in lines if x.source == s) for s in LINE_SOURCES}
    tagged = ", ".join(f"{n} {s}" for s, n in by_source.items() if n)
    if tagged:
        out.append(f"Sources: {tagged}")

    errors, warnings = error_checks(lines), warning_checks(lines)
    if errors or warnings:
        out.append(f"Checks: {len(errors)} error(s), {len(warnings)} warning(s)")
        for _, c in errors:
            out.append(f"  ERROR {c['check']}: {c.get('message', '')}")
        for _, c in warnings:
            out.append(f"  warn  {c['check']}: {c.get('message', '')}")

    def fmt(line: BomLine) -> str:
        bits = [",".join(line.designators)]
        if line.comment:
            bits.append(line.comment)
        if line.footprint:
            bits.append(line.footprint)
        bits.append(line.ref or "— NO PART —")
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
    resolved = [x for x in lines if x.ref and not x.dnp]
    if resolved:
        out.append("")
        out.append(f"Resolved ({len(resolved)})")
        out.extend(fmt(x) for x in resolved)
    if dnp:
        out.append("")
        out.append(f"DNP ({len(dnp)}) — carried for the record, not uploaded")
        out.extend(f"  {','.join(x.designators)}  {x.comment or ''}" for x in dnp)
    return "\n".join(out)
