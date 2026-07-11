"""PCBWay Provider Strategy — MPN-based sourcing, no live stock source."""

from __future__ import annotations

from ...datasources.base import PartFact
from ...domain.model import Check, RequirementLine, RequirementsBom, make_check


class PCBWayStrategy:
    """Resolve to manufacturer part numbers; availability is unverified.

    ``requires_live_stock = False``: spec lines take the first AVL choice with
    a usable identity (an MPN, or a recorded ``pcbway`` ref) and carry an
    ``unverified`` warning — PCBWay confirms sourcing on their side.
    """

    provider = "pcbway"
    offer_type = "pcbway-sourced"
    requires_live_stock = False

    def query_context(self, requirements: RequirementsBom,
                      candidate_refs: list[str]) -> list[str]:
        return []  # nothing is live-verifiable — never pretend otherwise

    def evaluate(self, line: RequirementLine, fact: PartFact | None,
                 required_qty: int) -> tuple[bool, list[Check]]:
        desigs = ",".join(line.designators)
        if line.mpn or line.provider_ref(self.provider):
            what = line.mpn or line.provider_ref(self.provider)
            return True, [make_check(
                "unverified",
                f"{desigs}: {what} — PCBWay availability is not live-verifiable; "
                "confirm sourcing with the provider")]
        return False, [make_check(
            "no-code-uncheckable",
            f"{desigs}: no MPN and no PCBWay ref — nothing PCBWay can source")]

    def score(self, candidate: dict, required_qty: int) -> list[dict]:
        return []  # no provider-specific ranking signal without provider data
