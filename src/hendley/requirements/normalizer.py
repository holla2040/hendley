"""Normalization: extracted Fusion parts → canonical Requirements BOM.

Maps what the design states — explicitly or implicitly:

- ``LCSC`` attribute → a ``jlcpcb`` provider ref (exact-part line)
- ``MPN`` (fallback ``MP``) + ``MANUFACTURER`` → manufacturer-constrained line
- **generic passives state their spec**: kind from the designator prefix,
  canonical value from the part value, package from the footprint name
  (:mod:`hendley.requirements.specs`) — so a plain "82k / R-0402" resistor
  resolves against the House Parts DB with zero hand-editing
- ``DNP`` attribute or an unpopulated board placement → ``dnp: true``
- identical lines merge (designators grouped, natural-sorted)

Parts that state nothing confidently (no id, no inferable spec) surface as
mode-less lines — a visible decision downstream, never a silent guess.
"""

from __future__ import annotations

from ..domain.model import RequirementLine, RequirementsBom, SpecKey
from ..ingestion.fusion.live_design import Placement, is_dnp, natural_key
from ..ingestion.fusion.parts_json import DesignPart
from .specs import infer_spec


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
        comment = (part.value or "").strip() or (part.manufacturer_part or None)

        spec: SpecKey | None = None
        provider_refs = {"jlcpcb": part.jlc_code} if part.jlc_code else {}
        mpn = None if part.jlc_code else part.manufacturer_part
        if not provider_refs and not mpn:
            spec = infer_spec(part.designator, part.value, footprint)

        key = (part.jlc_code or "", mpn or "", spec, comment or "", footprint, dnp)
        g = groups.setdefault(key, {"part": part, "designators": [], "dnp": dnp,
                                    "footprint": footprint, "comment": comment,
                                    "spec": spec})
        g["designators"].append(part.designator)

    lines: list[RequirementLine] = []
    for g in groups.values():
        part: DesignPart = g["part"]
        provider_refs = {"jlcpcb": part.jlc_code} if part.jlc_code else {}
        mpn = None if part.jlc_code else part.manufacturer_part
        manufacturer = (part.attributes or {}).get("MANUFACTURER") if mpn else None
        lines.append(RequirementLine(
            designators=sorted(g["designators"], key=natural_key),
            dnp=g["dnp"],
            comment=g["comment"],
            footprint=g["footprint"] or None,
            spec=g["spec"],
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
