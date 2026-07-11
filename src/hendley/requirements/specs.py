"""Spec inference for generic parts — the tool's job, not the user's.

A generic passive already states everything a spec needs: the kind is in the
designator prefix, the value is on the part, the package is in the footprint
name. This module turns those into the canonical
:class:`~hendley.domain.model.SpecKey` so a schematic pull resolves against
the House Parts DB with zero hand-editing.

Deliberately conservative: inference only fires for kinds where a wrong
guess is impossible-or-harmless (R/C/L chip passives with a recognizable
chip package). Everything else keeps its explicit identity (LCSC/MPN) or
surfaces as a decision — never a silent guess.
"""

from __future__ import annotations

import re

from ..domain.model import SpecKey

# designator prefix → spec kind, for kinds we auto-spec. Longest match wins.
SPEC_KINDS = {
    "R": "resistor",
    "C": "capacitor",
    "L": "inductor",
}

# chip packages recognizable inside a library footprint name (R-0402, C-0603…)
_CHIP_PACKAGE = re.compile(r"(?<!\d)(0201|0402|0603|0805|1206|1210|2010|2512)(?!\d)")

_VALUE = re.compile(r"^(\d+(?:\.\d+)?|\.\d+)\s*([a-zµμΩω]*)$")

# value-suffix normalization per kind: canonical unit multipliers.
_R_SUFFIX = {"": 1, "r": 1, "ohm": 1, "k": 1e3, "m": 1e6, "meg": 1e6}
_C_SUFFIX = {"p": 1e-12, "pf": 1e-12, "n": 1e-9, "nf": 1e-9,
             "u": 1e-6, "uf": 1e-6, "µ": 1e-6, "µf": 1e-6, "μ": 1e-6, "μf": 1e-6,
             "f": 1}
_L_SUFFIX = {"n": 1e-9, "nh": 1e-9, "u": 1e-6, "uh": 1e-6, "µ": 1e-6, "µh": 1e-6,
             "μ": 1e-6, "μh": 1e-6, "m": 1e-3, "mh": 1e-3, "h": 1}


def kind_for_designator(designator: str) -> str | None:
    """The auto-spec kind for a designator, or None (R7 → resistor; RV/U/J → None)."""
    m = re.match(r"([A-Za-z]+)", designator or "")
    prefix = (m.group(1) if m else "").upper()
    return SPEC_KINDS.get(prefix)


def package_from_footprint(footprint: str | None) -> str | None:
    """Extract the chip package from a library footprint name (R-0603 → 0603)."""
    if not footprint:
        return None
    m = _CHIP_PACKAGE.search(footprint)
    return m.group(1) if m else None


def base_value(kind: str, value: str | None) -> float | None:
    """Parse a design value string into base units (ohms/farads/henries).

    Handles the common spellings — ``82K``, ``4.7k``, ``.1u``, ``100n``,
    ``22uH``, ``220`` — case-insensitively. Returns None when the string
    isn't confidently parseable (then no spec is inferred).
    """
    if not value:
        return None
    text = value.strip().replace("Ω", "").replace("ω", "")
    suffixes = {"resistor": _R_SUFFIX, "capacitor": _C_SUFFIX,
                "inductor": _L_SUFFIX}.get(kind)
    if suffixes is None:
        return None
    # R-style infix notation: 4k7 = 4.7k, 0R1 = 0.1
    m = re.match(r"^(\d+)([rkmRKM])(\d+)$", text)
    if m and kind == "resistor":
        mult = _R_SUFFIX[m.group(2).lower()]
        return float(f"{m.group(1)}.{m.group(3)}") * mult
    m = _VALUE.match(text.lower())
    if not m:
        return None
    number, suffix = float(m.group(1)), m.group(2)
    if suffix not in suffixes:
        return None
    return number * suffixes[suffix]


def canonical_value(kind: str, value: str | None) -> str | None:
    """Canonical spec-value string for a design value (``82K`` → ``82k``,
    ``.1u`` → ``100n``), or None when not confidently parseable."""
    base = base_value(kind, value)
    if base is None or base <= 0:
        return None
    if kind == "resistor":
        steps = (("M", 1e6), ("k", 1e3), ("", 1))
    elif kind == "capacitor":
        steps = (("F", 1), ("m", 1e-3), ("u", 1e-6), ("n", 1e-9), ("p", 1e-12))
    else:  # inductor
        steps = (("H", 1), ("m", 1e-3), ("u", 1e-6), ("n", 1e-9))
    for unit, mult in steps:
        scaled = base / mult
        if scaled >= 1:
            text = f"{scaled:.3f}".rstrip("0").rstrip(".")
            return f"{text}{unit}"
    return None


def infer_spec(designator: str, value: str | None,
               footprint: str | None) -> SpecKey | None:
    """The SpecKey a generic part states about itself, or None.

    Fires only when all three legs are confident: an auto-spec kind, a
    parseable value, and a recognizable chip package.
    """
    kind = kind_for_designator(designator)
    if kind is None:
        return None
    package = package_from_footprint(footprint)
    if package is None:
        return None
    canonical = canonical_value(kind, value)
    if canonical is None:
        return None
    return SpecKey(kind=kind, value=canonical, package=package)
