"""Tests for the resolution-JSON → JLCPCB BOM CSV renderer."""

import json

import pytest

from hendley.bom import (
    BomLine,
    format_resolution_report,
    load_resolution_json,
    render_bom_csv,
    unresolved_lines,
)


def test_from_dict_requires_designators():
    with pytest.raises(ValueError):
        BomLine.from_dict({"comment": "22k"})
    with pytest.raises(ValueError):
        BomLine.from_dict({"designators": []})


def test_from_dict_rejects_unknown_source():
    with pytest.raises(ValueError):
        BomLine.from_dict({"designators": ["R1"], "source": "guess"})


def test_load_resolution_json_object_and_list_forms(tmp_path):
    f = tmp_path / "resolution.json"
    f.write_text(json.dumps({
        "design": "comet",
        "lines": [{"designators": ["R1", "R4"], "comment": "22k", "footprint": "0603",
                   "lcsc": "C31850", "source": "db"}],
    }))
    design, lines = load_resolution_json(f)
    assert design == "comet"
    assert lines[0].designators == ["R1", "R4"] and lines[0].lcsc == "C31850"

    f.write_text(json.dumps([{"designators": ["U1"], "lcsc": "C82942"}]))  # bare-list form
    design, lines = load_resolution_json(f)
    assert design is None and lines[0].lcsc == "C82942"


def test_render_bom_csv_columns_grouping_and_quoting():
    lines = [
        BomLine(["R1", "R4"], comment="22k", footprint="0603", lcsc="C31850"),
        BomLine(["U1"], comment="MT3608, boost", footprint="SOT-23-6", lcsc="C82942"),
    ]
    csv_text = render_bom_csv(lines).splitlines()
    assert csv_text[0] == "Comment,Designator,Footprint,LCSC Part #"
    assert csv_text[1] == '22k,"R1,R4",0603,C31850'  # grouped designators quoted
    assert csv_text[2] == '"MT3608, boost",U1,SOT-23-6,C82942'  # comma in comment quoted


def test_render_bom_csv_unresolved_line_gets_blank_cell():
    csv_text = render_bom_csv([BomLine(["J1"], comment="USB-C", footprint="16P")])
    assert csv_text.splitlines()[1] == "USB-C,J1,16P,"


def test_unresolved_lines():
    lines = [BomLine(["R1"], lcsc="C31850"), BomLine(["J1"]), BomLine(["J2"], lcsc="")]
    assert [x.designators for x in unresolved_lines(lines)] == [["J1"], ["J2"]]


def test_report_all_resolved():
    lines = [
        BomLine(["R1", "R4"], comment="22k", footprint="0603", lcsc="C31850",
                source="db", note="house part"),
        BomLine(["U1"], comment="MT3608", footprint="SOT-23-6", lcsc="C82942",
                source="explicit"),
    ]
    out = format_resolution_report("comet", lines)
    assert "BOM resolution for comet" in out
    assert "3 part(s)" in out and "ALL RESOLVED" in out
    assert "1 db" in out and "1 explicit" in out
    assert "R1,R4" in out and "(db; house part)" in out


def test_report_flags_unresolved_loudly():
    out = format_resolution_report(None, [BomLine(["J1"], comment="USB-C")])
    assert "1 UNRESOLVED" in out
    assert "do not upload" in out and "— NO PART —" in out
