"""The search executor — a coarse net, then an honest sieve.

The parts index silently ignores query params it doesn't know: ask it for
X7R and it hands back X5R parts with no complaint. Every test here exists
because a search that trusts its own query ships the wrong part.
"""

from hendley.datasources.base import PartFact
from hendley.resolver.orchestration.search import run_search


class LyingIndex:
    """jlcsearch to the life: it honours `package`, and SILENTLY IGNORES every
    other param — returning rows that look filtered and are not.

    Its rows carry the index's ``attributes`` blob — the RAW datasheet keys,
    which drift per manufacturer — while ``verify()`` returns the CATALOG's own
    normalized ``parameters``. The two disagree on purpose: that disagreement is
    what the sieve has to survive.
    """

    name = "lying"

    def __init__(self, rows, catalog=None):
        self.rows = rows
        self.catalog = catalog or {}      # code → the catalog's parameter table
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
                 "parameters": [{"parameterName": k, "parameterValue": v}
                                for k, v in (self.catalog.get(r) or {}).items()]},
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


def test_a_unit_the_agent_did_not_declare_is_never_guessed_at():
    # "100mW" is text, not a number. Coercing it unasked would silently decide
    # 100mW >= 250. With no unit declared it stays uncheckable — a miss.
    src = LyingIndex([{"code": "C_TXT", "package": "0603"}],
                     catalog={"C_TXT": {"Power": "100mW"}})
    got = run_search(src, {
        "mode": "parametric", "category": "resistors",
        "net": {"package": "0603"},
        "sieve": [{"field": "Power", "op": "gte", "value": 250}]})
    assert got["candidates"] == []
    assert "no unit was declared" in got["misses"][0]["failed"][0]["why"]


def test_a_declared_unit_makes_or_better_expressible():
    # The catalog publishes voltage as TEXT ("50V"). Until the agent could
    # declare the unit, "50 V or better" was uncheckable and EVERY part missed —
    # so the engineer could only ask for exactly 50 V, and the 63 V part, a
    # strictly better drop-in, was a silent casualty. Now it is a result.
    src = LyingIndex(
        [{"code": "C_50", "package": "SMD,D5xL5.4mm"},
         {"code": "C_63", "package": "SMD,D5xL5.4mm"},
         {"code": "C_25", "package": "SMD,D5xL5.4mm"}],
        catalog={"C_50": {"Voltage Rating": "50V"},
                 "C_63": {"Voltage Rating": "63V"},
                 "C_25": {"Voltage Rating": "25V"}})
    got = run_search(src, {
        "mode": "parametric", "category": "capacitors",
        "net": {"package": "SMD,D5xL5.4mm"},
        "sieve": [{"field": "Voltage Rating", "op": "gte", "value": 50,
                   "unit": "V"}]})
    assert sorted(c["code"] for c in got["candidates"]) == ["C_50", "C_63"]
    [miss] = got["misses"]
    assert miss["code"] == "C_25"
    assert "'25V', not ≥ 50V" in miss["failed"][0]["why"]


def test_a_string_that_does_not_conform_to_its_unit_is_a_miss_not_a_pass():
    # "17mA@120Hz" is not "17 mA". Coercing it would ship a part on a number
    # Python invented. A declared unit licenses a CHECK, never a guess.
    src = LyingIndex([{"code": "C_RIPPLE", "package": "SMD,D5xL5.4mm"}],
                     catalog={"C_RIPPLE": {"Ripple Current": "17mA@120Hz"}})
    got = run_search(src, {
        "mode": "parametric", "category": "capacitors",
        "net": {"package": "SMD,D5xL5.4mm"},
        "sieve": [{"field": "Ripple Current", "op": "gte", "value": 10,
                   "unit": "mA"}]})
    assert got["candidates"] == []
    assert "not a plain number in mA" in got["misses"][0]["failed"][0]["why"]


def test_the_manufacturers_spelling_never_decides_the_answer():
    # THE regression this path exists for. The index's attributes blob is a
    # scrape of the RAW datasheet keys and they drift: of 680 sampled
    # electrolytics, 583 call the diameter "φD" and 62 call it "Diameter". The
    # CATALOG calls it "Diameter" for every one of them. Sieve on the blob and a
    # part that matches perfectly is dropped as "not published" — an honest-
    # looking miss on a part that is, in fact, exactly what was asked for.
    src = LyingIndex(
        [{"code": "C_PHI", "package": "SMD,D5xL5.4mm",
          "attributes": '{"φD": "5mm", "L": "5.4mm", "Rated Voltage": "50V"}'},
         {"code": "C_DIA", "package": "SMD,D5xL5.4mm",
          "attributes": '{"Diameter": "5mm", "Height - Seated (Max)": "5.4mm"}'}],
        catalog={c: {"Diameter": "5mm", "Height - Seated (Max)": "5.4mm"}
                 for c in ("C_PHI", "C_DIA")})
    got = run_search(src, {
        "mode": "parametric", "category": "capacitors",
        "net": {"package": "SMD,D5xL5.4mm"},
        "sieve": [{"field": "Diameter", "op": "eq", "value": "5mm"}]})
    assert sorted(c["code"] for c in got["candidates"]) == ["C_DIA", "C_PHI"]
    assert got["misses"] == []


def test_a_catalog_name_resolves_to_the_index_s_typed_column():
    # One field, two spellings: the catalog's "Voltage Rating" ("50V") and the
    # index's typed voltage_rating (50). The number is there for the taking —
    # take it, and the term needs no unit at all.
    src = LyingIndex([{"code": "C_T", "package": "0805", "voltage_rating": 50}])
    got = run_search(src, {
        "mode": "parametric", "category": "capacitors",
        "net": {"package": "0805"},
        "sieve": [{"field": "Voltage Rating", "op": "gte", "value": 25}]})
    assert [c["code"] for c in got["candidates"]] == ["C_T"]


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
