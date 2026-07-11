"""Tests for the hard-constraint engine, the candidate ranking engine, and
the approval-queue orchestration (the discovery loop's one interruption)."""

from hendley.datasources.base import PartFact
from hendley.domain.model import RequirementLine, RequirementsBom, SpecKey
from hendley.knowledge.partsdb import PartsDb, record
from hendley.providers.jlcpcb.strategy import JLCPCBStrategy
from hendley.resolver.constraints import filter_candidates
from hendley.resolver.orchestration import (
    apply_approvals,
    build_approval_queue,
    resolve,
)
from hendley.resolver.ranking import rank_candidates

SPEC = SpecKey("resistor", "22k", "0603")


def cand(code, stock=1000, price=0.002, package="0603", verified=True, **kw):
    return {"code": code, "verified": verified, "liveStock": stock,
            "unitPrice1": price, "package": package, **kw}


# ---------------------------------------------------------------------------
# Constraints
# ---------------------------------------------------------------------------

def test_constraints_reject_unverified_and_wrong_package():
    valid, rejected = filter_candidates(SPEC, [
        cand("C1"),
        cand("C2", verified=False),
        cand("C3", package="0402"),
    ])
    assert [c["code"] for c in valid] == ["C1"]
    reasons = {c["code"]: c["rejectedBecause"] for c in rejected}
    assert "not live-verified" in reasons["C2"][0]
    assert "'0402' != required '0603'" in reasons["C3"][0]


def test_constraints_keep_unknown_package_with_caveat():
    valid, rejected = filter_candidates(SPEC, [cand("C1", package=None)])
    assert rejected == []
    assert "package unknown" in valid[0]["caveats"][0]


# ---------------------------------------------------------------------------
# Ranking (new candidates only — ADR-0001)
# ---------------------------------------------------------------------------

def test_ranking_prefers_stock_margin_over_price(tmp_path):
    # standing bias: high inventory beats cheapest
    ranked = rank_candidates(
        [cand("C_CHEAP", stock=600, price=0.001),
         cand("C_DEEP", stock=500_000, price=0.003)],
        required_qty=500, strategy=JLCPCBStrategy())
    assert [c["code"] for c in ranked] == ["C_DEEP", "C_CHEAP"]
    assert any("1000x" in w for w in ranked[0]["why"])


def test_ranking_scores_are_decomposed_and_deterministic():
    rows = [cand("C1", stock=5000), cand("C2", stock=5000)]
    a = rank_candidates(rows, required_qty=100, strategy=JLCPCBStrategy())
    b = rank_candidates(rows, required_qty=100, strategy=JLCPCBStrategy())
    assert a == b  # deterministic
    for c in a:
        assert abs(c["score"] - sum(x["weight"] for x in c["scoreContributions"])) < 1e-9
        assert len(c["why"]) == len(c["scoreContributions"])


def test_ranking_prior_approval_beats_everything(tmp_path):
    store = PartsDb(tmp_path / "parts.db")
    record(store.conn, "resistor", "22k", "0603", lcsc="C_OURS")
    ranked = rank_candidates(
        [cand("C_NEW", stock=1_000_000, price=0.0001),
         cand("C_OURS", stock=5_000, price=0.002)],
        required_qty=100, strategy=JLCPCBStrategy(), store=store, spec=SPEC)
    assert ranked[0]["code"] == "C_OURS"
    assert any("approved choice on this House Part" in w for w in ranked[0]["why"])


def test_ranking_short_stock_scores_zero_margin():
    ranked = rank_candidates([cand("C1", stock=40)], required_qty=100,
                             strategy=JLCPCBStrategy())
    short = ranked[0]["scoreContributions"][0]
    assert short["factor"] == "stock-short" and short["weight"] == 0.0


def test_jlc_offer_class_is_displayed_never_weighted():
    ranked = rank_candidates([cand("C1", libraryType="Extended")], required_qty=10,
                             strategy=JLCPCBStrategy())
    offer = [x for x in ranked[0]["scoreContributions"] if x["factor"] == "offer-class"]
    assert offer and offer[0]["weight"] == 0.0


# ---------------------------------------------------------------------------
# Approval queue
# ---------------------------------------------------------------------------

class QueueSource:
    """DataSource whose discover() serves canned jlcsearch-shaped rows."""

    name = "fake"

    def __init__(self, stocks: dict[str, int], discovered: list[dict]):
        self.stocks = stocks
        self.discovered = discovered
        self.discover_queries: list[dict] = []

    def verify(self, refs):
        out = {}
        for r in sorted(set(refs)):
            if r in self.stocks:
                out[r] = PartFact(
                    ref=r, found=True, stock=self.stocks[r], mpn=f"MPN-{r}",
                    price_tiers=[{"startQuantity": 1, "unitPrice": 0.002}],
                    raw={"componentCode": r, "stockCount": self.stocks[r],
                         "componentModel": f"MPN-{r}",
                         "componentSpecification": "0603",
                         "libraryType": "Basic",
                         "priceRanges": [{"startQuantity": 1, "unitPrice": 0.002}]},
                    provenance=self.name)
            else:
                out[r] = PartFact(ref=r, found=False, provenance=self.name)
        return out

    def discover(self, query):
        self.discover_queries.append(query)
        return list(self.discovered)


