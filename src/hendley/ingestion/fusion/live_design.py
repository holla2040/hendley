"""Live Fusion design extraction — schematic parts and board placements.

The read side of the ``hendley pcba`` flow: pull the open design over the HTTP
bridge (parts + part-scoped attributes), request schematic sheet 1 when needed
(``EDIT .S1;``), read it, switch to the board (``BOARD;``), and read the
placements. The current MCP proxy may wedge on a later return from board, so
callers should read schematic data first. All state stays in memory; turning the
extraction into JLCPCB order files is the provider adapter's job
(:mod:`hendley.providers.jlcpcb.order_files`).

Extraction rules (verified live, documented in ``docs/fusion-notes.md``):

- ``electronics.Attribute`` reads MUST be scoped by ``part_object_id`` —
  unscoped reads return empty, not an error.
- GND/supply pseudo-parts (their library device carries **no footprint** —
  ``electronics.Device.package_object_id`` = 0) and the title-block / logo
  part (``U$…`` with no LCSC/MPN) are excluded. Only the 2D footprint
  matters; 3D models are irrelevant to this tool (a real part whose device
  has no 3D model, e.g. a fresh library variant, must never be filtered).
- Parts marked do-not-populate — the schematic ``DNP`` attribute set to
  anything but ``0`` (test points, mount holes, programming pads), a part
  VALUE of literally ``DNP``, or the board element's ``populate`` flag off —
  are carried but flagged via :func:`is_dnp` / ``Placement.populate``.
- The JLC code is the ``LCSC`` attribute; the MPN is ``MPN`` and **only** ``MPN``.
  The legacy ``MP``/``MF`` attributes are stale SnapEDA imports and are NEVER an
  identity (they said ``MB6S`` — 600 V — on a part whose VALUE said ``MB10S`` —
  1000 V).
- The library FOOTPRINT and its geometry come from ``electronics.Device`` →
  ``electronics.Package`` (``name`` + ``headline``), read schematic-side with no
  ``BOARD;`` switch. The headline is what distinguishes a 150-mil ``SO16`` from a
  300-mil one; the name alone cannot.
- Board entities read empty until the board is the engine's current drawing;
  ``BOARD;`` switches it without raising the board window. ``EDIT .S1;`` can
  request schematic sheet 1, but some MCP sessions wedge on a board return.
"""

from __future__ import annotations

import re
import time
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

def is_pseudo_part(part_row: dict, attrs: dict[str, str], has_footprint: bool) -> bool:
    """True for rows that are not real components (GND/supply symbols, title block).

    ``has_footprint`` is whether the part's library device carries a 2D
    footprint (``electronics.Device.package_object_id`` != 0) — the one
    honest discriminator: supply symbols have none, every orderable part
    has one.
    """
    if not has_footprint:
        return True  # GND / supply pseudo-parts carry no footprint
    has_part_id = attrs.get("LCSC") or attrs.get("MPN") or attrs.get("MP")
    return part_row["name"].startswith("U$") and not has_part_id  # title block / logo


def is_dnp(part: DesignPart) -> bool:
    """True when the schematic marks the part do-not-populate.

    Two spellings count: the ``DNP`` attribute set to anything other than
    empty or ``0`` (matching the loose way libraries fill it in — ``1``,
    ``true``, ``yes``), or the part's VALUE being literally ``DNP`` (a common
    schematic shorthand, e.g. a resistor whose value reads ``DNP``).
    """
    if (part.attributes or {}).get("DNP", "").strip() not in ("", "0"):
        return True
    return (part.value or "").strip().upper() == "DNP"


