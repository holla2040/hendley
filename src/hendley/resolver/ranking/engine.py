"""The Ranking Engine — orders NEWLY DISCOVERED candidates, nothing else.

Scope per ADR-0001: approved Part Choices never pass through this engine —
the AVL's deliberate rank is authoritative and is walked as recorded. This
ranker exists for the discovery path only: when a line escalates and the
alternates search returns verified candidates, it produces a defensible
ordering with a visible ``why`` for every score (ranking is policy, and
policy must be inspectable — architecture principle "ranking is policy, not
truth").

V1 factors, hardcoded weights (a user-editable ranking config is a recorded
open decision):

- **prior approval** — the candidate is already on this House Part's AVL
  (strongest), or approved on some other House Part (weaker). History
  informs ranking, never eligibility (invariant 8).
- **stock margin** — live stock over required quantity, log-capped. The
  standing sourcing bias: high inventory = popular = supply-chain-safe,
  worth paying a bit more for.
- **price** — relative rank within this candidate set (cheapest earns a few
  points), deliberately weaker than stock margin.
- **strategy contributions** — provider-flavored factors via
  ``ProviderStrategy.score`` (e.g. JLC surfaces the Basic/Extended class at
  weight 0: displayed, never selected on).
"""

from __future__ import annotations

import math

from ...domain.model import SpecKey
from ...knowledge.partsdb import PartsDb
from ...providers.base import ProviderStrategy

W_PRIOR_SAME_SPEC = 50.0
W_PRIOR_ELSEWHERE = 20.0
W_STOCK_CAP = 30.0
W_PRICE_BEST = 8.0


def _prior_approval(store: PartsDb | None, spec: SpecKey | None,
                    provider: str, code: str | None) -> tuple[float, str] | None:
    if store is None or not code:
        return None
    if spec is not None:
        house = store.lookup(spec)
        if house and any(c["providerRefs"].get(provider) == code
                         for c in house["choices"]):
            return W_PRIOR_SAME_SPEC, "already an approved choice on this House Part"
    row = store.conn.execute(
        "SELECT c.id FROM part_choices c JOIN choice_provider_ids p "
        "ON p.choice_id=c.id WHERE p.provider=? AND p.provider_ref=? "
        "AND c.state='active' LIMIT 1", (provider, code)).fetchone()
    if row:
        return W_PRIOR_ELSEWHERE, "previously approved on another House Part"
    return None


def rank_candidates(
    candidates: list[dict],
    *,
    required_qty: int,
    strategy: ProviderStrategy,
    store: PartsDb | None = None,
    spec: SpecKey | None = None,
) -> list[dict]:
    """Return candidates ordered best-first, each with ``score`` and ``why``.

    Deterministic for identical inputs. Input rows are the constraint-engine
    survivors (verified discovery candidates).
    """
    by_price = sorted(
        (c for c in candidates if c.get("unitPrice1") is not None),
        key=lambda c: c["unitPrice1"])
    price_rank = {c["code"]: i for i, c in enumerate(by_price)}

    ranked: list[dict] = []
    for c in candidates:
        contributions: list[dict] = []

        prior = _prior_approval(store, spec, strategy.provider, c.get("code"))
        if prior:
            weight, why = prior
            contributions.append({"factor": "prior-approval", "weight": weight,
                                  "why": why})

        stock = int(c.get("liveStock") or 0)
        if required_qty > 0 and stock >= required_qty:
            margin = stock / required_qty
            weight = min(W_STOCK_CAP, 10.0 * math.log10(margin) + 10.0)
            contributions.append({
                "factor": "stock-margin", "weight": round(weight, 2),
                "why": f"live stock {stock} = {margin:.0f}x the required {required_qty}"})
        elif stock:
            contributions.append({
                "factor": "stock-short", "weight": 0.0,
                "why": f"live stock {stock} < required {required_qty} — "
                       "cannot cover this build alone"})

        if c.get("code") in price_rank and len(by_price) > 1:
            i = price_rank[c["code"]]
            weight = W_PRICE_BEST * (len(by_price) - 1 - i) / (len(by_price) - 1)
            contributions.append({
                "factor": "price", "weight": round(weight, 2),
                "why": f"unit price {c['unitPrice1']} — "
                       f"#{i + 1} of {len(by_price)} by price"})

        contributions.extend(strategy.score(c, required_qty))

        score = round(sum(x["weight"] for x in contributions), 2)
        ranked.append({**c, "score": score,
                       "why": [x["why"] for x in contributions],
                       "scoreContributions": contributions})

    ranked.sort(key=lambda c: (-c["score"], -(c.get("liveStock") or 0),
                               c.get("code") or ""))
    return ranked
