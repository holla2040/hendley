"""Alternate-part discovery: jlcsearch *discover* → official-API *verify* → trade-off.

The official JLCPCB API cannot search — it only verifies codes you already hold
(``getComponentDetailByCode``). So finding an alternate is a two-source job:

1. **Discover** candidate codes from the third-party parametric index at
   ``jlcsearch.tscircuit.com`` (a scraped, queryable mirror of the whole JLC
   catalog). One ``GET /<category>/list.json?<params>`` returns up to ~100 rows.
2. **Verify** *every* returned code against the live JLC API in one batched
   ``getComponentDetailByCode`` call (≤1000 codes/call) for authoritative
   ``stockCount`` / ``priceRanges`` / ``parameters`` / ``libraryType``.

This module deliberately **does not rank or pick**. jlcsearch's stock is a stale
cached snapshot — observed swinging both directions vs. live (a resistor listed
at 1.9M was really 474k; a MOSFET listed at 55k was really 252k) — so its order
is not trustworthy and is surfaced as-is, not as a recommendation. The
multi-dimensional trade-off (inventory vs. price vs. spec margin vs. package) is
a judgment left to the caller (Claude in the loop, or the user) acting on the
*verified* data returned here.

Two empirical gotchas baked into the design:

- **Package strings must match the jlcsearch value exactly** (``DFN-8(3x3)`` not
  ``DFN-8``; ``0402``). ``requests`` URL-encodes the params dict, so pass the raw
  string.
- **Numeric ``_min``/``_max`` query params are unreliable on semiconductors** —
  jlcsearch's structured numeric columns are sparsely populated (MOSFET drain
  current was filled on ~1/3 of rows), and a ``_min`` filter silently drops the
  null rows. Passive value fields (``resistance``, ``capacitance``) are dense.
  So discover broadly (by package + dense value field), then let the hard numeric
  filter live in the caller's judgment on the verified ``parameters[]`` — not in
  the jlcsearch query.
"""

from __future__ import annotations

import json
import os
from typing import Any, Callable, Iterable

from .client import JLCClient

# The jlcsearch index host. Override for testing / mirrors via env.
JLCSEARCH_BASE = os.environ.get("HENDLEY_JLCSEARCH", "https://jlcsearch.tscircuit.com")

# Known jlcsearch category slugs (the path segment before ``/list.json``).
# Used for ``--list-categories`` and a helpful error; validation is *soft* — an
# unrecognised slug is still attempted (the index is updated more often than this
# list), and only a failed fetch raises. Sourced from the jlcsearch site nav plus
# the OpenAPI spec's generic ``components`` route.
CATEGORIES: tuple[str, ...] = (
    "accelerometers",
    "adcs",
    "analog_multiplexers",
    "analog_switches",
    "arm_processors",
    "battery_holders",
    "bjt_transistors",
    "boost_converters",
    "buck_boost_converters",
    "capacitors",
    "components",  # generic fallback: subcategory_name / search / package
    "dacs",
    "diodes",
    "footprint_index",
    "fpc_connectors",
    "fpgas",
    "fuses",
    "gas_sensors",
    "gyroscopes",
    "headers",
    "io_expanders",
    "jst_connectors",
    "lcd_display",
    "ldos",
    "led_dot_matrix_display",
    "led_drivers",
    "led_segment_display",
    "led_with_ic",
    "leds",
    "microcontrollers",
    "microphones",
    "mosfets",
    "oled_display",
    "pcie_m2_connectors",
    "potentiometers",
    "relays",
    "resistor_arrays",
    "resistors",
    "risc_v_processors",
    "switches",
    "usb_c_connectors",
    "voltage_regulators",
    "wifi_modules",
    "wire_to_board_connectors",
)

# A fetch callable: (url, params) -> decoded JSON dict. Injectable for tests.
Fetch = Callable[[str, dict[str, Any]], Any]


def _default_fetch(url: str, params: dict[str, Any]) -> Any:
    """Default discovery fetch: a plain signed-less GET against jlcsearch."""
    import requests  # local import keeps the dep optional at import time

    resp = requests.get(
        url,
        params=params,
        timeout=20.0,
        headers={"Accept": "application/json", "User-Agent": "hendley/0.1.0"},
    )
    resp.raise_for_status()
    return resp.json()


def normalize_code(value: Any) -> str:
    """Coerce a jlcsearch ``lcsc`` (int or str) into a JLC ``Cxxxx`` code."""
    s = str(value).strip()
    if not s:
        return s
    return s if s[:1] in ("C", "c") else f"C{s}"