def part_from_row(part_row: dict, attrs: dict[str, str],
                  footprint: dict | None = None,
                  library_identity: dict | None = None) -> DesignPart:
    """Map a Part row + its attributes onto the :class:`DesignPart` contract.

    The MPN is the ``MPN`` attribute and **only** that. The legacy ``MP`` is NOT
    an identity and is never read here (Craig, 2026-07-13 — it is being retired):
    on a real board it said ``MB6S`` where the schematic VALUE said ``MB10S``, and
    those are a 600 V part and a 1000 V part. A stale SnapEDA import must not get
    to decide what gets soldered down.
    """
    footprint = footprint or {}
    return DesignPart(
        designator=part_row["name"],
        manufacturer_part=attrs.get("MPN"),
        jlc_code=attrs.get("LCSC"),
        value=part_row.get("value"),
        package=attrs.get("PACKAGE"),
        footprint=footprint.get("name"),
        footprint_headline=footprint.get("headline"),
        library_identity=library_identity,
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
    if design == "unknown":
        # electronics.Schematic can be empty even while Part rows are readable.
        # A shared "unknown" draft namespace would leak one design's typed
        # searches into another, so ask Fusion for the active document name.
        read_name = getattr(bridge, "active_document_name", None)
        if read_name:
            design = str(read_name() or "").strip() or "unknown"

    part_rows = bridge.read_all("electronics.Part")
    if not part_rows:
        # Verified live 2026-07-15: unlike BOARD;, EDIT .S1 works across editor
        # contexts and makes schematic entities readable while the layout is
        # frontmost. Sheet 1 necessarily exists in a paired schematic; never
        # probe higher numbers because EDIT creates a missing sheet.
        bridge.run_eagle("EDIT .S1;")
        time.sleep(0.75)  # Fusion changes Electronics context asynchronously.
        part_rows = bridge.read_all("electronics.Part")
    if not part_rows:
        raise BridgeError(
            "no schematic parts readable even after EDIT .S1 — check for open "
            "modal dialogs and confirm the Electronics design has a schematic"
        )
    # The library FOOTPRINT, read schematic-side — no BOARD; switch needed. The
    # device already names its package; joining electronics.Package gives us the
    # footprint's NAME and, crucially, its HEADLINE, which is where the geometry
    # lives ("Small Outline package 150 mil"). This used to be thrown away — the
    # package id was coerced to bool() and discarded — leaving "SO16" as the only
    # evidence of a land, which is not enough to tell a 3.9mm body from a 7.5mm one.
    packages = {p["object_id"]: {"name": p.get("name"),
                                 "headline": (p.get("headline") or "").strip() or None}
                for p in bridge.read_all("electronics.Package")}
    devices = bridge.read_all("electronics.Device")
    # Whether the part is REAL stays keyed on the package id, exactly as before —
    # never on the joined row. The geometry is an enrichment, and an enrichment
    # that fails must not delete the BOM: if electronics.Package reads empty, we
    # lose the headline and still ship every part.
    device_footprint = {d["object_id"]: bool(d.get("package_object_id")) for d in devices}
    device_package = {d["object_id"]: packages.get(d.get("package_object_id"))
                      for d in devices}
    def stable_identity(device: dict, package: dict | None) -> dict | None:
        """Keep Fusion library identity while deliberately dropping object ids."""
        aliases = {
            "deviceSetUrn": ("device_set_urn", "deviceSetUrn", "deviceset_urn", "urn"),
            "libraryVersion": ("library_version", "libraryVersion", "version"),
            "deviceVariant": ("name", "device_name", "deviceName", "variant"),
            "packageVariant": ("package_name", "packageName"),
            "libraryName": ("library_name", "libraryName"),
            "locallyModified": ("locally_modified", "locallyModified", "modified"),
        }
        out = {}
        for target, names in aliases.items():
            for name in names:
                if device.get(name) not in (None, ""):
                    out[target] = device[name]
                    break
        if package:
            out.setdefault("packageVariant", package.get("name"))
        # A URN is the minimum stable global identity. Names alone are local.
        return out if out.get("deviceSetUrn") else None
    device_rows = {d["object_id"]: d for d in devices}
    parts: list[DesignPart] = []
    for row in part_rows:
        attr_rows = bridge.read_all(
            "electronics.Attribute",
            {"filters": [{"property": "part_object_id", "op": "eq", "value": row["object_id"]}]},
        )
        attrs = {a["name"]: a["value"] for a in attr_rows}
        has_footprint = device_footprint.get(row.get("device_object_id"), False)
        if not is_pseudo_part(row, attrs, has_footprint):
            device = device_rows.get(row.get("device_object_id"), {})
            package = device_package.get(row.get("device_object_id"))
            parts.append(part_from_row(row, attrs, package,
                                       stable_identity(device, package)))
    parts.sort(key=lambda p: natural_key(p.designator))
    return design, parts


# ---------------------------------------------------------------------------
# Board side
# ---------------------------------------------------------------------------

def extract_board(bridge: FusionBridge) -> list[Placement]:
    """Read all board placements, switching the engine to the board if needed.

    Read the schematic first for a coherent snapshot. Do not depend on a later
    board-to-schematic return in the same MCP session.
    """
    probe = bridge.read("electronics.Element", {"pagination": {"limit": 1, "offset": 0}})
    if not probe.get("items"):
        switched = bridge.run_eagle("BOARD;")
        if switched.get("success") is False:
            detail = switched.get("error") or switched.get("message") or switched
            raise BridgeError(f"Fusion refused BOARD;: {detail}")
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
