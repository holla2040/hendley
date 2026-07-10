"""Tests for the resolver — rank-walk, substitution, escalation, quantity math."""

import pytest

from hendley.bom import BomLine, render_bom_csv, unresolved_lines
from hendley.partsdb import lookup, open_db, record
from hendley.resolve import (
    CHECKS,
    ResolveLine,
    format_escalation_report,
    load_request_json,
    resolve,
)


class FakeClient:
    """Canned getComponentDetailByCode: {code: stock} → detail rows."""

    def __init__(self, stocks: dict[str, int], price: float = 0.002):
        self.stocks = stocks
        self.calls: list[list[str]] = []
        self.price = price

    def get_component_detail_by_code(self, codes):
        self.calls.append(list(codes))
        return [
            {"componentCode": c, "stockCount": self.stocks[c],
             "priceRanges": [{"startQuantity": 1, "unitPrice": self.price},
                             {"startQuantity": 100, "unitPrice": self.price / 2}]}
            for c in codes if c in self.stocks
        ]


@pytest.fixture
def db(tmp_path):
    conn = open_db(tmp_path / "parts.db")
    yield conn
    conn.close()


def spec_line(*designators, kind="resistor", value="22k", package="0603", **kw):
    return ResolveLine(designators=list(designators),
                       spec={"kind": kind, "value": value, "package": package,
                             "qualifier": kw.pop("qualifier", "")},
                       **kw)


def checks_named(row):
    return [c["check"] for c in row["checks"]]


def test_happy_path_rank1_no_checks(db):
    record(db, "resistor", "22k", "0603", "C1")
    client = FakeClient({"C1": 10_000})
    result = resolve(db, [spec_line("R1", "R2", comment="22k")], 25, client=client)
    row = result["lines"][0]
    assert row["lcsc"] == "C1" and row["rankUsed"] == 1 and not row["substitution"]
    assert row["source"] == "db" and row["requiredQty"] == 50  # 2 designators × 25
    assert row["offerType"] == "jlc-mounted"
    assert row["checks"] == [] and result["escalations"] == []


def test_silent_fallback_down_the_rank(db):
    record(db, "resistor", "22k", "0603", "C1")
    record(db, "resistor", "22k", "0603", "C2", rank=2)
    client = FakeClient({"C1": 40, "C2": 9_000})
    result = resolve(db, [spec_line("R1", "R2")], 25, client=client)  # required 50
    row = result["lines"][0]
    assert row["lcsc"] == "C2" and row["rankUsed"] == 2 and row["substitution"]
    assert checks_named(row) == ["substitution"]  # warning, not a blocker
    assert "C1" in row["note"] and "50" in row["note"]  # self-explaining report note
    assert result["escalations"] == []  # silent — no human needed


def test_avl_exhausted_escalates_with_choice_stocks(db):
    record(db, "resistor", "22k", "0603", "C1")
    record(db, "resistor", "22k", "0603", "C2", rank=2)
    client = FakeClient({"C1": 10, "C2": 20})
    result = resolve(db, [spec_line("R1")], 100, client=client)  # required 100
    row = result["lines"][0]
    assert row["lcsc"] is None
    assert checks_named(row) == ["avl-exhausted", "unresolved"]
    esc = result["escalations"][0]
    assert esc["reason"] == "avl-exhausted"
    assert [(c["lcscCode"], c["liveStock"]) for c in esc["choices"]] == [
        ("C1", 10), ("C2", 20)]  # seeds the alternates search


def test_no_part_choices_escalates(db):
    client = FakeClient({})
    result = resolve(db, [spec_line("R9", value="47k")], 5, client=client)
    row = result["lines"][0]
    assert checks_named(row) == ["no-part-choices", "unresolved"]
    assert result["escalations"][0]["reason"] == "no-part-choices"
    assert client.calls == []  # nothing to verify → no API call at all


