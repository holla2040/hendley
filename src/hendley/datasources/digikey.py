"""DigiKeyDataSource — "can a US house buy this MPN?" (ADR-0010).

Product Information API v4, 2-legged OAuth (client credentials). Contract
taken from DigiKey's published OpenAPI file (2026-10-19):

- token:  ``POST https://api.digikey.com/v1/oauth2/token``
- search: ``POST https://api.digikey.com/products/v4/search/keyword``
  body ``{"Keywords": mpn, "Limit": n}`` → ``{"Products", "ExactMatches", ...}``

``verify()`` is keyed by **MPN**, not a DigiKey number: one keyword search per
MPN, keeping only a product whose ``ManufacturerProductNumber`` equals it.
A keyword hit on a different part is not this part — it is ``found=False``.
Free tier: 1000 requests/day, 120/minute. No discovery; JLC discovers.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from typing import Any

import requests

from ..config import optional_key
from .base import PartFact

TOKEN_URL = "https://api.digikey.com/v1/oauth2/token"
SEARCH_URL = "https://api.digikey.com/products/v4/search/keyword"

Post = Callable[..., Any]


class DigiKeyDataSource:
    name = "digikey"

    def __init__(self, client_id: str | None = None,
                 client_secret: str | None = None, *,
                 post: Post = requests.post, timeout: float = 30.0):
        self.client_id = client_id or optional_key("DigiKeyClientId", "DIGIKEY_CLIENT_ID")
        self.client_secret = client_secret or optional_key(
            "DigiKeyClientSecret", "DIGIKEY_CLIENT_SECRET")
        self._post = post
        self.timeout = timeout
        self._token: str | None = None
        self._expires = 0.0

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    def _bearer(self) -> str:
        if self._token and time.time() < self._expires:
            return self._token
        resp = self._post(TOKEN_URL, data={
            "client_id": self.client_id, "client_secret": self.client_secret,
            "grant_type": "client_credentials"}, timeout=self.timeout)
        resp.raise_for_status()
        doc = resp.json()
        self._token = doc["access_token"]
        self._expires = time.time() + int(doc.get("expires_in", 600)) - 30
        return self._token

    def _search(self, mpn: str) -> list[dict]:
        resp = self._post(SEARCH_URL, json={"Keywords": mpn, "Limit": 10}, headers={
            "Authorization": f"Bearer {self._bearer()}",
            "X-DIGIKEY-Client-Id": self.client_id,
            "X-DIGIKEY-Locale-Site": "US",
            "X-DIGIKEY-Locale-Language": "en",
            "X-DIGIKEY-Locale-Currency": "USD",
        }, timeout=self.timeout)
        resp.raise_for_status()
        doc = resp.json()
        return list(doc.get("ExactMatches") or []) + list(doc.get("Products") or [])

    def verify(self, refs: Sequence[str]) -> dict[str, PartFact]:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        out: dict[str, PartFact] = {}
        for mpn in dict.fromkeys(r.strip() for r in refs if r and r.strip()):
            hit = next((p for p in self._search(mpn)
                        if str(p.get("ManufacturerProductNumber") or "").casefold()
                        == mpn.casefold()), None)
            if hit is None:
                out[mpn] = PartFact(ref=mpn, found=False, provenance=self.name,
                                    fetched_at=now)
                continue
            out[mpn] = PartFact(
                ref=mpn,
                found=True,
                stock=hit.get("QuantityAvailable"),
                mpn=hit.get("ManufacturerProductNumber"),
                manufacturer=(hit.get("Manufacturer") or {}).get("Name"),
                description=(hit.get("Description") or {}).get("ProductDescription"),
                lifecycle=(hit.get("ProductStatus") or {}).get("Status"),
                price_tiers=_tiers(hit),
                provenance=self.name,
                fetched_at=now,
                raw=hit,
            )
        return out

    def discover(self, query: dict) -> list[dict]:
        return []           # ADR-0010: US distributors verify, JLC discovers


def _buyable(product: dict) -> dict | None:
    """The priced variation with the smallest minimum order (cut tape,
    usually) — the one a prototype or small US build actually buys."""
    variations = [v for v in product.get("ProductVariations") or []
                  if v.get("StandardPricing")]
    if not variations:
        return None
    return min(variations, key=lambda v: v.get("MinimumOrderQuantity") or 0)


def _tiers(product: dict) -> list[dict]:
    v = _buyable(product)
    if v is None:
        return []
    return [{"qty": b.get("BreakQuantity"), "price": b.get("UnitPrice"), "currency": "USD"}
            for b in v["StandardPricing"]]


def offer(fact: PartFact) -> dict:
    """The fields an engineer reads, from a verified fact."""
    raw = fact.raw
    buyable = _buyable(raw) or {}
    return {
        "leadTime": f"{raw['ManufacturerLeadWeeks']} weeks"
        if raw.get("ManufacturerLeadWeeks") else None,
        "datasheetUrl": raw.get("DatasheetUrl"),
        "productUrl": raw.get("ProductUrl"),
        "distributorPart": buyable.get("DigiKeyProductNumber"),
    }
