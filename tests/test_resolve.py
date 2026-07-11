"""Tests for the resolver — rank-walk, substitution, escalation, quantity math."""

import pytest

from hendley.datasources.base import PartFact
from hendley.domain.model import CHECKS, RequirementLine, RequirementsBom, SpecKey
from hendley.knowledge.partsdb import PartsDb, record
from hendley.providers.jlcpcb.bom_csv import BomLine, render_bom_csv, unresolved_lines
from hendley.providers.jlcpcb.strategy import JLCPCBStrategy
from hendley.resolver.orchestration.resolve import (
    format_escalation_report,
    load_request_json,
    resolve,
)


class FakeSource:
    """Canned DataSource: {ref: stock} → PartFacts. Tracks batching."""

    name = "fake"

    def __init__(self, stocks: dict[str, int], price: float = 0.002):
        self.stocks = stocks
        self.calls: list[list[str]] = []
        self.price = price

    def verify(self, refs):
        refs = sorted(set(refs))
        self.calls.append(list(refs))
        out = {}
        for r in refs:
            if r in self.stocks:
                out[r] = PartFact(
                    ref=r, found=True, stock=self.stocks[r],
                    price_tiers=[{"startQuantity": 1, "unitPrice": self.price},
                                 {"startQuantity": 100, "unitPrice": self.price / 2}],
                    provenance=self.name)
            else:
                out[r] = PartFact(ref=r, found=False, provenance=self.name)
        return out

    def discover(self, query):
        return []


@pytest.fixture
def store(tmp_path):
    return PartsDb(tmp_path / "parts.db")


def spec_line(*designators, kind="resistor", value="22k", package="0603", **kw):
    qualifier = kw.pop("qualifier", "")
    return RequirementLine(designators=list(designators),
                           spec=SpecKey(kind, value, package, qualifier), **kw)


def bom(lines, n=25, design=None):
    return RequirementsBom(production_quantity=n, lines=lines, design=design)


def run(store, lines, n=25, stocks=None, design=None, source=None):
    src = source or FakeSource(stocks or {})
    return resolve(store, bom(lines, n, design),
                   datasource=src, strategy=JLCPCBStrategy()), src


def checks_named(row):
    return [c["check"] for c in row["checks"]]


def test_happy_path_rank1_no_checks(store):
    record(store.conn, "resistor", "22k", "0603", lcsc="C1")
    result, _ = run(store, [spec_line("R1", "R2", comment="22k")], 25, {"C1": 10_000})
    row = result["lines"][0]
    assert row["lcsc"] == "C1" and row["ref"] == "C1"
    assert row["rankUsed"] == 1 and not row["substitution"]
    assert row["source"] == "db" and row["requiredQty"] == 50  # 2 designators × 25
    assert row["offerType"] == "jlc-mounted" and row["provider"] == "jlcpcb"
    assert row["checks"] == [] and result["escalations"] == []


def test_silent_fallback_down_the_rank(store):
    record(store.conn, "resistor", "22k", "0603", lcsc="C1")
    record(store.conn, "resistor", "22k", "0603", lcsc="C2", rank=2)
    result, _ = run(store, [spec_line("R1", "R2")], 25, {"C1": 40, "C2": 9_000})
    row = result["lines"][0]
    assert row["ref"] == "C2" and row["rankUsed"] == 2 and row["substitution"]
    assert checks_named(row) == ["substitution"]  # warning, not a blocker
    assert "C1" in row["note"] and "50" in row["note"]  # self-explaining report note
    assert result["escalations"] == []  # silent — no human needed


def test_avl_exhausted_escalates_with_choice_stocks(store):
    record(store.conn, "resistor", "22k", "0603", lcsc="C1")
    record(store.conn, "resistor", "22k", "0603", lcsc="C2", rank=2)
    result, _ = run(store, [spec_line("R1")], 100, {"C1": 10, "C2": 20})
    row = result["lines"][0]
    assert row["ref"] is None
    assert checks_named(row) == ["avl-exhausted"]  # 'unresolved' is emit-layer
    esc = result["escalations"][0]
    assert esc["reason"] == "avl-exhausted"
    assert [(c["ref"], c["liveStock"]) for c in esc["choices"]] == [
        ("C1", 10), ("C2", 20)]  # seeds the alternates search


def test_no_part_choices_escalates(store):
    result, src = run(store, [spec_line("R9", value="47k")], 5, {})
    row = result["lines"][0]
    assert checks_named(row) == ["no-part-choices"]
    assert result["escalations"][0]["reason"] == "no-part-choices"
    assert src.calls == []  # nothing to verify → no API call at all


def test_explicit_line_verified_only(store):
    line = RequirementLine(designators=["U1"], provider_refs={"jlcpcb": "C8734"},
                           comment="STM32")
    result, _ = run(store, [line], 25, {"C8734": 500})
    row = result["lines"][0]
    assert row["ref"] == "C8734" and row["source"] == "explicit"
    assert row["checks"] == []


def test_explicit_insufficient_and_not_in_catalog(store):
    lines = [RequirementLine(designators=["U1"], provider_refs={"jlcpcb": "C8734"}),
             RequirementLine(designators=["U2"], provider_refs={"jlcpcb": "C404"})]
    result, _ = run(store, lines, 25, {"C8734": 10})
    short, gone = result["lines"]
    assert checks_named(short) == ["insufficient-stock"]
    assert short["ref"] == "C8734"  # still selected — the user decides
    assert checks_named(gone) == ["not-in-catalog"]
    assert [e["reason"] for e in result["escalations"]] == [
        "insufficient-stock", "not-in-catalog"]


def test_no_spec_no_code_line(store):
    result, _ = run(store, [RequirementLine(designators=["J1"])], 5, {})
    assert checks_named(result["lines"][0]) == ["no-code-uncheckable"]
    assert result["escalations"][0]["reason"] == "no-code"


