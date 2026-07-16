"""Normalization: extracted Fusion parts → canonical Requirements BOM.

Maps what the design states — explicitly or implicitly:

- ``LCSC`` attribute → a ``jlcpcb`` provider ref (exact-part line)
- ``MPN`` + ``MANUFACTURER`` → manufacturer-constrained line. (``MP`` is NEVER
  read — it is a stale SnapEDA import; see ``live_design``.)
- **a semiconductor states a FAMILY**: a ``U``/``D``/``Q`` part with no LCSC
  names an incomplete part number — ``ULN2003``, ``MB10S``, ``1N4148`` — in its
  MPN attribute or, more often, its schematic VALUE. That is not orderable: the
  family ships in a dozen packages and the FOOTPRINT decides which one may go on
  the board. It becomes ``line.family``, a discovery seed — explicitly **not**
  ``line.mpn``, which would PIN it and ship an unorderable part number unsieved.
- **generic passives state their spec**: kind from the designator prefix,
  canonical value from the part value, package from the footprint name
  (:mod:`hendley.requirements.specs`) — so a plain "82k / R-0402" resistor
  resolves against the House Parts DB with zero hand-editing
- ``DNP`` attribute, a part value of ``DNP``, or an unpopulated board
  placement → ``dnp: true``
- identical lines merge (designators grouped, natural-sorted)

Parts that state nothing confidently (no id, no inferable spec) surface as
mode-less lines — a visible decision downstream, never a silent guess.
"""

from __future__ import annotations

from ..domain.model import RequirementLine, RequirementsBom, SpecKey
from ..ingestion.fusion.live_design import Placement, is_dnp, natural_key
from ..ingestion.fusion.parts_json import DesignPart
from .specs import infer_spec

# Designators whose part is named by a FAMILY rather than a value. A designer
# types "ULN2003", "MB10S", "1N4148" — an incomplete part number that ships in a
# dozen packages, and the board decides which one can be ordered. Passives are
# not here: an "82k" resistor states a spec, and infer_spec() already reads it.
FAMILY_PREFIXES = ("U", "D", "Q")

# Attribute values that describe workflow/provider metadata rather than the
# electrical specification. Attribute NAMES are never scanned: "SIZE" contains
# a Z but says nothing about diode class.
_NON_SPEC_ATTRIBUTES = {"DNP", "LCSC", "JLC", "JLCPCB", "MANUFACTURER", "MP", "MF"}


def designator_prefix(designator: str) -> str:
    return natural_key(designator)[0]


def has_zener_evidence(designator: str, value: str | None,
                       attributes: dict[str, str] | None = None) -> bool:
    """Whether a diode's written specification explicitly cues Zener intent.

    For this shop, Z anywhere in the VALUE or a meaningful attribute VALUE is
    the convention. A bare voltage (10V0, 500V, 1000V) is not evidence: ordinary
    diodes also state reverse-voltage ratings. The catalog class still confirms
    the concrete part after discovery.
    """
    if designator_prefix(designator) != "D":
        return False
    texts = [str(value or "")]
    texts.extend(
        str(v) for k, v in (attributes or {}).items()
        if str(k).strip().upper() not in _NON_SPEC_ATTRIBUTES
    )
    return any("z" in text.casefold() for text in texts)


def family_of(part: DesignPart, footprint: str, dnp: bool = False) -> str | None:
    """The family this part names, or None if it names none.

    The family is the ``MPN`` attribute if the designer filled it in, **else** the
    schematic VALUE — because the value shows on the schematic, which is why they
    mostly use it. The legacy ``MP`` is never consulted (see ``live_design``).

    A family needs a footprint to be resolvable at all: family + footprint →
    package → the parts. Without one there is nothing to narrow with, so the line
    stays a decision for the engineer rather than becoming a search for every
    package the family ships in.

    A DNP part names no family. Its VALUE is often literally ``DNP``, and that
    would otherwise be searched for as though it were a part number — a nonsense
    query, and a paid web lookup, for a part that is not being fitted.
    """
    if dnp or part.jlc_code or not footprint:
        return None                      # not fitted / exact part / nothing to narrow
    if designator_prefix(part.designator) not in FAMILY_PREFIXES:
        return None
    return ((part.manufacturer_part or "").strip()
            or (part.value or "").strip() or None)


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
        footprint = ((placed.footprint if placed else None)
                     or part.footprint or part.package or "")
        comment = (part.value or "").strip() or (part.manufacturer_part or None)

        spec: SpecKey | None = None
        provider_refs = {"jlcpcb": part.jlc_code} if part.jlc_code else {}
        # A FAMILY is not an MPN. "ULN2003" in the MPN attribute used to land in
        # `mpn` and PIN the line — an unorderable part number, never sieved,
        # shipped to the resolver as if it were real. It is a discovery seed now.
        family = family_of(part, footprint, dnp)
        mpn = None if (part.jlc_code or family) else part.manufacturer_part
        if not provider_refs and not mpn and not family:
            spec = infer_spec(part.designator, part.value, footprint)

        attributes = {str(k): str(v) for k, v in (part.attributes or {}).items()}
        # A mode-less/family line may derive its class from a unique schematic
        # symbol. Keep it separate until that intent is read: grouping Q2/Q3
        # merely because both say `40V` on SOT-23 destroys N/P-channel evidence.
        unresolved_instance = (part.designator if not dnp and not provider_refs
                               and not mpn and spec is None else "")
        key = (part.jlc_code or "", mpn or "", family or "", spec, comment or "",
               footprint, dnp, tuple(sorted(attributes.items())),
               unresolved_instance)
        g = groups.setdefault(key, {"part": part, "designators": [], "dnp": dnp,
                                    "footprint": footprint, "comment": comment,
                                    "spec": spec, "family": family,
                                    "attributes": attributes})
        g["designators"].append(part.designator)

    lines: list[RequirementLine] = []
    for g in groups.values():
        part: DesignPart = g["part"]
        provider_refs = {"jlcpcb": part.jlc_code} if part.jlc_code else {}
        mpn = None if (part.jlc_code or g["family"]) else part.manufacturer_part
        manufacturer = (part.attributes or {}).get("MANUFACTURER") if mpn else None
        lines.append(RequirementLine(
            designators=sorted(g["designators"], key=natural_key),
            dnp=g["dnp"],
            comment=g["comment"],
            footprint=g["footprint"] or None,
            footprint_headline=part.footprint_headline,
            attributes=g["attributes"],
            family=g["family"],
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
