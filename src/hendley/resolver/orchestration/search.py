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
against the sieve using data it holds: the live-verified fact, the index
row's typed columns, and the catalog's own ``parameters``. A candidate that
cannot be PROVEN to satisfy a term is not a result — it goes to ``misses``
with the reason, where the engineer can see it and judge.

**The sieve speaks the CATALOG's language, not the index's.** The official
API publishes a part's specs as normalized name/value pairs — ``Capacitance``,
``Voltage Rating``, ``Diameter``, ``Height - Seated (Max)`` — and the SAME
names come back for every manufacturer. The index's ``attributes`` blob is a
scrape of the raw datasheet keys and they drift wildly (across 680 sampled
electrolytics, diameter is ``φD`` on 583 rows, ``Diameter`` on 62, absent on
35), so it is NOT consulted: it can only ever answer worse than the parameters
we already fetched, and a key it happens to miss would be recorded as an
honest-looking miss on a part that in fact matches.

Python composes nothing and parses no names (ADR-0006): the agent wrote the
terms, this module only compares. It adds exactly two things — re-asserting
the agent's own net params as sieve terms (``NET_COLUMNS``), so a param the
index quietly dropped cannot leak a wrong part through; and coercing a
catalog string against a unit **the agent declared** (``"63V"`` + ``unit:
"V"`` → 63), so "50 V or better" is expressible at all. Python never guesses
a unit — it only checks the string conforms to the one it was handed.
"""

from __future__ import annotations

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

# One field, two vocabularies that do NOT collapse to the same name on their
# own. The index's ``tolerance_fraction`` IS the catalog's ``Tolerance`` (0.01
# is "±1%"), and without this the term proves SILENTLY: it earns no column,
# because a column is only granted to a field the catalog names — so the
# engineer sets 0.01, reads "±0.1%" in a read-only column, and nothing on
# screen connects the two.
#
# ``capacitance_farads`` is deliberately NOT aliased: a capacitor states
# ``Capacitance`` as its own term (docs/parts/aluminium-electrolytic-…), and an
# alias here would hand one field two columns.
CATALOG_ALIAS = {"tolerancefraction": "Tolerance"}


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
            misses.append({**c, "proof": [], "failed": [
                {"field": "stock", "why": "not in the live catalog"}]})
            continue
        proof = _sift(sieve, by_code.get(c["code"], {}), c)
        failed = [p for p in proof if not p["ok"]]
        row = {**c, "proof": proof}
        if failed:
            misses.append({**row, "failed": [
                {"field": p["field"], "why": p["why"]} for p in failed]})
        else:
            candidates.append(row)
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
        if not search:
            return None
        # ``components`` DOES honour ``package`` (measured 2026-07-13:
        # search=SP3485 → 19 rows, +package=SOIC-8 → the 2 SOIC-8 parts,
        # +package=BOGUS-9 → 0). This is what makes a FAMILY searchable: the
        # designer typed "ULN2003" and the board decides which of the eleven
        # ULN2003s can go on it. Dropping the package here — as this did —
        # meant a family search returned every package it ships in.
        params = {"search": search}
        package = str(net.get("package") or "").strip()
        if package:
            params["package"] = package
        return {"category": "components", "params": params}
    category = str(plan.get("category") or "").strip()
    return {"category": category, "params": net} if category else None


def _provable(term: dict) -> bool:
    """Can this term's VALUE be compared against a typed column at all?

    A number can. A string that declares its unit can ("63V" + unit "V"). A
    bare string carrying an SI prefix — ``"10kΩ"`` — cannot: ``10k`` is not a
    number in Ω, so nothing it is compared against can ever match it.
    """
    value = term.get("value")
    if isinstance(value, bool):
        return True
    return isinstance(value, (int, float)) or bool(term.get("unit"))


def _full_sieve(plan: dict) -> list[dict]:
    """The agent's sieve, plus its own net params re-asserted as terms.

    ONE TERM PER FIELD. The index column ``resistance`` and the catalog's
    ``Resistance`` are the same field — they differ only in case — and stating
    both is not belt-and-braces, it is a contradiction the sieve cannot honour:
    ``_field()`` resolves either to the index's NUMBER (10000) and the
    catalog-worded value ("10kΩ") then misses on every part in the catalog. So
    duplicates collapse, and the survivor is the one that can actually be
    PROVEN — a number, or a value that declares its unit. Choosing between two
    terms the agent wrote is not composing a query; it is refusing to run a
    comparison that cannot come out true.
    """
    sieve: list[dict] = []
    seen: dict[str, int] = {}
    for term in (plan.get("sieve") or []):
        key = _squash(term.get("field"))
        if key in seen:
            at = seen[key]
            if _provable(term) and not _provable(sieve[at]):
                sieve[at] = dict(term)      # the provable one wins, whatever the order
            continue
        seen[key] = len(sieve)
        sieve.append(dict(term))
    if plan.get("mode") == "code":
        return sieve            # a part number states no terms to prove
    # Every OTHER mode re-asserts its net — including "fts". A keyword search
    # that carries a package is exactly the family case (ULN2003 + SOIC-16),
    # and it is the one search where trusting the net is least affordable:
    # the words match a NAME, so if the package were quietly dropped the
    # engineer would be handed a TSSOP part for a 150-mil land and nothing on
    # screen would say so. ``search`` itself is not in NET_COLUMNS and earns no
    # term — a name match is not a spec, and pretending otherwise would prove a
    # part right for the wrong reason.
    for param, column in NET_COLUMNS.items():
        if param in (plan.get("net") or {}) and _squash(column) not in seen:
            seen[_squash(column)] = len(sieve)
            sieve.append({"field": column, "op": "eq",
                          "value": plan["net"][param], "fromNet": True})
    return sieve


def _sift(sieve: list[dict], row: dict, cand: dict) -> list[dict]:
    """Prove one candidate against every term — and KEEP THE WORKINGS.

    One entry per term, pass AND fail, because an engineer picks a part by
    reading a column, not by reading a sentence about why some other part was
    rejected. A term that cannot be checked is a failure like any other: an
    unprovable part is not a match, it is an unknown.

    - ``have``    what was actually compared (the index's number where it has
                  one, else the catalog's string)
    - ``shown``   what the ENGINEER should read: the catalog's own published
                  string when it publishes this field. The index column says
                  ``1e-05``; the catalog says ``10uF``. Both are true; only one
                  is worth putting in a table.
    - ``catalog`` the catalog names this field — which is exactly what makes it
                  worth a column. ``package`` and ``capacitance_farads`` are
                  query plumbing and do not earn one.
    """
    published = {p.get("parameterName"): p.get("parameterValue")
                 for p in (cand.get("parameters") or [])}
    proof = []
    for term in sieve:
        field = str(term.get("field"))
        op = str(term.get("op"))
        want = term.get("value")
        unit = str(term.get("unit") or "")
        have = _field(field, row, cand)
        alias = CATALOG_ALIAS.get(_squash(field), "")
        catalog = next((v for k, v in published.items()
                        if _same(k, field) or (alias and _same(k, alias))), None)
        entry: dict[str, Any] = {"field": field, "op": op, "unit": unit,
                                 "catalog": catalog is not None}
        if want is not None:
            entry["value"] = want
        if have is None:
            entry.update(ok=False, have=None, shown="—",
                         why=f"{field} is not published for this part")
        else:
            ok, why = _compare(have, op, want, unit)
            entry.update(ok=ok, have=have, why="" if ok else why,
                         shown=str(catalog if catalog is not None else have))
        proof.append(entry)
    return proof


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
    snapshot), then the index row's typed column — worth reaching for because
    it is a NUMBER where the catalog publishes a string — and finally the
    catalog's own parameter list, which is the vocabulary the agent writes in.

    The index's ``attributes`` blob is deliberately not consulted; see the
    module docstring. None means nothing we hold can prove the term — and
    unprovable is a miss, never a pass."""
    if field not in STRUCTURAL and cand.get(field) is not None:
        return cand[field]
    for key, value in row.items():
        # the catalog's "Voltage Rating" IS the index's typed voltage_rating
        if key != "attributes" and value is not None and _same(key, field):
            return value
    for p in (cand.get("parameters") or []):
        if _same(p.get("parameterName") or "", field):
            return p.get("parameterValue")
    return None


def _compare(have: Any, op: str, want: Any, unit: str = "") -> tuple[bool, str]:
    """Compare, never parse. A catalog value is a string ("50V", "5.4mm"), and
    it is coerced to a number ONLY against a ``unit`` the AGENT declared. A
    string that does not conform to that unit ("17mA@120Hz" asked for in mA)
    is reported uncheckable, not guessed at — guessing at units is how the
    wrong part gets shipped."""
    if op == "isTrue":
        return bool(have) is True, f"{have!r} is not true"
    if op == "isFalse":
        return bool(have) is False, f"{have!r} is not false"
    h, w = _numeric(have, unit), _numeric(want, unit)
    if op in ("eq", "ne"):
        if h is not None and w is not None:
            same = math.isclose(h, w, rel_tol=1e-6)
        else:
            same = str(have).strip().casefold() == str(want).strip().casefold()
        if op == "eq":
            return same, f"is {have!r}, not {want!r}"
        return not same, f"is {want!r}"
    if op == "contains":
        return (str(want).casefold() in str(have).casefold(),
                f"{have!r} does not contain {want!r}")
    if op == "in":
        # ONE land, several of the catalog's words for it. JLC spells the 3.9mm
        # 8-pin body both "SOIC-8" and "SOP-8", and they hold DIFFERENT parts —
        # the Basic 327k-stock SP3485 is under SOIC-8 and would simply be missed
        # by a search that had to pick one string. So a term may name a set.
        wanted = want if isinstance(want, (list, tuple)) else [want]
        shown = " or ".join(str(w) for w in wanted)
        return (any(str(have).strip().casefold() == str(w).strip().casefold()
                    for w in wanted),
                f"is {have!r}, not {shown}")
    if op in NUMERIC_OPS:
        if h is None or w is None:
            return False, _uncheckable(have, unit)
        ok = {"lte": h <= w, "gte": h >= w, "lt": h < w, "gt": h > w}[op]
        sign = {"lte": "≤", "gte": "≥", "lt": "<", "gt": ">"}[op]
        return ok, f"is {have!r}, not {sign} {want}{unit}"
    return False, f"unknown test {op!r}"


def _uncheckable(have: Any, unit: str) -> str:
    if unit:
        return f"{have!r} is not a plain number in {unit}"
    return f"{have!r} can't be compared numerically — no unit was declared"


def _numeric(v: Any, unit: str = "") -> float | None:
    """A number is a number. A string is coerced ONLY against the unit the
    agent declared: "63V" with unit "V" is 63; "17mA@120Hz" asked for in "mA"
    is nothing at all, and neither is anything when no unit was declared
    ('100mW' must not become 100 — the index's power column is milliwatts and
    the catalog's text is not). Python checks the string conforms to the unit
    it was handed; it never picks the unit."""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if not unit or not isinstance(v, str):
        return None
    text = v.strip()
    if len(text) <= len(unit) or not text.endswith(unit):
        return None
    try:
        return float(text[: -len(unit)].strip())
    except ValueError:
        return None
