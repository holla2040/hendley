"""Queue discovery — deterministic queries auto-run; judgment never does.

The VZ10 lesson (2026-07-13): a zener spec in a library footprint has no
resistance/capacitance param and no chip package, so the old query hit the
ENTIRE diodes category unfiltered and proposed rectifiers. Rule (Craig's):
composing a search is judgment — Python never invents one. Such specs get
candidates ONLY from a human-supplied search string, fired verbatim at the
full-text index; without one the queue entry says ``needsSearch`` and
carries an empty list.
"""

from hendley.datasources.base import PartFact
from hendley.domain.model import SpecKey
from hendley.resolver.orchestration.queue import _verified_candidates


class RecordingSource:
    name = "recording"

    def __init__(self, rows):
        self.rows = rows
        self.queries = []

    def discover(self, query):
        self.queries.append(query)
        return list(self.rows)

    def verify(self, refs):
        out = {}
        for r in sorted(set(refs)):
            out[r] = PartFact(
                ref=r, found=True, stock=1000, mpn=f"MPN-{r}",
                price_tiers=[{"startQuantity": 1, "unitPrice": 0.01}],
                raw={"componentCode": r, "componentModel": f"MPN-{r}",
                     "componentSpecification": "SOD-323",
                     "stockCount": 1000, "libraryType": "Basic",
                     "priceRanges": [{"startQuantity": 1, "unitPrice": 0.01}],
                     "parameters": []},
                provenance=self.name)
        return out


ZENER = SpecKey("diode", "10V", "SOD-323", "zener")


def test_no_deterministic_query_and_no_search_discovers_nothing():
    src = RecordingSource([{"code": "C353563"}])
    rows, used = _verified_candidates(src, "diodes", ZENER, set())
    assert rows == [] and used is None
    assert src.queries == []   # no query the engineer didn't ask for


def test_human_search_fires_verbatim_at_the_fts_index():
    src = RecordingSource([{"code": "C353563"}])
    rows, used = _verified_candidates(src, "diodes", ZENER, set(),
                                      search="zener 10V sot-23")
    [q] = src.queries
    assert q["category"] == "components"
    assert q["params"] == {"search": "zener 10V sot-23"}   # verbatim, no edits
    assert used == {"category": "components",
                    "params": {"search": "zener 10V sot-23"}}
    assert [r["code"] for r in rows] == ["C353563"]


def test_dense_value_param_keeps_the_category_query():
    src = RecordingSource([{"code": "C25768"}])
    spec = SpecKey("resistor", "22k", "0402", "")
    _verified_candidates(src, "resistors", spec, set())
    [q] = src.queries
    assert q["category"] == "resistors"
    assert q["params"]["resistance"] == 22000
    assert q["params"]["package"] == "0402"


def test_chip_package_alone_still_queries_the_category():
    # an LED has no value param but 0603 IS a deterministic package filter
    src = RecordingSource([{"code": "C2286"}])
    spec = SpecKey("led", "red", "0603", "")
    _verified_candidates(src, "leds", spec, set())
    [q] = src.queries
    assert q["category"] == "leds" and q["params"] == {"package": "0603"}


def test_chip_package_without_a_category_uses_the_search_not_a_crash():
    src = RecordingSource([{"code": "C1"}])
    spec = SpecKey("ferrite", "600R", "0603", "")   # no KIND_CATEGORIES entry
    rows, used = _verified_candidates(src, None, spec, set(),
                                      search="ferrite bead 600R 0603")
    [q] = src.queries
    assert q["category"] == "components"
    assert used == {"category": "components",
                    "params": {"search": "ferrite bead 600R 0603"}}
