"""The search executor — a coarse net, then an honest sieve.

The parts index silently ignores query params it doesn't know: ask it for
X7R and it hands back X5R parts with no complaint. Every test here exists
because a search that trusts its own query ships the wrong part.
"""

from hendley.datasources.base import PartFact
from hendley.resolver.orchestration.search import run_search


class LyingIndex:
    """jlcsearch to the life: it honours `package`, and SILENTLY IGNORES every
    other param — returning rows that look filtered and are not."""

    name = "lying"

    def __init__(self, rows):
        self.rows = rows
        self.queries = []

    def discover(self, query):
        self.queries.append(query)
        pkg = (query.get("params") or {}).get("package")
        return [r for r in self.rows if not pkg or r.get("package") == pkg]

    def verify(self, refs):
        pkg = {r["code"]: r.get("package") for r in self.rows}
        return {r: PartFact(
            ref=r, found=True, stock=5000, mpn=f"MPN-{r}", manufacturer="ACME",
            price_tiers=[{"startQuantity": 1, "unitPrice": 0.01}],
            raw={"componentCode": r, "componentModel": f"MPN-{r}",
                 "componentSpecification": pkg.get(r), "stockCount": 5000,
                 "libraryType": "Basic",
                 "priceRanges": [{"startQuantity": 1, "unitPrice": 0.01}],
                 "parameters": []},
            provenance=self.name) for r in refs}


CAPS = [
    {"code": "C_X7R", "package": "0805", "capacitance_farads": 1e-5,
     "temperature_coefficient": "X7R", "voltage_rating": 50},
    {"code": "C_X5R", "package": "0805", "capacitance_farads": 1e-5,
     "temperature_coefficient": "X5R", "voltage_rating": 50},   # wrong dielectric
    {"code": "C_16V", "package": "0805", "capacitance_farads": 1e-5,
     "temperature_coefficient": "X7R", "voltage_rating": 16},   # underrated
    {"code": "C_100N", "package": "0805", "capacitance_farads": 1e-7,
     "temperature_coefficient": "X7R", "voltage_rating": 50},   # wrong value
]

PLAN = {"mode": "parametric", "category": "capacitors",
        "net": {"package": "0805", "capacitance": 1e-5},
        "sieve": [{"field": "temperature_coefficient", "op": "eq", "value": "X7R"},
                  {"field": "voltage_rating", "op": "gte", "value": 25}],
        "say": "10uF 0805 X7R 25V+"}


def test_the_sieve_catches_what_the_index_silently_ignored():
    # the index returned all four (it only honoured `package`); only ONE part
    # actually satisfies the engineer's terms, and only it may be offered
    src = LyingIndex(CAPS)
    got = run_search(src, PLAN)
    assert [c["code"] for c in got["candidates"]] == ["C_X7R"]
    assert got["scanned"] == 4
    missed = {c["code"]: [f["why"] for f in c["failed"]] for c in got["misses"]}
    assert set(missed) == {"C_X5R", "C_16V", "C_100N"}
    assert "X5R" in missed["C_X5R"][0]          # the reason is shown, not hidden
    assert any("25" in w for w in missed["C_16V"])


def test_a_net_param_the_index_dropped_is_still_enforced():
    # capacitance was in the net and the index ignored it — the 100n part came
    # back. The sieve re-asserts every net param, so it cannot leak through.
    src = LyingIndex(CAPS)
    plan = {**PLAN, "sieve": []}   # the agent stated NO extra terms
    got = run_search(src, plan)
    assert "C_100N" not in [c["code"] for c in got["candidates"]]
    why = next(c["failed"] for c in got["misses"] if c["code"] == "C_100N")
    assert why[0]["field"] == "capacitance_farads"


def test_a_term_that_cannot_be_checked_is_a_miss_not_a_pass():
    # the part doesn't publish the column: it is an UNKNOWN, never a match
    src = LyingIndex([{"code": "C_MYSTERY", "package": "0805"}])
    got = run_search(src, {**PLAN, "net": {"package": "0805"}})
    assert got["candidates"] == []
    [miss] = got["misses"]
    assert "not published" in miss["failed"][0]["why"]


def test_units_are_never_guessed_at():
    # "100mW" is text, not a number: comparing it numerically would silently
    # decide 100mW >= 250mW. It is reported as uncheckable instead.
    src = LyingIndex([{"code": "C_TXT", "package": "0603",
                       "attributes": '{"Power(Watts)": "100mW"}'}])
    got = run_search(src, {
        "mode": "parametric", "category": "resistors",
        "net": {"package": "0603"},
        "sieve": [{"field": "Power(Watts)", "op": "gte", "value": 250}]})
    assert got["candidates"] == []
    assert "compared numerically" in got["misses"][0]["failed"][0]["why"]


def test_the_attributes_json_answers_when_a_column_does_not():
    src = LyingIndex([{"code": "C_A", "package": "0603",
                       "attributes": '{"Temperature Coefficient": "X7R"}'}])
    got = run_search(src, {
        "mode": "parametric", "category": "capacitors",
        "net": {"package": "0603"},
        "sieve": [{"field": "temperature_coefficient", "op": "eq",
                   "value": "x7r"}]})       # case-insensitive
    assert [c["code"] for c in got["candidates"]] == ["C_A"]


def test_keyword_mode_asks_the_component_index_verbatim():
    src = LyingIndex([{"code": "C1", "package": "SOD-323"}])
    got = run_search(src, {"mode": "fts", "category": "components",
                           "net": {"search": "1n4148ws"}, "sieve": []})
    assert src.queries == [{"category": "components",
                            "params": {"search": "1n4148ws"}}]
    assert [c["code"] for c in got["candidates"]] == ["C1"]


def test_an_unverifiable_part_is_never_a_result():
    class Gone(LyingIndex):
        def verify(self, refs):
            return {r: PartFact(ref=r, found=False, provenance="gone")
                    for r in refs}

    got = run_search(Gone([{"code": "C_GONE", "package": "0805"}]),
                     {**PLAN, "net": {"package": "0805"}, "sieve": []})
    assert got["candidates"] == []
    assert got["misses"][0]["failed"][0]["why"] == "not in the live catalog"


def test_truncation_is_reported_not_hidden():
    rows = [{"code": f"C{i}", "package": "0805", "capacitance_farads": 1e-5,
             "temperature_coefficient": "X7R", "voltage_rating": 50}
            for i in range(100)]
    got = run_search(LyingIndex(rows), PLAN)
    assert got["truncated"] is True     # the index stops at 100 — say so
    assert len(got["candidates"]) == 100
