"""The DataSource contract — how the resolver sees component facts.

Facts carry provenance and freshness (architecture invariant 9: "unknown
inventory is not zero inventory"): every :class:`PartFact` says where it came
from and when. Live-verified facts and discovery-index rows must never be
conflated — ``verify()`` returns authoritative facts; ``discover()`` returns
candidates whose numbers are advisory until verified.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, Sequence, runtime_checkable


@dataclass
class PartFact:
    """One live-verified fact about a purchasable part."""

    ref: str  # the provider/datasource ref that was queried (e.g. "C31850")
    found: bool
    stock: int | None = None
    mpn: str | None = None
    manufacturer: str | None = None
    description: str | None = None
    offer_class: str | None = None  # e.g. JLC's "Basic"/"Extended" libraryType
    price_tiers: list[dict] = field(default_factory=list)  # raw tier rows
    provenance: str = ""  # data source name, e.g. "jlc-api"
    fetched_at: str | None = None  # ISO-8601 UTC
    raw: dict = field(default_factory=dict)  # the source row, unmodified


@runtime_checkable
class DataSource(Protocol):
    """A component data source (live catalog API, discovery index, cache)."""

    name: str

    def verify(self, refs: Sequence[str]) -> dict[str, PartFact]:
        """Live-verify refs (ONE batched call where the source allows it).

        Returns a fact for every requested ref — ``found=False`` when the
        catalog doesn't know it, never a missing key.
        """
        ...

    def discover(self, query: dict) -> list[dict]:
        """Search for candidate parts. Rows are advisory until verified."""
        ...
