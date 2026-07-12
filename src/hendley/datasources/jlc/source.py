"""JLCDataSource — the official JLC API behind the DataSource contract.

``verify()`` is ONE batched ``getComponentDetailByCode`` call for all refs
(≤1000/call); ``discover()`` is the jlcsearch parametric index (advisory —
its stock is a stale snapshot; always verify before trusting numbers).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence

from ..base import PartFact
from .client import JLCClient


def _brand_from_manual_url(detail: dict) -> str | None:
    """The LCSC brand slug embedded in the datasheet filename — the official
    API's only manufacturer signal (no dedicated field exists).

    Filename shape: ``<digits>_<brand>-<MPN>_<Ccode>.pdf``. The MPN
    (``componentModel``) and code anchor the parse; any mismatch returns
    None — a manufacturer is never fabricated. The slug is lowercase
    ("yageo", not "YAGEO"); user-recorded names always take precedence
    downstream (update_verified backfills NULLs only).
    """
    url = detail.get("dataManualUrl") or ""
    code = detail.get("componentCode") or ""
    mpn = detail.get("componentModel") or ""
    if not (url and code and mpn):
        return None
    name = url.rsplit("/", 1)[-1]
    suffix = f"_{code}.pdf"
    if not name.endswith(suffix):
        return None
    stem = name[: -len(suffix)]
    ts, _, rest = stem.partition("_")
    if not ts.isdigit() or not rest.endswith(f"-{mpn}"):
        return None
    return rest[: -len(mpn) - 1] or None


class JLCDataSource:
    """Live JLC catalog facts + jlcsearch discovery."""

    name = "jlc-api"

    def __init__(self, client: JLCClient | None = None):
        self._client = client

    @property
    def client(self) -> JLCClient:
        if self._client is None:
            self._client = JLCClient()
        return self._client

    def verify(self, refs: Sequence[str]) -> dict[str, PartFact]:
        refs = sorted(set(refs))
        if not refs:
            return {}
        fetched = self.client.get_component_detail_by_code(list(refs)) or []
        details = {d.get("componentCode"): d for d in fetched}
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        out: dict[str, PartFact] = {}
        for ref in refs:
            d = details.get(ref)
            if d is None:
                out[ref] = PartFact(ref=ref, found=False, provenance=self.name,
                                    fetched_at=now)
            else:
                out[ref] = PartFact(
                    ref=ref,
                    found=True,
                    stock=d.get("stockCount"),
                    mpn=d.get("componentModel"),
                    manufacturer=_brand_from_manual_url(d),
                    description=d.get("describe"),
                    offer_class=d.get("libraryType"),
                    price_tiers=list(d.get("priceRanges") or []),
                    provenance=self.name,
                    fetched_at=now,
                    raw=d,
                )
        return out

    def discover(self, query: dict) -> list[dict]:
        """jlcsearch candidate rows for ``{"category": slug, "params": {...}}``."""
        from .alternates import fetch_candidates

        q = dict(query)
        category = q.pop("category")
        params = q.pop("params", q)  # accept flat or nested param form
        return fetch_candidates(category, params)
