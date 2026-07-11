"""JLCPCB order files — the BOM/CPL builders behind ``hendley pcba``.

The manufacturing side of the pcba flow: take the extracted design
(:mod:`hendley.ingestion.fusion.live_design`) and format JLCPCB's two upload
files. Selection never happens here — DNP exclusion and grouping are the only
transformations, both driven by data already on the parts.

CPL rotation corrections
------------------------
Some library footprints are drawn with a zero-orientation that differs from
what JLC's feeders expect, so those parts need the same hand-rotation in JLC's
order preview on every submission. ``data/cpl-rotations.json`` (in the repo)
records each correction once, keyed by part identity — LCSC code or library
footprint name, never designator — and ``build_cpl_rows`` applies it:
``rotation = (angle + rotationOffsetDeg) % 360``, positive = counterclockwise
(JLC's convention).
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from ...ingestion.fusion.live_design import Placement, is_dnp, natural_key
from ...ingestion.fusion.parts_json import DesignPart

BOM_FIELDS = ("Comment", "Designator", "Footprint", "JLCPCB Part #")
CPL_FIELDS = ("Designator", "Mid X", "Mid Y", "Layer", "Rotation")
ROTATIONS_FILENAME = Path("data") / "cpl-rotations.json"


# ---------------------------------------------------------------------------
# Rotation corrections
# ---------------------------------------------------------------------------

def find_rotations_file(explicit: str | Path | None = None) -> Path | None:
    """Locate ``data/cpl-rotations.json``: explicit path, else walk up from cwd."""
    if explicit:
        return Path(explicit)
    here = Path.cwd()
    for candidate in (here, *here.parents):
        p = candidate / ROTATIONS_FILENAME
        if p.exists():
            return p
    return None


def load_rotations(path: str | Path | None = None) -> list[dict]:
    """Load rotation-correction entries; empty list when no DB is found."""
    found = find_rotations_file(path)
    if found is None:
        return []
    return json.loads(Path(found).read_text()).get("corrections", [])


def rotation_for(corrections: list[dict], jlc_code: str | None, footprint: str | None) -> dict | None:
    """Match a correction by part identity: LCSC code or library footprint name."""
    for c in corrections:
        if (jlc_code and c.get("lcsc") == jlc_code) or (footprint and c.get("footprint") == footprint):
            return c
    return None


# ---------------------------------------------------------------------------
# BOM / CPL assembly
# ---------------------------------------------------------------------------

def build_bom_rows(parts: list[DesignPart], placements: list[Placement]) -> list[dict]:
    """Group parts into JLC BOM lines by identical (comment, footprint, JLC code).

    Comment is the schematic value, falling back to the MPN. Footprint is the
    board's library package name (falling back to the PACKAGE attribute).
    Do-not-populate parts — the ``DNP`` attribute or the board's ``populate``
    flag — are left out (matching their absence from the CPL).
    """
    place_by_desig = {pl.designator: pl for pl in placements}
    groups: dict[tuple[str, str, str], list[str]] = {}
    for part in parts:
        placed = place_by_desig.get(part.designator)
        if is_dnp(part) or (placed is not None and not placed.populate):
            continue
        footprint = (placed.footprint if placed else None) or part.package or ""
        comment = (part.value or "").strip() or (part.manufacturer_part or "")
        key = (comment, footprint, part.jlc_code or "")
        groups.setdefault(key, []).append(part.designator)

    rows = [
        {
            "Comment": comment,
            "Designator": ",".join(sorted(desigs, key=natural_key)),
            "Footprint": footprint,
            "JLCPCB Part #": code,
        }
        for (comment, footprint, code), desigs in groups.items()
    ]
    rows.sort(key=lambda r: natural_key(r["Designator"].split(",")[0]))
    return rows


def build_cpl_rows(
    parts: list[DesignPart], placements: list[Placement], corrections: list[dict] | None = None
) -> tuple[list[dict], list[dict]]:
    """One CPL row per populated placement (DNP parts skipped), corrections applied.

    Returns ``(rows, applied)`` where ``applied`` records each correction that
    fired (designator, raw angle, corrected rotation, matched key) so callers
    can surface what changed.
    """
    corrections = corrections or []
    part_by_desig = {p.designator: p for p in parts}
    rows: list[dict] = []
    applied: list[dict] = []
    for pl in placements:
        part = part_by_desig.get(pl.designator)
        if not pl.populate or (part is not None and is_dnp(part)):
            continue
        rotation = pl.angle
        c = rotation_for(corrections, part.jlc_code if part else None, pl.footprint)
        if c:
            rotation = (rotation + c["rotationOffsetDeg"]) % 360
            applied.append(
                {
                    "designator": pl.designator,
                    "rawAngle": pl.angle,
                    "rotation": rotation,
                    "matched": c.get("lcsc") or c.get("footprint"),
                }
            )
        rows.append(
            {
                "Designator": pl.designator,
                "Mid X": f"{pl.x}mm",
                "Mid Y": f"{pl.y}mm",
                "Layer": "Bottom" if pl.mirror else "Top",
                "Rotation": rotation,
            }
        )
    return rows, applied


def write_csv(rows: list[dict], fields: tuple[str, ...], path: Path) -> None:
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(fields))
        writer.writeheader()
        writer.writerows(rows)
