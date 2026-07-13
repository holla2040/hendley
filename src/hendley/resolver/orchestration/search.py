"""The engineer's search: a coarse net, then an honest sieve.

The parts index cannot be trusted to filter. It honours ``package`` and one
value param (``resistance``/``capacitance``) and **silently ignores every
other param it is given** — an unknown name is not an error, it just returns
100 unfiltered rows that look filtered. A "10uF 0805 X7R 25V" query comes
back with a 100nF 50V X5R part at the top, and nothing in the response says
so. So a search that trusts its own query ships the wrong part.

Hence: the agent's plan carries a **net** (the few params the index really
honours — a way to fetch fewer rows) and a **sieve** (EVERY constraint,
including the net's own). Python fires the net, then proves each candidate
against the sieve using data it holds: the index row's typed columns, the
row's ``attributes`` JSON, and the live-verified ``parameters``. A candidate
that cannot be PROVEN to satisfy a term is not a result — it goes to
``misses`` with the reason, where the engineer can see it and judge.

Python composes nothing and parses no names (ADR-0006): the agent wrote the
terms, this module only compares. The one thing it adds is re-asserting the
agent's own net params as sieve terms (``NET_COLUMNS``), so a param the
index quietly dropped still cannot leak a wrong part through.
"""

from __future__ import annotations

import json
import math
from typing import Any

from ...datasources.base import DataSource
from .queue import _verify_rows

# The agent's net params, mapped to the column that proves them. Re-asserted
# in the sieve so a silently-ignored param is caught rather than trusted.
NET_COLUMNS = {
    "package": "package",
    "resistance": "resistance",
    "capacitance": "capacitance_farads",
}

NUMERIC_OPS = ("lte", "gte", "lt", "gt")


def run_search(datasource: DataSource, plan: dict,
               exclude: tuple[str, ...] = ()) -> dict:
    """Execute an agent search plan. Returns::

        {"candidates": [...],   # verified AND proven against every term
         "misses": [...],       # found, but a term failed or can't be checked
         "scanned": int, "truncated": bool}

    ``candidates`` carry the queue's candidate shape (same table as
    everywhere else); ``misses`` add ``failed: [{field, why}]``. ``query`` is
    the request that was actually sent and ``proved`` the terms every result
    had to satisfy — both go on screen: a query the engineer cannot see is a
    query they cannot correct.
    """
    query = _query(plan)
    rows = datasource.discover(query) if query else []
    if plan.get("mode") == "code":
        code = str((plan.get("net") or {}).get("code") or "").strip().upper()
        rows = [{"code": code}] if code else []
    truncated = len(rows) >= 100          # the index caps a category listing
    cands = _verify_rows(datasource, rows, set(exclude))
    by_code = {r["code"]: r for r in rows if r.get("code")}
    sieve = _full_sieve(plan)

    candidates: list[dict] = []
    misses: list[dict] = []
    for c in cands:
        if not c["verified"]:
            misses.append({**c, "failed": [
                {"field": "stock", "why": "not in the live catalog"}]})
            continue
        failed = _sift(sieve, by_code.get(c["code"], {}), c)
        if failed:
            misses.append({**c, "failed": failed})
        else:
            candidates.append(c)
    return {"candidates": candidates, "misses": misses, "query": query,
            "proved": sieve, "scanned": len(cands), "truncated": truncated}


def _query(plan: dict) -> dict | None:
    """The request this plan sends, verbatim. The plan owns it; we only send
    it — and show it."""
    mode = plan.get("mode")
    net = dict(plan.get("net") or {})
    if mode == "code":
        return None                       # a part number needs no discovery
    if mode == "fts":
        search = str(net.get("search") or "").strip()
        return ({"category": "components", "params": {"search": search}}
                if search else None)
    category = str(plan.get("category") or "").strip()
    return {"category": category, "params": net} if category else None


