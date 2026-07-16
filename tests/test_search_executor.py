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

    def __init__(self, rows, catalog=None, classes=None):
        self.rows = rows
        self.catalog = catalog or {}      # code → the catalog's parameter table
        self.classes = classes or {}
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
                 "firstTypeName": (self.classes.get(r) or {}).get("first"),
                 "secondTypeName": (self.classes.get(r) or {}).get("second"),
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


def test_catalog_capacitance_outranks_missing_index_capacitance():
    src = LyingIndex(
        [{"code": "C_10U", "package": "0805"},
         {"code": "C_22U", "package": "0805"}],
        catalog={"C_10U": {"Capacitance": "10uF"},
                 "C_22U": {"Capacitance": "22uF"}})
    plan = {**PLAN, "sieve": [
        {"field": "capacitance_farads", "op": "eq", "value": 1e-5},
        {"field": "Capacitance", "op": "eq", "value": "10uF"}],
    }

    got = run_search(src, plan)

    assert got["query"]["params"]["capacitance"] == 1e-5
    assert [c["code"] for c in got["candidates"]] == ["C_10U"]
    assert [t["field"] for t in got["proved"]] == ["Capacitance", "package"]
    assert got["misses"][0]["failed"][0]["field"] == "Capacitance"


def test_a_term_that_cannot_be_checked_is_a_miss_not_a_pass():
    # the part doesn't publish the column: it is an UNKNOWN, never a match
    src = LyingIndex([{"code": "C_MYSTERY", "package": "0805"}])
    got = run_search(src, {**PLAN, "net": {"package": "0805"}})
    assert got["candidates"] == []
    [miss] = got["misses"]
    assert "not published" in miss["failed"][0]["why"]


def test_catalog_class_intent_is_proved_from_live_verified_type():
    src = LyingIndex(
        [{"code": "C_E", "package": "SMD,D5xL5.4mm"},
         {"code": "C_M", "package": "SMD,D5xL5.4mm"}],
        classes={
            "C_E": {"first": "Capacitors", "second":
                    "Aluminum Electrolytic Capacitors - SMD"},
            "C_M": {"first": "Capacitors", "second":
                    "Multilayer Ceramic Capacitors MLCC - SMD/SMT"},
        })
    got = run_search(src, {
        "mode": "parametric", "category": "capacitors", "net": {},
        "sieve": [{"field": "secondTypeName", "op": "in", "value": [
            "Aluminum Electrolytic Capacitors - SMD",
            "Aluminum Electrolytic Capacitors - Leaded"]}]})

    assert [c["code"] for c in got["candidates"]] == ["C_E"]
    assert got["candidates"][0]["secondTypeName"].endswith("- SMD")
    assert got["candidates"][0]["proof"][0]["catalog"] is True
    assert got["misses"][0]["failed"][0]["field"] == "secondTypeName"


def test_catalog_model_family_is_proved_from_live_verified_model():
    src = LyingIndex([
        {"code": "C_BAT", "package": "SOD-323"},
        {"code": "C_OTHER", "package": "SOD-323"},
    ])
    original_verify = src.verify

    def verify(refs):
        facts = original_verify(refs)
        facts["C_BAT"].raw["componentModel"] = "BAT54WS"
        facts["C_OTHER"].raw["componentModel"] = "1N4148WS"
        return facts

    src.verify = verify
    got = run_search(src, {
        "mode": "fts", "category": "components",
        "net": {"search": "BAT54", "package": "SOD-323"},
        "sieve": [
            {"field": "package", "op": "eq", "value": "SOD-323"},
            {"field": "componentModel", "op": "contains", "value": "BAT54"},
        ],
    })

    assert [c["code"] for c in got["candidates"]] == ["C_BAT"]
    assert got["candidates"][0]["proof"][1]["catalog"] is True
    assert got["misses"][0]["failed"][0]["field"] == "componentModel"


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