def _extract_rows(doc: Any, category: str) -> list[dict]:
    """Pull the candidate row list out of a jlcsearch list.json response.

    The list usually lives under a key equal to the category slug, but that
    isn't guaranteed for every category, so fall back to the sole list-valued
    entry in the object.
    """
    if not isinstance(doc, dict):
        raise ValueError(f"jlcsearch returned a non-object response for {category!r}")
    rows = doc.get(category)
    if isinstance(rows, list):
        return rows
    lists = [v for v in doc.values() if isinstance(v, list)]
    if len(lists) == 1:
        return lists[0]
    raise ValueError(
        f"could not locate the candidate list in the jlcsearch response for "
        f"{category!r} (keys: {sorted(doc)})"
    )


def _parse_attributes(raw: Any) -> dict:
    """jlcsearch stores per-part specs as a JSON *string*; decode it leniently."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            val = json.loads(raw)
            return val if isinstance(val, dict) else {}
        except ValueError:
            return {}
    return {}


def fetch_candidates(
    category: str,
    params: dict[str, Any],
    *,
    fetch: Fetch = _default_fetch,
) -> list[dict]:
    """Discover candidate parts from jlcsearch for one category.

    Returns the rows **in the index's own order** (no re-ranking) normalised to a
    small common shape. ``params`` are passed through verbatim (jlcsearch ignores
    unknown keys), so the caller controls the hard filter.
    """
    url = f"{JLCSEARCH_BASE.rstrip('/')}/{category}/list.json"
    doc = fetch(url, params)
    rows = _extract_rows(doc, category)
    out: list[dict] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        out.append(
            {
                "code": normalize_code(r.get("lcsc")),
                "mfr": r.get("mfr"),
                "package": r.get("package"),
                "jlcsearch_stock": r.get("stock"),
                "price1": r.get("price1"),
                "is_basic": bool(r.get("is_basic")),
                "is_preferred": bool(r.get("is_preferred")),
                "in_stock": r.get("in_stock"),
                "attributes": _parse_attributes(r.get("attributes")),
            }
        )
    return out


def _unit_price_at_qty1(detail: dict | None) -> float | None:
    """The unit price for a single unit, from the official ``priceRanges``."""
    ranges = (detail or {}).get("priceRanges") or []
    for pr in ranges:
        if pr.get("startQuantity") in (1, "1"):
            return pr.get("unitPrice")
    if ranges:
        return min(ranges, key=lambda p: p.get("startQuantity") or 0).get("unitPrice")
    return None


def _summarize_target(code: str, detail: dict | None) -> dict:
    """Reference summary for the part being replaced."""
    d = detail or {}
    return {
        "code": code,
        "model": d.get("componentModel"),
        "package": d.get("componentSpecification"),
        "verified": detail is not None,
        "liveStock": d.get("stockCount"),
        "unitPrice1": _unit_price_at_qty1(detail),
        "libraryType": d.get("libraryType"),
        "description": d.get("description"),
        "parameters": d.get("parameters"),
        "datasheetUrl": d.get("datasheetUrl"),
    }


def discover_and_verify(
    target_code: str,
    category: str,
    params: dict[str, Any],
    client: JLCClient,
    *,
    fetch: Fetch = _default_fetch,
) -> dict:
    """Discover alternates from jlcsearch and verify every hit against the live API.

    The target itself is excluded from the candidate list (it is summarised
    separately for comparison). Returns::

        {
          "target": {...summary...},
          "category": str,
          "params": {...},
          "totalFound": int,        # candidates discovered (excl. target)
          "candidates": [ {code, model, package, verified, liveStock,
                           jlcsearchStock, unitPrice1, libraryType, isBasic,
                           description, parameters, attributes, datasheetUrl}, ... ],
        }

    ``candidates`` preserve jlcsearch's order. No ranking or filtering is applied
    here beyond the spoken ``params`` — that is the caller's job.
    """
    target_code = normalize_code(target_code)
    discovered = fetch_candidates(category, params, fetch=fetch)
    # Drop the target's own listing; keep the rest in index order.
    candidates = [c for c in discovered if c["code"] != target_code]

    # One batched verify call covers the target + every candidate.
    codes: list[str] = [target_code]
    for c in candidates:
        if c["code"] and c["code"] not in codes:
            codes.append(c["code"])
    details_list = client.get_component_detail_by_code(codes) or []
    details = {d.get("componentCode"): d for d in details_list}

    rows: list[dict] = []
    for c in candidates:
        d = details.get(c["code"])
        rows.append(
            {
                "code": c["code"],
                "model": (d or {}).get("componentModel") or c["mfr"],
                "mfr": c["mfr"],
                "package": (d or {}).get("componentSpecification") or c["package"],
                "verified": d is not None,
                "liveStock": (d or {}).get("stockCount"),
                "jlcsearchStock": c["jlcsearch_stock"],
                "unitPrice1": _unit_price_at_qty1(d) if d else c.get("price1"),
                "libraryType": (d or {}).get("libraryType"),
                "isBasic": c["is_basic"],
                "description": (d or {}).get("description"),
                "parameters": (d or {}).get("parameters"),
                "attributes": c["attributes"],
                "datasheetUrl": (d or {}).get("datasheetUrl"),
            }
        )

    return {
        "target": _summarize_target(target_code, details.get(target_code)),
        "category": category,
        "params": dict(params),
        "totalFound": len(candidates),
        "candidates": rows,
    }


# -- human-readable report ----------------------------------------------------

_LIB_LABEL = {"base": "Basic", "expand": "Extended"}


def _fmt_stock(v: Any) -> str:
    return f"{v:,}" if isinstance(v, int) else "—"


def _fmt_money(v: Any) -> str:
    return f"${v:.4f}" if isinstance(v, (int, float)) else "$—"


def _fmt_lib(row: dict) -> str:
    lib = row.get("libraryType")
    if lib:
        return _LIB_LABEL.get(lib, lib)
    return "Basic" if row.get("isBasic") else ""


def _fmt_params(params: dict) -> str:
    return ", ".join(f"{k}={v}" for k, v in params.items()) if params else "no filter"


def _stale_note(live: Any, idx: Any) -> str:
    """Flag a large divergence between live and jlcsearch-indexed stock."""
    if isinstance(live, int) and isinstance(idx, int) and idx > 0:
        ratio = live / idx
        if ratio < 0.5 or ratio > 2:
            return f" (idx {_fmt_stock(idx)}, stale)"
    return ""


def _candidate_line(c: dict) -> str:
    model = (c.get("model") or "")[:20]
    pkg = (c.get("package") or "")[:16]
    live = c.get("liveStock")
    stock = _fmt_stock(live) + _stale_note(live, c.get("jlcsearchStock"))
    lib = _fmt_lib(c)
    flag = "" if c.get("verified") else "  [UNVERIFIED]"
    return (
        f"  {c['code']:<11} {model:<20} {pkg:<16} "
        f"stock {stock:<22} {_fmt_money(c.get('unitPrice1')):>9}  {lib}{flag}"
    )


def format_alternates_report(result: dict, *, top: int | None = None) -> str:
    """Render :func:`discover_and_verify` output as a human-readable trade-off table.

    ``top`` caps how many candidates are shown (in index order) with a "showing
    N of M" note; ``None`` or ``0`` shows all. The output is explicitly *not* a
    recommendation — the caller weighs the dimensions.
    """
    t = result["target"]
    cands = result["candidates"]
    total = len(cands)

    head = f"Alternates for {t['code']}"
    if t.get("model"):
        head += f" — {t['model']}"
    if t.get("package"):
        head += f" [{t['package']}]"
    head += f"  (category: {result['category']})"
    lines = [head, ""]

    tgt_stock = _fmt_stock(t.get("liveStock"))
    tgt_lib = _LIB_LABEL.get(t.get("libraryType"), t.get("libraryType") or "")
    lines.append(
        f"TARGET (live): stock {tgt_stock}, {_fmt_money(t.get('unitPrice1'))}@1"
        + (f", {tgt_lib}" if tgt_lib else "")
        + ("" if t.get("verified") else "   [NOT FOUND in live API]")
    )
    if t.get("description"):
        lines.append(f"        {t['description']}")
    lines.append("")

    filt = _fmt_params(result.get("params") or {})
    lines.append(
        f"Discovered {total} candidate(s) via jlcsearch ({filt}); "
        "verified against the live JLC API."
    )
    lines.append(
        "Order is jlcsearch's index order (stale) — NOT a recommendation. "
        "Weigh live stock / price / spec margin / package yourself."
    )

    shown = cands if not top else cands[:top]
    if top and total > len(shown):
        lines.append(f"(showing first {len(shown)} of {total}; use --top 0 or --json for all)")
    lines.append("")

    for c in shown:
        lines.append(_candidate_line(c))
        if c.get("description"):
            lines.append(f"        {c['description']}")

    unverified = [c["code"] for c in cands if not c["verified"]]
    if unverified:
        lines.append("")
        lines.append(
            "In jlcsearch but NOT returned by the live API "
            f"(stale/delisted — treat with caution): {', '.join(unverified)}"
        )
    return "\n".join(lines)


def parse_param_args(items: Iterable[str]) -> dict[str, str]:
    """Parse ``key=value`` CLI ``--param`` items into a query-params dict."""
    params: dict[str, str] = {}
    for item in items:
        if "=" not in item:
            raise ValueError(f"--param must be KEY=VALUE, got {item!r}")
        key, value = item.split("=", 1)
        key = key.strip()
        if not key:
            raise ValueError(f"--param has an empty key: {item!r}")
        params[key] = value
    return params
