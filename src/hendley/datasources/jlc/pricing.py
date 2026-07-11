"""JLC price-tier arithmetic (the ``priceRanges`` shape from the detail API)."""

from __future__ import annotations


def unit_price_at_qty(detail: dict | None, qty: int = 1) -> float | None:
    """Unit price at the ``priceRanges`` break that applies to ``qty``.

    Picks the range with the largest ``startQuantity`` <= qty; if none applies
    (all breaks start above qty), falls back to the lowest break.
    """
    ranges = (detail or {}).get("priceRanges") or []
    applicable = [p for p in ranges
                  if int(p.get("startQuantity") or 0) <= qty
                  and p.get("unitPrice") is not None]
    if applicable:
        return max(applicable, key=lambda p: int(p.get("startQuantity") or 0)).get("unitPrice")
    if ranges:
        return min(ranges, key=lambda p: int(p.get("startQuantity") or 0)).get("unitPrice")
    return None