# The FAMILY case. A designer types "ULN2003" into the schematic VALUE — that is
# a family, not a part, and the board decides which of the eleven ULN2003s can go
# on it. These are the real catalog rows (measured 2026-07-13).
ULN2003 = [
    {"code": "C7512", "package": "SOIC-16"},          # the D suffix: 3.9mm body
    {"code": "C94832", "package": "SOIC-16"},
    {"code": "C2859910", "package": "SO-16-208mil"},  # the NS suffix: WIDE body
    {"code": "C126289", "package": "TSSOP-16"},       # a different land entirely
    {"code": "C93000", "package": "DIP-16"},          # not even surface mount
]


def test_a_family_search_carries_the_package_into_the_request():
    # "ULN2003" alone matches every package the family ships in. The footprint on
    # the board is what makes it orderable, so it MUST reach the index — dropping
    # it (as _query once did) hands the engineer a DIP part for a 150-mil land.
    src = LyingIndex(ULN2003)
    run_search(src, {"mode": "fts", "category": "components",
                     "net": {"search": "ULN2003", "package": "SOIC-16"},
                     "sieve": []})
    assert src.queries == [{"category": "components",
                            "params": {"search": "ULN2003",
                                       "package": "SOIC-16"}}]


def test_a_family_search_proves_its_package_even_when_the_index_ignores_it():
    # The keyword index matches part NAMES. If it quietly dropped `package` — the
    # thing it does to every param it doesn't know — a wide-body SO-16-208mil part
    # would be offered for a 150-mil footprint and NOTHING on screen would say so.
    # So the net's package is re-asserted as a term and proven per part.
    class IgnoresPackage(LyingIndex):
        def discover(self, query):
            self.queries.append(query)
            return list(self.rows)        # the param is silently ignored

    src = IgnoresPackage(ULN2003)
    got = run_search(src, {"mode": "fts", "category": "components",
                           "net": {"search": "ULN2003", "package": "SOIC-16"},
                           "sieve": []})
    assert [c["code"] for c in got["candidates"]] == ["C7512", "C94832"]
    missed = {c["code"]: c["failed"][0] for c in got["misses"]}
    assert set(missed) == {"C2859910", "C126289", "C93000"}
    assert missed["C2859910"]["field"] == "package"      # named, with a reason
    assert "SO-16-208mil" in missed["C2859910"]["why"]


def test_a_family_search_states_no_term_for_the_words_themselves():
    # `search` matches a NAME. A name is not a spec, and proving a part "right"
    # because its name matched would be proving it for the wrong reason.
    src = LyingIndex(ULN2003)
    got = run_search(src, {"mode": "fts", "category": "components",
                           "net": {"search": "ULN2003", "package": "SOIC-16"},
                           "sieve": []})
    assert [t["field"] for t in got["proved"]] == ["package"]


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


