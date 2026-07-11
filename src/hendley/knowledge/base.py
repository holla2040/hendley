"""The KnowledgeStore contract — deliberate engineering decisions, persisted.

The store records what the engineer approved (House Parts and their ranked
Part Choices) and what happened to those decisions (audit trail). Rank is
deliberate: nothing in the system reorders an AVL (ADR-0001) — the store's
verbs mutate rank only on explicit instruction.

Storage is SQLite (ADR-0002); this Protocol keeps consumers
storage-agnostic. Advisory stock/price caches held by the store are for
display only — never order against them (live verification is the resolver's
job).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain.model import SpecKey


@runtime_checkable
class KnowledgeStore(Protocol):
    """House Parts + ranked Part Choices + audit trail."""

    def lookup(self, spec: SpecKey) -> dict | None:
        """House Part + rank-ordered active choices for a spec, or None."""
        ...

    def record(self, spec: SpecKey, *, mpn: str | None = None,
               manufacturer: str | None = None,
               provider_refs: dict[str, str] | None = None,
               rank: int = 1, description: str | None = None,
               design: str | None = None, note: str | None = None) -> dict:
        """Approve a Part Choice (rank 1 = promotion; re-recording promotes)."""
        ...

    def rerank(self, spec: SpecKey, choice_id: int, rank: int) -> dict:
        """Deliberately move a choice within the AVL."""
        ...

    def remove_choice(self, spec: SpecKey, choice_id: int,
                      note: str | None = None) -> dict:
        """State change to 'removed' — never a delete."""
        ...

    def history(self, spec: SpecKey) -> list[dict]:
        """Audit trail for a House Part, newest first."""
        ...

    def list_parts(self, kind: str | None = None) -> list[dict]:
        ...

    def update_verified(self, provider: str, ref: str, stock: int | None,
                        price: float | None, *, mpn: str | None = None,
                        manufacturer: str | None = None) -> None:
        """Refresh the advisory cache (and backfill identity) after a live verify."""
        ...
