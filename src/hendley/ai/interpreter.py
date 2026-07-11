"""The Interpreter contract — ad-hoc design text → canonical spec + envelope."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from ..domain.model import SpecKey


@dataclass
class Interpretation:
    """One judged reading of a part's ad-hoc description.

    ``spec`` is the canonical requirement key. ``envelope`` is the physical
    reality of the footprint, used by the fit constraint::

        {"mount": "smd" | "tht", "maxDiaMm": 6.3, "maxLenMm": 8.0,
         "leadSpacingMm": 5.0}

    (all envelope fields optional — absent means unknown, and unknown fit
    is surfaced, never assumed). ``confidence`` is 0..1; ``rationale`` is
    the one-line why, shown to the engineer and kept in the cache.
    """

    spec: SpecKey | None = None
    envelope: dict = field(default_factory=dict)
    confidence: float = 0.0
    rationale: str = ""

    def to_dict(self) -> dict:
        return {
            "spec": self.spec.to_dict() if self.spec else None,
            "envelope": dict(self.envelope),
            "confidence": self.confidence,
            "rationale": self.rationale,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Interpretation":
        spec = SpecKey.from_dict(d["spec"]) if d.get("spec") else None
        return cls(spec=spec, envelope=dict(d.get("envelope") or {}),
                   confidence=float(d.get("confidence") or 0.0),
                   rationale=str(d.get("rationale") or ""))


@runtime_checkable
class Interpreter(Protocol):
    """Judges ad-hoc part descriptions. Implementations must be replaceable."""

    name: str

    def interpret_part(self, ctx: dict) -> Interpretation | None:
        """Interpret one part's context, or None when unavailable/unsure.

        ``ctx``: ``{"designator", "value", "footprint", "attributes",
        "geometry"?}`` — whatever the design states, verbatim.
        """
        ...
