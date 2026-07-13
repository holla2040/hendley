"""The Interpreter contract — ad-hoc design text → canonical spec + envelope."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from ..domain.model import SpecKey


@dataclass
class Interpretation:
    """One judged reading of a part's ad-hoc description.

    ``spec`` is the canonical requirement key — set only when the reading is
    COMPLETE. ``partial`` carries an incomplete reading (the same four spec
    fields, any of them empty): a schematic diode with no VALUE is honestly
    "kind=diode, package=SOD-323, value unknown" — real knowledge that must
    reach the engineer's confirm card as prefill, never be thrown away.

    ``envelope`` is the physical reality of the footprint, used by the fit
    constraint::

        {"mount": "smd" | "tht", "maxDiaMm": 6.3, "maxLenMm": 8.0,
         "leadSpacingMm": 5.0}

    (all envelope fields optional — absent means unknown, and unknown fit
    is surfaced, never assumed). ``confidence`` is 0..1; ``rationale`` is
    the one-line why, shown to the engineer and kept in the cache.
    """

    spec: SpecKey | None = None
    partial: dict = field(default_factory=dict)
    envelope: dict = field(default_factory=dict)
    confidence: float = 0.0
    rationale: str = ""

    def to_dict(self) -> dict:
        return {
            "spec": self.spec.to_dict() if self.spec else None,
            "partial": dict(self.partial),
            "envelope": dict(self.envelope),
            "confidence": self.confidence,
            "rationale": self.rationale,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Interpretation":
        spec = SpecKey.from_dict(d["spec"]) if d.get("spec") else None
        return cls(spec=spec, partial=dict(d.get("partial") or {}),
                   envelope=dict(d.get("envelope") or {}),
                   confidence=float(d.get("confidence") or 0.0),
                   rationale=str(d.get("rationale") or ""))


@runtime_checkable
class Interpreter(Protocol):
    """Judges ad-hoc part descriptions. Implementations must be replaceable."""

    name: str

    def interpret_part(self, ctx: dict) -> Interpretation | None:
        """Interpret one part's context.

        ``ctx``: ``{"designator", "value", "footprint", "attributes",
        "geometry"?}`` — whatever the design states, verbatim.

        None means the INTERPRETER is unavailable (binary missing, timeout,
        no usable answer) — the caller stops asking it. An Interpretation
        whose ``spec`` is None means it answered but the reading is
        incomplete: an honest "I got this far" (see ``partial``), and the
        caller keeps consulting it for the other parts.
        """
        ...

    def read_part(self, dossier: dict) -> dict | None:
        """Work out what a design's part actually IS, from everything known.

        Called when the engineer opens a part — for EVERY part, whatever the
        schematic does or doesn't say about it. ``dossier`` carries every
        fact the app holds::

            {"schematic": {"designators", "prefix", "value", "footprint",
                           "mpn", "code"},          # verbatim, as drawn
             "catalog":   {"code", "mpn", "manufacturer", "package",
                           "libraryType", "parameters"} | None,
             "convention": {...} | {}}              # this shop's designator rule

        ``catalog`` is the part's own record from the live catalog, present
        whenever the design pins a part number (or one is already mounted).
        It is GROUND TRUTH: when it is there, nothing is guessed — the
        package is ``componentSpecification``, the specs are ``parameters``.
        That record is where a library footprint like ``C-E-5`` finally
        becomes a real package (``插件,D5xL11mm`` — read it, never parse it).

        Returns::

            {"is": "10uF 50V aluminium electrolytic, through-hole, D5x11mm",
             "spec": {kind, value, package, qualifier},
             "search": "10u 50V electrolytic",   # seeds the search box
             "plan": {category, net, sieve},     # seeds the part-type popup
             "rationale": "...", "confidence": 0..1}

        None = interpreter unavailable.
        """
        ...

    def plan_search(self, ctx: dict) -> dict | None:
        """Turn the engineer's words into a query plan for the parts index.

        ``ctx``: ``{"terms"}`` (verbatim, whatever they typed) plus the
        design context they typed it against — ``{"designator", "value",
        "footprint", "package"?, "spec"?}``.

        Returns the plan (see ``SEARCH_PLAN_SHAPE``)::

            {"mode": "parametric" | "fts" | "code",
             "category": "resistors",              # a jlcsearch slug
             "net": {"package": "0603", "resistance": 22000},
             "sieve": [{"field": "tolerance_fraction", "op": "lte",
                        "value": 0.01}],
             "lookingFor": {kind, value, package, qualifier},  # display only
             "say": "22k 0603, 1% or better",
             "confidence": 0.0..1}

        The **net** may only use params the index actually honours; the
        **sieve** re-asserts EVERY constraint (the index silently ignores
        params it doesn't know, so the net is a coarse net and the sieve is
        the truth). None = interpreter unavailable; the caller falls back to
        a verbatim keyword search and says so.
        """
        ...

    def derive_key(self, ctx: dict) -> dict | None:
        """Name the requirement this pick satisfies — the AVL's database key.

        Called ONCE, when the engineer commits a pick. ``ctx`` carries
        everything known: the design line (``designator``, ``value``,
        ``footprint``), what they searched (``terms``), what the app
        remembered (``remembered``), and the picked part's VERIFIED facts
        (``part``: mpn, manufacturer, package, parameters).

        Returns ``{"spec": {kind, value, package, qualifier}, "rationale",
        "confidence"}`` — the key every future design files this requirement
        under. ``value`` is left empty when the part genuinely has none;
        ratings (50V, 1%, X7R, 1/4W) belong in ``qualifier``. Never invent a
        value. None = unavailable.
        """
        ...