def _escalated_setup(tmp_path):
    """A spec line whose single AVL choice is out of stock → escalates."""
    store = PartsDb(tmp_path / "parts.db")
    record(store.conn, "resistor", "22k", "0603", lcsc="C_OLD")
    requirements = RequirementsBom(
        production_quantity=100, design="comet",
        lines=[RequirementLine(designators=["R1"], comment="22k", spec=SPEC)])
    src = QueueSource(
        stocks={"C_OLD": 3, "C_NEW1": 90_000, "C_NEW2": 500},
        discovered=[
            {"code": "C_NEW1", "mfr": "0603WAF2202T5E", "package": "0603",
             "jlcsearch_stock": 12, "price1": 0.001},
            {"code": "C_NEW2", "mfr": "RC0603FR-0722KL", "package": "0603",
             "jlcsearch_stock": 5, "price1": 0.002},
            {"code": "C_WRONG", "mfr": "X", "package": "0402",
             "jlcsearch_stock": 9, "price1": 0.001},
        ])
    result = resolve(store, requirements, datasource=src, strategy=JLCPCBStrategy())
    assert result["escalations"]
    return store, requirements, result, src


def test_queue_discovers_verifies_filters_and_ranks(tmp_path):
    store, requirements, result, src = _escalated_setup(tmp_path)
    queue = build_approval_queue(store, requirements, result,
                                 datasource=src, strategy=JLCPCBStrategy())
    assert queue["approvalQueueVersion"] == 1
    assert queue["design"] == "comet" and queue["provider"] == "jlcpcb"
    [entry] = queue["entries"]
    assert entry["reason"] == "avl-exhausted" and entry["requiredQty"] == 100
    assert entry["discovery"] == {"category": "resistors", "automatic": True}
    # AVL live stock rides along to seed the review without a re-query
    assert entry["avlChoices"][0]["ref"] == "C_OLD"
    # wrong-package candidate rejected by the constraint engine, with reason
    assert [c["code"] for c in entry["rejectedCandidates"]] == ["C_WRONG"]
    # survivors verified live and ranked (deep stock first), with why-lists
    assert [c["code"] for c in entry["candidates"]] == ["C_NEW1", "C_NEW2"]
    top = entry["candidates"][0]
    assert top["verified"] and top["liveStock"] == 90_000 and top["score"] > 0
    assert top["model"] == "MPN-C_NEW1"  # live identity, not the stale index row
    # discovery queried the mapped category with the exact package AND value
    assert src.discover_queries == [
        {"category": "resistors", "params": {"package": "0603",
                                             "resistance": 22000}}]
    # the decisive parameters ride along for the reviewer
    assert "keyParams" in top


def test_queue_unmapped_kind_ships_empty_with_note(tmp_path):
    store = PartsDb(tmp_path / "parts.db")
    spec = SpecKey("transformer", "10uH", "SMD-XL")
    requirements = RequirementsBom(
        production_quantity=5,
        lines=[RequirementLine(designators=["T1"], spec=spec)])
    src = QueueSource(stocks={}, discovered=[])
    result = resolve(store, requirements, datasource=src, strategy=JLCPCBStrategy())
    queue = build_approval_queue(store, requirements, result,
                                 datasource=src, strategy=JLCPCBStrategy())
    [entry] = queue["entries"]
    assert entry["candidates"] == [] and not entry["discovery"]["automatic"]
    assert "pick a" in entry["discovery"]["note"]
    assert src.discover_queries == []  # no guessing at categories


def test_apply_approvals_records_and_re_resolution_is_clean(tmp_path):
    store, requirements, result, src = _escalated_setup(tmp_path)
    queue = build_approval_queue(store, requirements, result,
                                 datasource=src, strategy=JLCPCBStrategy())
    pick = queue["entries"][0]["candidates"][0]
    recorded = apply_approvals(store, [{
        "spec": queue["entries"][0]["spec"],
        "lcsc": pick["code"], "mpn": pick["model"],
        "design": "comet", "note": "C_OLD out of stock",
    }])
    assert recorded[0]["rank"] == 1  # promotion; C_OLD stays at rank 2
    again = resolve(store, requirements, datasource=src, strategy=JLCPCBStrategy())
    assert again["escalations"] == []
    assert again["lines"][0]["ref"] == "C_NEW1" and again["lines"][0]["rankUsed"] == 1