def test_mpn_only_line_escalates_for_jlc(store):
    line = RequirementLine(designators=["U2"], mpn="AMS1117-3.3", manufacturer="AMS")
    result, _ = run(store, [line], 5, {})
    row = result["lines"][0]
    assert checks_named(row) == ["no-code-uncheckable"]
    assert "AMS1117-3.3" in row["checks"][0]["message"]
    assert result["escalations"][0]["mpn"] == "AMS1117-3.3"


def test_dnp_line_carried_never_resolved(store):
    record(store.conn, "resistor", "22k", "0603", lcsc="C1")
    lines = [spec_line("R1"),
             RequirementLine(designators=["TP1"], dnp=True, comment="testpoint")]
    result, src = run(store, lines, 25, {"C1": 10_000})
    dnp_row = result["lines"][1]
    assert dnp_row["dnp"] is True and dnp_row["ref"] is None
    assert checks_named(dnp_row) == ["dnp"]
    assert dnp_row["requiredQty"] == 0
    assert result["escalations"] == []  # DNP never escalates


def test_choice_records_survive_to_output_identity(store):
    record(store.conn, "resistor", "22k", "0603", lcsc="C1",
           mpn="0603WAF2202T5E", manufacturer="UNI-ROYAL")
    result, _ = run(store, [spec_line("R1")], 1, {"C1": 100})
    row = result["lines"][0]
    assert row["mpn"] == "0603WAF2202T5E" and row["manufacturer"] == "UNI-ROYAL"


def test_one_batched_call_and_cache_refresh(store):
    record(store.conn, "resistor", "22k", "0603", lcsc="C1")
    record(store.conn, "capacitor", "100n", "0603", lcsc="C3")
    lines = [spec_line("R1"),
             spec_line("C5", kind="capacitor", value="100n"),
             RequirementLine(designators=["U1"], provider_refs={"jlcpcb": "C9"})]
    _, src = run(store, lines, 10, {"C1": 100, "C3": 100, "C9": 100})
    assert len(src.calls) == 1 and src.calls[0] == ["C1", "C3", "C9"]
    # advisory cache refreshed as a side effect of the live verify
    cached = store.lookup(SpecKey("resistor", "22k", "0603"))["choices"][0]
    assert cached["lastStock"] == 100 and cached["lastVerifiedAt"]


def test_quantity_per_multiplies_and_survives_to_output(store):
    record(store.conn, "led", "red", "0603", lcsc="C7")
    line = spec_line("D1", kind="led", value="red", quantity_per=2)
    result, _ = run(store, [line], 30, {"C7": 1_000})
    assert result["lines"][0]["requiredQty"] == 60  # 1 designator × 2 each × 30
    assert result["lines"][0]["quantityPer"] == 2  # the fact record needs it


def test_price_break_at_required_qty(store):
    record(store.conn, "resistor", "22k", "0603", lcsc="C1")
    result, _ = run(store, [spec_line("R1", "R2", "R3", "R4")], 50, {"C1": 10_000})
    assert result["lines"][0]["unitPrice"] == 0.001  # required 200 → 100+ break


def test_output_feeds_bom_renderer(store):
    record(store.conn, "resistor", "22k", "0603", lcsc="C1")
    result, _ = run(store, [spec_line("R1", "R2", comment="22k", footprint="0603"),
                            spec_line("R9", value="47k")], 25, {"C1": 10_000})
    bom_lines = [BomLine.from_dict(x) for x in result["lines"]]  # superset contract
    csv_text = render_bom_csv(bom_lines)
    assert "22k,\"R1,R2\",0603,C1" in csv_text
    assert len(unresolved_lines(bom_lines)) == 1  # the 47k gap is visible + blocking


def test_load_request_json_validation(tmp_path):
    p = tmp_path / "req.json"
    p.write_text('{"lines": [{"designators": ["R1"], "spec": {"kind": "resistor", '
                 '"value": "22k", "package": "0603"}}]}')
    with pytest.raises(ValueError, match="productionQuantity"):
        load_request_json(p)
    p.write_text('{"productionQuantity": 25, "lines": [{"designators": [], '
                 '"lcsc": "C1"}]}')
    with pytest.raises(ValueError, match="designators"):
        load_request_json(p)
    p.write_text('{"productionQuantity": 25, "design": "comet", "lines": '
                 '[{"designators": ["R1"], "lcsc": "C1"}]}')
    req = load_request_json(p)
    assert req.design == "comet" and req.production_quantity == 25
    assert req.lines[0].provider_ref("jlcpcb") == "C1"


def test_escalation_report_reads_well(store):
    record(store.conn, "resistor", "22k", "0603", lcsc="C1")
    record(store.conn, "resistor", "22k", "0603", lcsc="C2", rank=2)
    result, _ = run(store, [spec_line("R1", "R2"), spec_line("R9", value="47k")],
                    25, {"C1": 40, "C2": 9_000}, design="comet")
    text = format_escalation_report(result)
    assert "1 ESCALATED" in text and "no-part-choices" in text
    assert "Substitutions (1)" in text


def test_escalation_report_explicit_line_has_no_rank_label(store):
    line = RequirementLine(designators=["U1"], provider_refs={"jlcpcb": "C9"})
    result, _ = run(store, [line], 25, {"C9": 3})
    text = format_escalation_report(result)
    assert "rank-None" not in text
    assert "C9: stock 3 < required 25" in text


def test_checks_table_severities():
    assert set(CHECKS.values()) == {"error", "warning", "info"}
    assert CHECKS["substitution"] == "warning"
    assert CHECKS["avl-exhausted"] == "error"
    assert CHECKS["dnp"] == "info"