def test_the_workings_are_kept_for_every_part_matched_or_not():
    """An engineer picks by comparing a column, not by reading a sentence.

    So every part carries its proof: one entry per term, pass and fail alike,
    with the catalog's own published string to put in the cell. `catalog` marks
    the terms worth a column — the query's own plumbing (`package`,
    `capacitance_farads`) is not one of them.
    """
    src = LyingIndex(
        [{"code": "C_50", "package": "SMD,D5xL5.4mm", "capacitance_farads": 1e-5},
         {"code": "C_25", "package": "SMD,D5xL5.4mm", "capacitance_farads": 1e-5}],
        catalog={"C_50": {"Capacitance": "10uF", "Voltage Rating": "50V"},
                 "C_25": {"Capacitance": "10uF", "Voltage Rating": "25V"}})
    got = run_search(src, {
        "mode": "parametric", "category": "capacitors",
        "net": {"package": "SMD,D5xL5.4mm", "capacitance": 1e-5},
        "sieve": [{"field": "Capacitance", "op": "eq", "value": "10uF"},
                  {"field": "Voltage Rating", "op": "gte", "value": 50,
                   "unit": "V"}]})

    [hit] = got["candidates"]
    [miss] = got["misses"]
    assert hit["code"] == "C_50" and miss["code"] == "C_25"

    # the REJECTED part carries its workings too — that is the whole point: you
    # can see it is a 10uF 5x5.4 can and that ONLY its voltage is wrong
    by_field = {p["field"]: p for p in miss["proof"]}
    assert by_field["Capacitance"]["ok"] is True
    assert by_field["Capacitance"]["shown"] == "10uF"
    assert by_field["Voltage Rating"]["ok"] is False
    assert by_field["Voltage Rating"]["shown"] == "25V"   # the cell to paint red
    assert "≥ 50V" in by_field["Voltage Rating"]["why"]

    # the index's number is what Python compared; the catalog's string is what
    # the engineer reads. Both are true; only one belongs in a table.
    cap = {p["field"]: p for p in hit["proof"]}["Capacitance"]
    assert cap["shown"] == "10uF"

    # net params are re-asserted and proven, but they are PLUMBING — no column
    plumbing = {p["field"]: p for p in hit["proof"]}
    for field in ("package", "capacitance_farads"):
        if field in plumbing:
            assert plumbing[field]["catalog"] is False
    assert all(p["catalog"] for p in hit["proof"]
               if p["field"] in ("Capacitance", "Voltage Rating"))


def test_an_unverifiable_part_has_no_workings_to_show():
    class Gone(LyingIndex):
        def verify(self, refs):
            return {r: PartFact(ref=r, found=False, provenance="gone")
                    for r in refs}

    got = run_search(Gone([{"code": "C_GONE", "package": "0805"}]),
                     {**PLAN, "net": {"package": "0805"}, "sieve": []})
    [miss] = got["misses"]
    assert miss["proof"] == []          # nothing was proven — say nothing
    assert miss["failed"][0]["why"] == "not in the live catalog"


# The index column `resistance` and the catalog parameter `Resistance` are ONE
# field spelled two ways. A plan that states both is not being careful — the
# string term ("10kΩ") gets compared against the column's NUMBER (10000) and
# misses on every part in the catalog. This is not hypothetical: it rejected all
# 100 candidates for a stock 10k 0603 while every column on screen read "10kΩ".
RES = [{"code": "R_10K", "package": "0603", "resistance": 10000,
        "tolerance_fraction": 0.01},
       {"code": "R_10K_5PC", "package": "0603", "resistance": 10000,
        "tolerance_fraction": 0.05},          # ±5% — fails "1% or better"
       {"code": "R_1K", "package": "0603", "resistance": 1000,
        "tolerance_fraction": 0.01}]          # wrong value; the index ignored it

RES_CATALOG = {"R_10K": {"Resistance": "10kΩ", "Tolerance": "±1%"},
               "R_10K_5PC": {"Resistance": "10kΩ", "Tolerance": "±5%"},
               "R_1K": {"Resistance": "1kΩ", "Tolerance": "±1%"}}


def _res_plan(sieve):
    return {"mode": "parametric", "category": "resistors",
            "net": {"package": "0603", "resistance": 10000}, "sieve": sieve}


def test_one_field_spelled_two_ways_is_proved_once():
    src = LyingIndex(RES, catalog=RES_CATALOG)
    got = run_search(src, _res_plan([
        {"field": "resistance", "op": "eq", "value": 10000},
        {"field": "Resistance", "op": "eq", "value": "10kΩ"}]))
    assert [c["code"] for c in got["candidates"]] == ["R_10K", "R_10K_5PC"]
    fields = [p["field"] for p in got["candidates"][0]["proof"]]
    assert fields.count("resistance") + fields.count("Resistance") == 1


