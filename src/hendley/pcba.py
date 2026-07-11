"""JLCPCB PCBA order files (BOM + CPL) — generated live from the open Fusion design.

The one-prompt flow behind ``hendley pcba``: read the schematic over the HTTP
bridge (parts + attributes), switch the electronics engine's current drawing to
the board (``BOARD;`` — one-way; the schematic must be read *first*), read the
placements, and write **exactly two files**: ``bom.csv`` and ``cpl.csv``. All
intermediate state stays in memory.

Extraction rules (verified live, documented in ``docs/fusion-notes.md``):

- ``electronics.Attribute`` reads MUST be scoped by ``part_object_id`` —
  unscoped reads return empty, not an error.
- GND/supply pseudo-parts (``package3d_object_id`` = 0) and the title-block /
  logo part (``U$…`` with no LCSC/MPN) are excluded from the BOM.
- The JLC code is the ``LCSC`` attribute; MPN is ``MPN`` (fallback ``MP``).
- Board entities read empty until the board is the engine's current drawing;
  ``BOARD;`` switches it (without raising the board window). There is no
  command back — the user re-activates the schematic in the Fusion UI.

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
import re
from dataclasses import dataclass
from pathlib import Path

from .bridge import BridgeError, FusionBridge
from .fusion import DesignPart

BOM_FIELDS = ("Comment", "Designator", "Footprint", "JLCPCB Part #")
CPL_FIELDS = ("Designator", "Mid X", "Mid Y", "Layer", "Rotation")
ROTATIONS_FILENAME = Path("data") / "cpl-rotations.json"


@dataclass
class Placement:
    """One placed package on the board (an ``electronics.Element`` row)."""

    designator: str
    x: float  # mm, relative to the board origin (may be negative)
    y: float
    angle: float  # degrees, Fusion's raw value
    mirror: bool = False  # True = bottom side
    populate: bool = True
    footprint: str | None = None  # library package name, e.g. "DO-214AC(SMA)"


# ---------------------------------------------------------------------------
# Schematic side
# ---------------------------------------------------------------------------

def is_pseudo_part(part_row: dict, attrs: dict[str, str]) -> bool:
    """True for rows that are not real components (GND/supply symbols, title block)."""
    if part_row.get("package3d_object_id", 0) == 0:
        return True  # GND / supply pseudo-parts carry no package
    has_part_id = attrs.get("LCSC") or attrs.get("MPN") or attrs.get("MP")
    return part_row["name"].startswith("U$") and not has_part_id  # title block / logo


def part_from_row(part_row: dict, attrs: dict[str, str]) -> DesignPart:
    """Map a Part row + its attributes onto the :class:`DesignPart` contract."""
    return DesignPart(
        designator=part_row["name"],
        manufacturer_part=attrs.get("MPN") or attrs.get("MP"),
        jlc_code=attrs.get("LCSC"),
        value=part_row.get("value"),
        package=attrs.get("PACKAGE"),
        quantity=1,
        attributes=dict(attrs),
    )


def extract_schematic(bridge: FusionBridge) -> tuple[str, list[DesignPart]]:
    """Read the open design's name and real parts (schematic must be current first)."""
    design = "unknown"
    schematics = bridge.read_all("electronics.Schematic")
    if schematics:
        # name is a temp path ending in "<design> sch.sch"
        stem = schematics[0].get("name", "").replace("\\", "/").rsplit("/", 1)[-1]
        design = stem.removesuffix(".sch").removesuffix(" sch").strip() or "unknown"

    part_rows = bridge.read_all("electronics.Part")
    if not part_rows:
        raise BridgeError(
            "no schematic parts readable — activate the schematic in Fusion first "
            "(board→schematic has no command; click the schematic tab) and check for "
            "open modal dialogs"
        )
    parts: list[DesignPart] = []
    for row in part_rows:
        attr_rows = bridge.read_all(
            "electronics.Attribute",
            {"filters": [{"property": "part_object_id", "op": "eq", "value": row["object_id"]}]},
        )
        attrs = {a["name"]: a["value"] for a in attr_rows}
        if not is_pseudo_part(row, attrs):
            parts.append(part_from_row(row, attrs))
    parts.sort(key=lambda p: natural_key(p.designator))
    return design, parts


# ---------------------------------------------------------------------------
# Board side
# ---------------------------------------------------------------------------

def extract_board(bridge: FusionBridge) -> list[Placement]:
    """Read all board placements, switching the engine to the board if needed.

    The ``BOARD;`` switch is one-way (no command returns to the schematic), so
    call this only after :func:`extract_schematic`.
    """
    probe = bridge.read("electronics.Element", {"pagination": {"limit": 1, "offset": 0}})
    if not probe.get("items"):
        bridge.run_eagle("BOARD;")
    elements = bridge.read_all("electronics.Element")
    if not elements:
        raise BridgeError(
            "no board placements readable even after the BOARD; switch — "
            "is a board part of this design, and is Fusion free of modal dialogs?"
        )
    packages = {p["object_id"]: p.get("name") for p in bridge.read_all("electronics.Package")}
    placements = [
        Placement(
            designator=e["name"],
            x=e["x"],
            y=e["y"],
            angle=e["angle"],
            mirror=bool(e.get("mirror", 0)),
            populate=bool(e.get("populate", 1)),
            footprint=packages.get(e.get("package_object_id")),
        )
        for e in elements
    ]
    placements.sort(key=lambda p: natural_key(p.designator))
    return placements


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

def natural_key(designator: str):
    """Sort R2 before R13 (letters, then numeric suffix)."""
    m = re.match(r"([^\d]*)(\d*)", designator)
    return (m.group(1), int(m.group(2)) if m.group(2) else -1)


def build_bom_rows(parts: list[DesignPart], placements: list[Placement]) -> list[dict]:
    """Group parts into JLC BOM lines by identical (comment, footprint, JLC code).

    Comment is the schematic value, falling back to the MPN. Footprint is the
    board's library package name (falling back to the PACKAGE attribute).
    Do-not-populate parts are left out (matching their absence from the CPL).
    """
    place_by_desig = {pl.designator: pl for pl in placements}
    groups: dict[tuple[str, str, str], list[str]] = {}
    for part in parts:
        placed = place_by_desig.get(part.designator)
        if placed is not None and not placed.populate:
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
    """One CPL row per populated placement, rotation corrections applied.

    Returns ``(rows, applied)`` where ``applied`` records each correction that
    fired (designator, raw angle, corrected rotation, matched key) so callers
    can surface what changed.
    """
    corrections = corrections or []
    part_by_desig = {p.designator: p for p in parts}
    rows: list[dict] = []
    applied: list[dict] = []
    for pl in placements:
        if not pl.populate:
            continue
        part = part_by_desig.get(pl.designator)
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
