"""Tests for the resolution-JSON → JLCPCB BOM CSV renderer."""

import json

import pytest

from hendley.providers.jlcpcb.bom_csv import (
    BomLine,
    blocking_checks,
    error_checks,
    format_resolution_report,
    load_resolution_json,
    render_bom_csv,
    unresolved_lines,
    warning_checks,
)


def test_from_dict_requires_designators():
    with pytest.raises(ValueError):
        BomLine.from_dict({"comment": "22k"})
    with pytest.raises(ValueError):
        BomLine.from_dict({"designators": []})


def test_from_dict_rejects_unknown_source():
    with pytest.raises(ValueError):
        BomLine.from_dict({"designators": ["R1"], "source": "guess"})


def test_from_dict_accepts_ref_and_lcsc_spellings():
    assert BomLine.from_dict({"designators": ["R1"], "ref": "C1"}).ref == "C1"
    assert BomLine.from_dict({"designators": ["R1"], "lcsc": "C1"}).ref == "C1"


def test_load_resolution_json_object_and_list_forms(tmp_path):
    f = tmp_path / "resolution.json"
    f.write_text(json.dumps({
        "design": "comet",
        "productionQuantity": 25,
        "lines": [{"designators": ["R1", "R4"], "comment": "22k", "footprint": "0603",
                   "lcsc": "C31850", "source": "db", "requiredQty": 50}],
    }))
    design, n, lines, doc = load_resolution_json(f)
    assert design == "comet" and n == 25
    assert lines[0].designators == ["R1", "R4"] and lines[0].ref == "C31850"
    assert lines[0].required_qty == 50
    assert doc["design"] == "comet"  # the raw doc rides along for the snapshot

    f.write_text(json.dumps([{"designators": ["U1"], "lcsc": "C82942"}]))  # bare-list form
    design, n, lines, doc = load_resolution_json(f)
    assert design is None and n is None and lines[0].ref == "C82942"
    assert lines[0].required_qty is None
    assert doc == {"lines": [{"designators": ["U1"], "lcsc": "C82942"}]}  # normalized

    f.write_text(json.dumps({"productionQuantity": 0, "lines": []}))
    with pytest.raises(ValueError, match="productionQuantity"):
        load_resolution_json(f)


def test_render_bom_csv_columns_grouping_and_quoting():
    lines = [
        BomLine(["R1", "R4"], comment="22k", footprint="0603", ref="C31850"),
        BomLine(["U1"], comment="MT3608, boost", footprint="SOT-23-6", ref="C82942"),
    ]
    csv_text = render_bom_csv(lines).splitlines()
    assert csv_text[0] == "Comment,Designator,Footprint,LCSC Part #"
    assert csv_text[1] == '22k,"R1,R4",0603,C31850'  # grouped designators quoted
    assert csv_text[2] == '"MT3608, boost",U1,SOT-23-6,C82942'  # comma in comment quoted


def test_render_bom_csv_unresolved_line_gets_blank_cell():
    csv_text = render_bom_csv([BomLine(["J1"], comment="USB-C", footprint="16P")])
    assert csv_text.splitlines()[1] == "USB-C,J1,16P,"


def test_dnp_lines_stay_out_of_csv_and_never_block():
    lines = [
        BomLine(["R1"], comment="22k", ref="C31850"),
        BomLine(["TP1"], comment="testpoint", dnp=True),
    ]
    csv_text = render_bom_csv(lines)
    assert "TP1" not in csv_text
    assert unresolved_lines(lines) == []  # a code-less DNP line is not a gap
    assert blocking_checks(lines) == []
    report = format_resolution_report(None, lines)
    assert "DNP (1)" in report and "READY TO UPLOAD" in report


def test_unresolved_lines():
    lines = [BomLine(["R1"], ref="C31850"), BomLine(["J1"]), BomLine(["J2"], ref="")]
    assert [x.designators for x in unresolved_lines(lines)] == [["J1"], ["J2"]]


