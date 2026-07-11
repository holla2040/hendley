"""Mechanical normalization: extracted Fusion parts → canonical Requirements BOM.

This is the parser half only. Interpreting free-form design attributes into a
:class:`~hendley.domain.model.SpecKey` (``22K`` ≡ ``22k``, qualifier
extraction) is judgment and stays with the engineer/agent/app — the
normalizer maps what the design states explicitly:

- ``LCSC`` attribute → a ``jlcpcb`` provider ref (exact-part line)
- ``MPN`` (fallback ``MP``) + ``MANUFACTURER`` → manufacturer-constrained line
- ``DNP`` attribute or an unpopulated board placement → ``dnp: true``
- identical lines merge (designators grouped, natural-sorted)

The board placement's ``populate`` flag and library footprint name are joined
in when placements are provided (the live pcba path).
"""

from __future__ import annotations

from ..domain.model import RequirementLine, RequirementsBom
from ..ingestion.fusion.live_design import Placement, is_dnp, natural_key
from ..ingestion.fusion.parts_json import DesignPart


def _line_key(part: DesignPart, footprint: str, dnp: bool) -> tuple:
    """Group identical needs: same identity, comment, footprint, DNP state."""
    comment = (part.value or "").strip() or (part.manufacturer_part or "")
    return (part.jlc_code or "", part.manufacturer_part or "", comment, footprint, dnp)


def requirements_from_design(
    design: str | None,
    parts: list[DesignPart],
    production_quantity: int,
    placements: list[Placement] | None = None,
) -> RequirementsBom:
    """Build the canonical Requirements BOM from extracted design parts.

    Every part becomes (part of) a line — DNP parts included, marked. Parts
    sharing identity/comment/footprint merge into one line with grouped
    designators.
    """
    place_by_desig = {pl.designator: pl for pl in (placements or [])}

    groups: dict[tuple, dict] = {}
    for part in parts:
        placed = place_by_desig.get(part.designator)
        dnp = is_dnp(part) or (placed is not None and not placed.populate)
        footprint = (placed.footprint if placed else None) or part.package or ""
        key = _line_key(part, footprint, dnp)
        g = groups.setdefault(key, {"part": part, "designators": [], "dnp": dnp,
                                    "footprint": footprint})
        g["designators"].append(part.designator)

    lines: list[RequirementLine] = []
    for g in groups.values():
        part: DesignPart = g["part"]
        comment = (part.value or "").strip() or (part.manufacturer_part or None)
        provider_refs = {"jlcpcb": part.jlc_code} if part.jlc_code else {}
        mpn = None if part.jlc_code else part.manufacturer_part
        manufacturer = (part.attributes or {}).get("MANUFACTURER") if mpn else None
        lines.append(RequirementLine(
            designators=sorted(g["designators"], key=natural_key),
            dnp=g["dnp"],
            comment=comment,
            footprint=g["footprint"] or None,
            provider_refs=provider_refs,
            mpn=mpn,
            manufacturer=manufacturer,
        ))
    lines.sort(key=lambda ln: natural_key(ln.designators[0]))
    return RequirementsBom(
        production_quantity=production_quantity,
        lines=lines,
        design=design,
    )