def test_the_provable_twin_wins_whatever_order_it_was_written_in():
    # the string term first: keeping "first wins" would still reject every part
    src = LyingIndex(RES, catalog=RES_CATALOG)
    got = run_search(src, _res_plan([
        {"field": "Resistance", "op": "eq", "value": "10kΩ"},
        {"field": "resistance", "op": "eq", "value": 10000}]))
    assert [c["code"] for c in got["candidates"]] == ["R_10K", "R_10K_5PC"]
    assert got["misses"][0]["code"] == "R_1K"   # and the wrong value still dies


def test_tolerance_fraction_earns_the_catalogs_own_column():
    # 0.01 IS "±1%", and `lte` is "1% or better" — a ±0.1% part passes. But the
    # engineer must be able to SEE that: a column is only granted to a field the
    # catalog names, and without the alias this term proved invisibly, leaving
    # `0.01` on screen with nothing to tie it to the "±1%" being read.
    src = LyingIndex(RES, catalog=RES_CATALOG)
    got = run_search(src, _res_plan([
        {"field": "resistance", "op": "eq", "value": 10000},
        {"field": "tolerance_fraction", "op": "lte", "value": 0.01}]))
    assert [c["code"] for c in got["candidates"]] == ["R_10K"]
    tol = next(p for p in got["candidates"][0]["proof"]
               if p["field"] == "tolerance_fraction")
    assert tol["catalog"] is True       # → it earns a column
    assert tol["shown"] == "±1%"        # → in the catalog's own words
    loose = next(c for c in got["misses"] if c["code"] == "R_10K_5PC")
    assert loose["failed"][0]["field"] == "tolerance_fraction"


# One land, several of the catalog's words for it. JLC spells the 3.9mm 8-pin
# body BOTH "SOIC-8" and "SOP-8", and they hold different parts — the Basic,
# 327k-in-stock SP3485 sits under SOIC-8 (measured 2026-07-13).
SP3485 = [
    {"code": "C8963", "package": "SOIC-8"},        # Basic, the big-stock one
    {"code": "C668205", "package": "SOP-8"},       # a house brand, same land
    {"code": "C5199842", "package": "MSOP-8"},     # a DIFFERENT land
    {"code": "C52121503", "package": "DFN-8(3x3)"},
]


def test_a_term_may_name_a_SET_of_packages_for_one_land():
    # Picking a single string would throw away half the land's parts — and the
    # better half at that. The net cannot express it (the index takes one
    # `package`), so the sieve does, which is where the proving belonged anyway.
    src = LyingIndex(SP3485)
    got = run_search(src, {
        "mode": "fts", "category": "components", "net": {"search": "SP3485"},
        "sieve": [{"field": "package", "op": "in",
                   "value": ["SOIC-8", "SOP-8"]}]})
    assert src.queries == [{"category": "components",
                            "params": {"search": "SP3485"}}]
    assert [c["code"] for c in got["candidates"]] == ["C8963", "C668205"]
    missed = {c["code"]: c["failed"][0]["why"] for c in got["misses"]}
    assert set(missed) == {"C5199842", "C52121503"}
    # the reason names what it IS and what was wanted — readable, not a code
    assert missed["C5199842"] == "is 'MSOP-8', not SOIC-8 or SOP-8"


def test_a_multi_package_net_unions_narrow_requests_and_proves_the_land():
    src = LyingIndex(SP3485)
    got = run_search(src, {
        "mode": "fts", "category": "components",
        "net": {"search": "SP3485", "package": ["SOIC-8", "SOP-8"]},
        "sieve": []})

    assert src.queries == [
        {"category": "components",
         "params": {"search": "SP3485", "package": "SOIC-8"}},
        {"category": "components",
         "params": {"search": "SP3485", "package": "SOP-8"}},
    ]
    assert got["queries"] == src.queries
    assert [c["code"] for c in got["candidates"]] == ["C8963", "C668205"]
    assert got["proved"] == [{"field": "package", "op": "in",
                              "value": ["SOIC-8", "SOP-8"],
                              "fromNet": True}]