def test_report_all_resolved():
    lines = [
        BomLine(["R1", "R4"], comment="22k", footprint="0603", ref="C31850",
                source="db", note="house part"),
        BomLine(["U1"], comment="MT3608", footprint="SOT-23-6", ref="C82942",
                source="explicit"),
    ]
    out = format_resolution_report("comet", lines)
    assert "BOM resolution for comet" in out
    assert "3 part(s)" in out and "READY TO UPLOAD" in out
    assert "1 db" in out and "1 explicit" in out
    assert "R1,R4" in out and "(db; house part)" in out


def test_report_flags_unresolved_loudly():
    out = format_resolution_report(None, [BomLine(["J1"], comment="USB-C")])
    assert "1 BLOCKER(S) — DO NOT UPLOAD" in out
    assert "do not upload until fixed" in out and "— NO PART —" in out


def test_checks_severity_split_and_validation():
    sub = {"check": "substitution", "severity": "warning", "message": "R1: used rank-2"}
    short = {"check": "insufficient-stock", "severity": "error",
             "message": "U1: stock 10 < required 250"}
    lines = [BomLine(["R1"], ref="C2", checks=[sub]),
             BomLine(["U1"], ref="C9", checks=[short]),
             BomLine(["C5"], ref="C14663")]  # no checks at all — fine
    assert [c["check"] for _, c in error_checks(lines)] == ["insufficient-stock"]
    assert [c["check"] for _, c in warning_checks(lines)] == ["substitution"]
    with pytest.raises(ValueError, match="checks"):
        BomLine.from_dict({"designators": ["R1"], "checks": [{"oops": True}]})
    parsed = BomLine.from_dict({"designators": ["R1"], "lcsc": "C2", "checks": [sub]})
    assert parsed.checks == [sub]


def test_unknown_severity_is_rejected_not_ignored():
    # An unrecognized severity must fail loudly at intake — anything that
    # slipped past error_checks() would emit cleanly and write a snapshot.
    bad = {"check": "insufficient-stock", "severity": "Error", "message": "short"}
    with pytest.raises(ValueError, match="severity"):
        BomLine.from_dict({"designators": ["U1"], "lcsc": "C9", "checks": [bad]})


def test_info_severity_is_legal_and_never_blocks():
    info = {"check": "dnp", "severity": "info", "message": "TP1: do-not-populate"}
    line = BomLine.from_dict({"designators": ["TP1"], "dnp": True, "checks": [info]})
    assert blocking_checks([line]) == []


def test_blocking_checks_single_pass():
    # one ref-less line + one error-checked line: both blockers in ONE call
    lines = [
        BomLine(["R9"], comment="47k"),  # no code, no checks (hand-composed)
        BomLine(["U1"], ref="C9", checks=[
            {"check": "insufficient-stock", "severity": "error", "message": "short"}]),
        BomLine(["R1"], ref="C2"),  # clean
    ]
    got = sorted(c["check"] for _, c in blocking_checks(lines))
    assert got == ["insufficient-stock", "unresolved"]


def test_report_lists_checks_by_severity():
    lines = [
        BomLine(["R1", "R4"], ref="C2", checks=[
            {"check": "substitution", "severity": "warning",
             "message": "R1,R4: rank-1 C1 stock 40 < required 50 → used rank-2 C2"}]),
        BomLine(["U1"], ref="C9", checks=[
            {"check": "insufficient-stock", "severity": "error",
             "message": "U1: C9 stock 10 < required 25"}]),
    ]
    out = format_resolution_report("comet", lines)
    assert "Checks: 1 error(s), 1 warning(s)" in out
    assert "ERROR insufficient-stock" in out and "warn  substitution" in out
    # every line has an LCSC code, but the error check still blocks — and the
    # headline must say so (a headline/exit-code contradiction is how a short
    # order gets uploaded).
    assert "1 BLOCKER(S) — DO NOT UPLOAD" in out


def test_report_shows_board_count_and_required_qty():
    lines = [BomLine(["R1", "R4"], comment="22k", ref="C31850", required_qty=50)]
    out = format_resolution_report("comet", lines, production_quantity=25)
    assert "2 part(s)/board × 25 board(s)" in out
    assert "need 50" in out
    # and quantity is genuinely optional — plain hand-composed JSON still renders
    out = format_resolution_report(None, [BomLine(["U1"], ref="C1")])
    assert "board(s)" not in out and "need" not in out
