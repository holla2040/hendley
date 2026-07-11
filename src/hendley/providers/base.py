"""Provider contracts — strategies select, adapters format.

The two roles are deliberately separate (architecture invariants 4/5):

- a :class:`ProviderStrategy` influences **resolution** — which refs to
  verify, whether a fact is orderable for this provider at this quantity,
  and provider-flavored scoring input for candidate ranking;
- a :class:`ProviderAdapter` turns an **approved** resolution into the
  provider's upload files. It never selects parts.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from ..domain.model import Check, RequirementLine, RequirementsBom
from ..datasources.base import PartFact


@runtime_checkable
class ProviderStrategy(Protocol):
    """Sourcing policy for one manufacturing/procurement context."""

    provider: str  # e.g. "jlcpcb", "pcbway"
    offer_type: str  # the Solution offer type this strategy computes

    def query_context(self, requirements: RequirementsBom, candidate_refs: list[str]) -> list[str]:
        """Refs to live-verify for this resolution (may add/drop refs)."""
        ...

    def evaluate(self, line: RequirementLine, fact: PartFact | None,
                 required_qty: int) -> tuple[bool, list[Check]]:
        """Is this fact orderable for the line at the required quantity?"""
        ...

    def score(self, candidate: dict, required_qty: int) -> list[dict]:
        """Provider-flavored score contributions for a discovered candidate.

        Each contribution is ``{"factor": str, "weight": float, "why": str}``;
        the ranking engine sums and displays them (ranking is policy, and it
        must stay inspectable).
        """
        ...


@runtime_checkable
class ProviderAdapter(Protocol):
    """Formats an approved resolution into provider upload files."""

    provider: str

    def validate(self, resolution: dict) -> list[Check]:
        """Blocking-check gate: error-severity checks refuse the export."""
        ...

    def export(self, resolution: dict, outdir: Path) -> list[Path]:
        """Write the provider's order files; returns the written paths."""
        ...
