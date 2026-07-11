"""Live Fusion design extraction — schematic parts and board placements.

The read side of the ``hendley pcba`` flow: pull the open design over the HTTP
bridge (parts + part-scoped attributes), switch the electronics engine's
current drawing to the board (``BOARD;`` — one-way; the schematic must be read
*first*), and read the placements. All state stays in memory; turning the
extraction into JLCPCB order files is the provider adapter's job
(:mod:`hendley.providers.jlcpcb.order_files`).

Extraction rules (verified live, documented in ``docs/fusion-notes.md``):

- ``electronics.Attribute`` reads MUST be scoped by ``part_object_id`` —
  unscoped reads return empty, not an error.
- GND/supply pseudo-parts (``package3d_object_id`` = 0) and the title-block /
  logo part (``U$…`` with no LCSC/MPN) are excluded.
- Parts marked do-not-populate — the schematic ``DNP`` attribute set to
  anything but ``0`` (test points, mount holes, programming pads), or the
  board element's ``populate`` flag off — are carried but flagged via
  :func:`is_dnp` / ``Placement.populate``.
- The JLC code is the ``LCSC`` attribute; MPN is ``MPN`` (fallback ``MP``).
- Board entities read empty until the board is the engine's current drawing;
  ``BOARD;`` switches it (without raising the board window). There is no
  command back — the user re-activates the schematic in the Fusion UI.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .bridge import BridgeError, FusionBridge
from .parts_json import DesignPart


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


def natural_key(designator: str):
    """Sort R2 before R13 (letters, then numeric suffix)."""
    m = re.match(r"([^\d]*)(\d*)", designator)
    return (m.group(1), int(m.group(2)) if m.group(2) else -1)


# ---------------------------------------------------------------------------
# Schematic side
# ---------------------------------------------------------------------------

def is_pseudo_part(part_row: dict, attrs: dict[str, str]) -> bool:
    """True for rows that are not real components (GND/supply symbols, title block)."""
    if part_row.get("package3d_object_id", 0) == 0:
        return True  # GND / supply pseudo-parts carry no package
    has_part_id = attrs.get("LCSC") or attrs.get("MPN") or attrs.get("MP")
    return part_row["name"].startswith("U$") and not has_part_id  # title block / logo


def is_dnp(part: DesignPart) -> bool:
    """True when the schematic marks the part do-not-populate (``DNP`` attribute).

    Any value other than empty or ``0`` counts as set, matching the loose way
    libraries fill it in (``1``, ``true``, ``yes``).
    """
    return (part.attributes or {}).get("DNP", "").strip() not in ("", "0")


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