def test_explicit_line_verified_only(db):
    client = FakeClient({"C8734": 500})
    line = ResolveLine(designators=["U1"], lcsc="C8734", comment="STM32")
    result = resolve(db, [line], 25, client=client)
    row = result["lines"][0]
    assert row["lcsc"] == "C8734" and row["source"] == "explicit"
    assert row["checks"] == []


def test_explicit_insufficient_and_not_in_catalog(db):
    client = FakeClient({"C8734": 10})
    lines = [ResolveLine(designators=["U1"], lcsc="C8734"),
             ResolveLine(designators=["U2"], lcsc="C404")]
    result = resolve(db, lines, 25, client=client)
    short, gone = result["lines"]
    assert checks_named(short) == ["insufficient-stock"]
    assert short["lcsc"] == "C8734"  # still selected — the user decides
    assert checks_named(gone) == ["not-in-catalog", "unresolved"]
    assert [e["reason"] for e in result["escalations"]] == [
        "insufficient-stock", "not-in-catalog"]


def test_no_spec_no_code_line(db):
    result = resolve(db, [ResolveLine(designators=["J1"])], 5, client=FakeClient({}))
    assert checks_named(result["lines"][0]) == ["no-code-uncheckable", "unresolved"]
    assert result["escalations"][0]["reason"] == "no-code"


def test_one_batched_call_and_cache_refresh(db):
    record(db, "resistor", "22k", "0603", "C1")
    record(db, "capacitor", "100n", "0603", "C3")
    client = FakeClient({"C1": 100, "C3": 100, "C9": 100})
    lines = [spec_line("R1"),
             spec_line("C5", kind="capacitor", value="100n"),
             ResolveLine(designators=["U1"], lcsc="C9")]
    resolve(db, lines, 10, client=client)
    assert len(client.calls) == 1 and client.calls[0] == ["C1", "C3", "C9"]
    # advisory cache refreshed as a side effect of the live verify
    cached = lookup(db, "resistor", "22k", "0603")["choices"][0]
    assert cached["lastStock"] == 100 and cached["lastVerifiedAt"]


def test_quantity_per_multiplies(db):
    record(db, "led", "red", "0603", "C7")
    client = FakeClient({"C7": 1_000})
    line = spec_line("D1", kind="led", value="red", quantity_per=2)
    result = resolve(db, [line], 30, client=client)
    assert result["lines"][0]["requiredQty"] == 60  # 1 designator × 2 each × 30


def test_price_break_at_required_qty(db):
    record(db, "resistor", "22k", "0603", "C1")
    client = FakeClient({"C1": 10_000}, price=0.002)
    result = resolve(db, [spec_line("R1", "R2", "R3", "R4")], 50, client=client)
    assert result["lines"][0]["unitPrice"] == 0.001  # required 200 → 100+ break


def test_output_feeds_bom_renderer(db):
    record(db, "resistor", "22k", "0603", "C1")
    client = FakeClient({"C1": 10_000})
    result = resolve(db, [spec_line("R1", "R2", comment="22k", footprint="0603"),
                          spec_line("R9", value="47k")], 25, client=client)
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
    design, n, lines = load_request_json(p)
    assert design == "comet" and n == 25 and lines[0].lcsc == "C1"


def test_escalation_report_reads_well(db):
    record(db, "resistor", "22k", "0603", "C1")
    record(db, "resistor", "22k", "0603", "C2", rank=2)
    client = FakeClient({"C1": 40, "C2": 9_000})
    result = resolve(db, [spec_line("R1", "R2"), spec_line("R9", value="47k")],
                     25, client=client, design="comet")
    text = format_escalation_report(result)
    assert "1 ESCALATED" in text and "no-part-choices" in text
    assert "Substitutions (1)" in text


def test_checks_table_severities():
    assert set(CHECKS.values()) == {"error", "warning"}
    assert CHECKS["substitution"] == "warning"
    assert CHECKS["avl-exhausted"] == "error"
