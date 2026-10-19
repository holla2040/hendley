"""MouserDataSource — "can a US house buy this MPN?" (ADR-0010).

Search API v1, API key in the query string. Contract taken from Mouser's
published Swagger file (2026-10-19):

- ``POST https://api.mouser.com/api/v1/search/partnumber?apiKey=<key>``
  body ``{"SearchByPartRequest": {"mouserPartNumber": "A|B|C",
  "partSearchOptions": "Exact"}}`` — up to 10 numbers per call, pipe-joined.
  Despite the name, the field matches manufacturer part numbers too.

``verify()`` is keyed by **MPN**: a returned part counts only if its
``ManufacturerPartNumber`` equals the MPN asked for. Free tier: 1000
calls/day, 30/minute. No discovery; JLC discovers.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from typing import Any

import requests

from ..config import optional_key
from .base import PartFact

SEARCH_URL = "https://api.mouser.com/api/v1/search/partnumber"
BATCH = 10

Post = Callable[..., Any]


class MouserDataSource:
    name = "mouser"

    def __init__(self, api_key: str | None = None, *,
                 post: Post = requests.post, timeout: float = 30.0):
        self.api_key = api_key or optional_key("MouserApiKey", "MOUSER_API_KEY")
        self._post = post
        self.timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def _search(self, mpns: list[str]) -> list[dict]:
        resp = self._post(SEARCH_URL, params={"apiKey": self.api_key}, json={
            "SearchByPartRequest": {"mouserPartNumber": "|".join(mpns),
                                    "partSearchOptions": "Exact"}},
            timeout=self.timeout)
        try:
            resp.raise_for_status()
        except requests.HTTPError:
            # requests puts the URL in the message, and the URL carries the key
            raise RuntimeError(f"Mouser: HTTP {resp.status_code}") from None
        doc = resp.json()
        errors = doc.get("Errors") or []
        if errors:
            raise RuntimeError(f"Mouser: {errors[0].get('Message') or errors[0]}")
        return list((doc.get("SearchResults") or {}).get("Parts") or [])

    def verify(self, refs: Sequence[str]) -> dict[str, PartFact]:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        mpns = list(dict.fromkeys(r.strip() for r in refs if r and r.strip()))
        parts: list[dict] = []
        for i in range(0, len(mpns), BATCH):
            parts += self._search(mpns[i:i + BATCH])
        out: dict[str, PartFact] = {}
        for mpn in mpns:
            # Mouser lists one MPN under several Mouser numbers (reel, cut
            # tape); the stocked listing is the one a buyer would use.
            hits = [p for p in parts if str(p.get("ManufacturerPartNumber") or "")
                    .casefold() == mpn.casefold()]
            if not hits:
                out[mpn] = PartFact(ref=mpn, found=False, provenance=self.name,
                                    fetched_at=now)
                continue
            hit = max(hits, key=lambda p: _stock(p) or 0)
            out[mpn] = PartFact(
                ref=mpn,
                found=True,
                stock=_stock(hit),
                mpn=hit.get("ManufacturerPartNumber"),
                manufacturer=hit.get("Manufacturer"),
                description=hit.get("Description"),
                # Mouser publishes this only for flagged parts ("New Product",
                # "Not Recommended for New Designs", "Obsolete"); an ordinary
                # active part reads null. Null is passed on, never guessed.
                lifecycle=hit.get("LifecycleStatus"),
                price_tiers=[{"qty": b.get("Quantity"), "price": _money(b.get("Price")),
                              "currency": b.get("Currency")}
                             for b in hit.get("PriceBreaks") or []],
                provenance=self.name,
                fetched_at=now,
                raw=hit,
            )
        return out

    def discover(self, query: dict) -> list[dict]:
        return []           # ADR-0010: US distributors verify, JLC discovers


def _stock(part: dict) -> int | None:
    """``AvailabilityInStock`` is a string count ("12345"); ``Availability`` is
    prose ("12,345 In Stock"). Prefer the count; read the prose only when it
    is exactly a number followed by "In Stock"."""
    raw = part.get("AvailabilityInStock")
    if raw not in (None, ""):
        try:
            return int(str(raw).replace(",", ""))
        except ValueError:
            pass
    m = re.fullmatch(r"\s*([\d,]+)\s+In Stock\s*", str(part.get("Availability") or ""))
    return int(m.group(1).replace(",", "")) if m else None


def _money(text: Any) -> float | None:
    """``"$0.28"`` → 0.28. Anything else is None, never a guess."""
    m = re.fullmatch(r"\s*\$?\s*([\d,]*\.?\d+)\s*", str(text or ""))
    return float(m.group(1).replace(",", "")) if m else None


def offer(fact: PartFact) -> dict:
    """The fields an engineer reads, from a verified fact."""
    raw = fact.raw
    return {
        "leadTime": raw.get("LeadTime") or None,
        "datasheetUrl": raw.get("DataSheetUrl") or None,
        "productUrl": raw.get("ProductDetailUrl") or None,
        "distributorPart": raw.get("MouserPartNumber") or None,
    }
