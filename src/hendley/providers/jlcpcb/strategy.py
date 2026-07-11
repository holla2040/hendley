"""JLCPCB/LCSC Provider Strategy — sourcing policy for JLC-mounted assembly."""

from __future__ import annotations

from ...datasources.base import PartFact
from ...domain.model import Check, RequirementLine, RequirementsBom, make_check


class JLCPCBStrategy:
    """Resolve against LCSC/JLC part numbers; one offer type: jlc-mounted."""

    provider = "jlcpcb"
    offer_type = "jlc-mounted"
    requires_live_stock = True

    def query_context(self, requirements: RequirementsBom,
                      candidate_refs: list[str]) -> list[str]:
        return sorted(set(candidate_refs))

    def evaluate(self, line: RequirementLine, fact: PartFact | None,
                 required_qty: int) -> tuple[bool, list[Check]]:
        """Orderable = the JLC catalog knows the ref and has the quantity.

        A line with no JLC ref (MPN-only or nothing) is not orderable here —
        JLC's API can only verify codes, so there is nothing to check.
        """
        desigs = ",".join(line.designators)
        if fact is None:
            what = f"MPN {line.mpn}" if line.mpn else "no spec and no LCSC code"
            return False, [make_check(
                "no-code-uncheckable",
                f"{desigs}: {what} — JLC can only verify LCSC codes")]
        if not fact.found:
            return False, [make_check(
                "not-in-catalog",
                f"{desigs}: {fact.ref} not returned by the JLC catalog")]
        if (fact.stock or 0) < required_qty:
            return False, [make_check(
                "insufficient-stock",
                f"{desigs}: {fact.ref} stock {fact.stock or 0} < required {required_qty}")]
        return True, []

    def score(self, candidate: dict, required_qty: int) -> list[dict]:
        """JLC-only ranking contributions. Generic factors (stock margin,
        price, history) belong to the ranking engine — the strategy adds only
        what is provider-specific."""
        offer = candidate.get("libraryType")
        if offer:
            return [{
                "factor": "offer-class",
                "weight": 0.0,  # displayed, never selected on (fee policy, CLAUDE.md)
                "why": f"JLC {offer} part (loading-fee class — your call, not a rank factor)",
            }]
        return []
