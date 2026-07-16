"""The canonical Requirements BOM and BOM Check vocabulary.

This closes the PRD's open question on the Requirements BOM schema
(PRD §21 / architecture §5.3): frozen dataclasses with a versioned JSON
representation (``requirementsBomVersion``). The JSON documents are the
contract every surface shares — the app renders them, the agent composes
them, the resolver consumes them.

A :class:`RequirementLine` carries **at most one selection mode** (PRD §9):

- ``spec`` — requirements-defined (resolved against the House Parts AVL)
- ``mpn`` (+ ``manufacturer``) — manufacturer-constrained
- ``provider_refs`` — exact provider part (e.g. an explicit LCSC code;
  verify-only, never substituted)

A line with no mode is legal at intake — it surfaces as an ``unresolved`` /
``no-code-uncheckable`` check downstream rather than being rejected (PRD
§12.14: unresolved lines are reported, never silently dropped). DNP lines are
carried and reported but excluded from resolution and order files.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

REQUIREMENTS_BOM_VERSION = 1

# BOM Check name → severity. Errors block upload; warnings are reported;
# info is advisory. (Ported vocabulary from the AGREED sourcing design §2;
# the table is the single authority — severities are validated at intake.)
CHECK_SEVERITIES = ("error", "warning", "info")
CHECKS = {
    "unresolved": "error",           # no provider ref (synthesized at the emit layer)
    "no-part-choices": "error",      # spec has no House Part / no active choices
    "avl-exhausted": "error",        # choices exist; none satisfies required qty
    "not-in-catalog": "error",       # a code the catalog no longer returns
    "insufficient-stock": "error",   # explicit code's stock < required qty
    "substitution": "warning",       # resolved at rank > 1
    "no-code-uncheckable": "warning",  # no spec and no code — nothing to verify
    "dnp": "info",                   # carried but not populated / not resolved
    "unverified": "warning",         # fact could not be live-verified (no data source)
}
ERROR_CHECKS = tuple(k for k, v in CHECKS.items() if v == "error")


@dataclass(frozen=True)
class Check:
    """One named validation result attached to a line or a resolution."""

    check: str
    severity: str
    message: str

    def to_dict(self) -> dict:
        return {"check": self.check, "severity": self.severity, "message": self.message}


def make_check(name: str, message: str) -> Check:
    """Build a :class:`Check`, refusing names missing from the authority table."""
    if name not in CHECKS:
        raise ValueError(f"unknown BOM check {name!r} (known: {sorted(CHECKS)})")
    return Check(check=name, severity=CHECKS[name], message=message)


@dataclass(frozen=True)
class SpecKey:
    """The canonical requirement key: what the design needs, not what to buy.

    ``kind`` and ``package`` are required. ``value`` is required only when
    the part HAS one: a 22k resistor does, a general-purpose diode does not
    — and a key that demands one just gets a fabricated answer (which is
    exactly how a "1000V" landed in a diode's value field once). Empty is a
    legal, honest value. ``qualifier`` carries the disambiguator when two
    different needs share the first three (e.g. ``"1%"``, ``"X7R 50V"``,
    ``"20A"``). Interpretation of free-form design attributes into a SpecKey
    is judgment (agent or engineer), not parsing — this class only validates
    shape.
    """

    kind: str
    value: str
    package: str
    qualifier: str = ""

    def __post_init__(self):
        for f in ("kind", "package"):
            if not getattr(self, f):
                raise ValueError(f"spec is missing required {f!r}: {self!r}")

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "value": self.value,
            "package": self.package,
            "qualifier": self.qualifier,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SpecKey":
        missing = [k for k in ("kind", "package") if not d.get(k)]
        if missing:
            raise ValueError(f"spec is missing {missing}: {d!r}")
        return cls(
            kind=str(d["kind"]),
            value=str(d.get("value") or ""),
            package=str(d["package"]),
            qualifier=str(d.get("qualifier") or ""),
        )


@dataclass
class RequirementLine:
    """One requirement: designators plus at most one selection mode."""

    designators: list[str]
    quantity_per: int = 1  # per-designator quantity
    dnp: bool = False  # carried + reported, excluded from resolution/output
    comment: str | None = None  # value/description (order-file Comment column)
    footprint: str | None = None  # the LIBRARY's name for the land, e.g. "SO16"
    # …and that footprint's own geometry, verbatim from the library. "SO16" cannot
    # tell a 3.9mm body from a 7.5mm one; "Small Outline package 150 mil" can.
    footprint_headline: str | None = None
    # Stable library identity used only to recognize the same engineering intent
    # across designs. Fusion object ids and design-local names never belong here.
    library_identity: dict[str, Any] | None = None
    # Verbatim schematic attributes used as interpretation evidence. These are
    # not identity by themselves; in particular MP/MF remain stale metadata.
    attributes: dict[str, str] = field(default_factory=dict)
    # The FAMILY: an incomplete part number the designer typed — "ULN2003",
    # "MB10S", "SP3485". It is NOT a selection mode and deliberately NOT `mpn`: a
    # family is a DEFAULT, not a lock. Pinning it (which is what happens today
    # when it lands in `mpn`) ships a part number nobody can order, unsieved. It
    # is a discovery seed — family + footprint → package → the parts — and it
    # coexists with whatever mode the line ends up in.
    family: str | None = None
    note: str | None = None
    spec: SpecKey | None = None  # requirements-defined → AVL resolution
    mpn: str | None = None  # manufacturer-constrained
    manufacturer: str | None = None
    provider_refs: dict[str, str] = field(default_factory=dict)  # provider → ref

    def __post_init__(self):
        if not self.designators:
            raise ValueError(f"line needs a non-empty 'designators' list: {self!r}")
        if self.quantity_per < 1:
            raise ValueError(f"'quantityPer' must be >= 1 (mark DNP instead): {self!r}")
        modes = [m for m, present in (
            ("spec", self.spec is not None),
            ("mpn", self.mpn is not None),
            ("provider", bool(self.provider_refs)),
        ) if present]
        if len(modes) > 1:
            raise ValueError(
                f"line has multiple selection modes {modes} — use exactly one "
                f"(an explicit part short-circuits spec resolution): {self!r}")
        if self.manufacturer and not self.mpn:
            raise ValueError(f"'manufacturer' requires 'mpn': {self!r}")

    @property
    def mode(self) -> str | None:
        """``"spec"`` | ``"mpn"`` | ``"provider"`` | ``None`` (nothing to resolve)."""
        if self.spec is not None:
            return "spec"
        if self.mpn is not None:
            return "mpn"
        if self.provider_refs:
            return "provider"
        return None

    def provider_ref(self, provider: str) -> str | None:
        return self.provider_refs.get(provider)

    def required_qty(self, production_quantity: int) -> int:
        """Parts needed for the build; 0 for DNP lines."""
        if self.dnp:
            return 0
        return len(self.designators) * self.quantity_per * production_quantity

    def to_dict(self) -> dict:
        d: dict[str, Any] = {
            "designators": list(self.designators),
            "quantityPer": self.quantity_per,
        }
        if self.dnp:
            d["dnp"] = True
        if self.comment is not None:
            d["comment"] = self.comment
        if self.footprint is not None:
            d["footprint"] = self.footprint
        if self.footprint_headline is not None:
            d["footprintHeadline"] = self.footprint_headline
        if self.library_identity is not None:
            d["libraryIdentity"] = dict(self.library_identity)
        if self.attributes:
            d["attributes"] = dict(self.attributes)
        if self.family is not None:
            d["family"] = self.family
        if self.note is not None:
            d["note"] = self.note
        if self.spec is not None:
            d["spec"] = self.spec.to_dict()
        if self.mpn is not None:
            d["mpn"] = self.mpn
        if self.manufacturer is not None:
            d["manufacturer"] = self.manufacturer
        if self.provider_refs:
            d["providerRefs"] = dict(self.provider_refs)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "RequirementLine":
        designators = d.get("designators")
        if not isinstance(designators, list) or not designators:
            raise ValueError(f"line is missing required non-empty 'designators': {d!r}")
        qp_raw = d.get("quantityPer", 1)
        quantity_per = int(qp_raw) if qp_raw is not None else 1

        provider_refs = dict(d.get("providerRefs") or {})
        # `lcsc` is the documented JLC shorthand (and the pre-port request
        # contract); it maps onto the neutral provider_refs form.
        if d.get("lcsc"):
            if provider_refs.get("jlcpcb", d["lcsc"]) != d["lcsc"]:
                raise ValueError(f"'lcsc' conflicts with providerRefs.jlcpcb: {d!r}")
            provider_refs["jlcpcb"] = str(d["lcsc"])

        spec = SpecKey.from_dict(d["spec"]) if d.get("spec") is not None else None
        return cls(
            designators=[str(x) for x in designators],
            quantity_per=quantity_per,
            dnp=bool(d.get("dnp", False)),
            comment=d.get("comment"),
            footprint=d.get("footprint"),
            footprint_headline=d.get("footprintHeadline"),
            library_identity=(dict(d["libraryIdentity"])
                              if isinstance(d.get("libraryIdentity"), dict) else None),
            attributes={str(k): str(v) for k, v in
                        dict(d.get("attributes") or {}).items()},
            family=d.get("family"),
            note=d.get("note"),
            spec=spec,
            mpn=d.get("mpn"),
            manufacturer=d.get("manufacturer"),
            provider_refs=provider_refs,
        )


@dataclass
class RequirementsBom:
    """The canonical Requirements BOM — the boundary between ECAD and resolver."""

    production_quantity: int
    lines: list[RequirementLine]
    design: str | None = None

    def __post_init__(self):
        if not isinstance(self.production_quantity, int) or self.production_quantity < 1:
            raise ValueError(
                f"'productionQuantity' must be a positive integer, "
                f"got {self.production_quantity!r}")
        if not self.lines:
            raise ValueError("a Requirements BOM needs a non-empty 'lines' list")

    def to_dict(self) -> dict:
        d: dict[str, Any] = {
            "requirementsBomVersion": REQUIREMENTS_BOM_VERSION,
            "productionQuantity": self.production_quantity,
            "lines": [ln.to_dict() for ln in self.lines],
        }
        if self.design:
            d["design"] = self.design
        return d

    @classmethod
    def from_dict(cls, doc: dict) -> "RequirementsBom":
        if not isinstance(doc, dict):
            raise ValueError("a Requirements BOM must be a JSON object")
        version = doc.get("requirementsBomVersion", REQUIREMENTS_BOM_VERSION)
        if version != REQUIREMENTS_BOM_VERSION:
            raise ValueError(
                f"unsupported requirementsBomVersion {version!r} "
                f"(this build reads {REQUIREMENTS_BOM_VERSION})")
        n = doc.get("productionQuantity")
        if not isinstance(n, int) or n < 1:
            raise ValueError(f"'productionQuantity' must be a positive integer, got {n!r}")
        lines = doc.get("lines")
        if not isinstance(lines, list) or not lines:
            raise ValueError("a Requirements BOM needs a non-empty 'lines' list")
        return cls(
            production_quantity=n,
            lines=[RequirementLine.from_dict(x) for x in lines],
            design=(str(doc["design"]) if doc.get("design") else None),
        )