def _full_sieve(plan: dict) -> list[dict]:
    """The agent's sieve, plus its own net params re-asserted as terms."""
    sieve = [dict(p) for p in (plan.get("sieve") or [])]
    if plan.get("mode") != "parametric":
        return sieve            # a keyword/code search states no terms to prove
    stated = {str(p.get("field")) for p in sieve}
    for param, column in NET_COLUMNS.items():
        if param in (plan.get("net") or {}) and column not in stated:
            sieve.append({"field": column, "op": "eq",
                          "value": plan["net"][param], "fromNet": True})
    return sieve


def _sift(sieve: list[dict], row: dict, cand: dict) -> list[dict]:
    """Prove one candidate against every term. Returns the terms it failed —
    including the ones that CANNOT be checked, which are failures too: an
    unprovable part is not a match, it is an unknown."""
    failed = []
    for term in sieve:
        field = str(term.get("field"))
        op = str(term.get("op"))
        want = term.get("value")
        have = _field(field, row, cand)
        if have is None:
            failed.append({"field": field,
                           "why": f"{field} is not published for this part"})
            continue
        ok, why = _compare(have, op, want)
        if not ok:
            failed.append({"field": field, "why": why})
    return failed


STRUCTURAL = ("parameters", "keyParams", "verified", "code")


def _squash(s: Any) -> str:
    return "".join(c for c in str(s).casefold() if c.isalnum())


def _same(a: str, b: str) -> bool:
    """One field, three spellings: the index column ``temperature_coefficient``,
    the catalog attribute ``Temperature Coefficient``, JLC's ``Voltage Rated``.
    Matching the NAME is not parsing the VALUE — the value is still compared
    exactly as it was published."""
    return _squash(a) == _squash(b)


def _field(field: str, row: dict, cand: dict) -> Any:
    """Resolve a term's field over everything we hold, in order of authority:
    the LIVE-verified fact first (the catalog is truth; the index is a
    snapshot), then the index row's typed column, its attributes JSON, and
    finally the verified parameter list. None means nothing we hold can prove
    it — and unprovable is a miss, never a pass."""
    if field not in STRUCTURAL and cand.get(field) is not None:
        return cand[field]
    if row.get(field) is not None:
        return row[field]
    for key, value in _attributes(row).items():
        if _same(key, field):
            return value
    for p in (cand.get("parameters") or []):
        if _same(p.get("parameterName") or "", field):
            return p.get("parameterValue")
    return None


def _attributes(row: dict) -> dict:
    raw = row.get("attributes")
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            got = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return got if isinstance(got, dict) else {}
    return {}


def _compare(have: Any, op: str, want: Any) -> tuple[bool, str]:
    """Compare, never parse. A numeric term against an unparsed catalog string
    ("±1%", "100mW") is NOT quietly coerced — it is reported as uncheckable,
    because guessing at units is how the wrong part gets shipped."""
    if op == "isTrue":
        return bool(have) is True, f"{have!r} is not true"
    if op == "isFalse":
        return bool(have) is False, f"{have!r} is not false"
    if op in ("eq", "ne"):
        if _numeric(have) is not None and _numeric(want) is not None:
            same = math.isclose(_numeric(have), _numeric(want), rel_tol=1e-6)
        else:
            same = str(have).strip().casefold() == str(want).strip().casefold()
        if op == "eq":
            return same, f"is {have!r}, not {want!r}"
        return not same, f"is {want!r}"
    if op == "contains":
        return (str(want).casefold() in str(have).casefold(),
                f"{have!r} does not contain {want!r}")
    if op in NUMERIC_OPS:
        h, w = _numeric(have), _numeric(want)
        if h is None or w is None:
            return False, f"{have!r} can't be compared numerically"
        ok = {"lte": h <= w, "gte": h >= w, "lt": h < w, "gt": h > w}[op]
        sign = {"lte": "≤", "gte": "≥", "lt": "<", "gt": ">"}[op]
        return ok, f"is {have}, not {sign} {want}"
    return False, f"unknown test {op!r}"


def _numeric(v: Any) -> float | None:
    """A number is a number. A string is NOT coerced — '100mW' must not become
    100 (the catalog's power column is milliwatts and its text is not)."""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    return None
