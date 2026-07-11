"""Tests for the JLCPCB order-file (BOM + CPL) builders — offline, no bridge."""

import csv
import json

from hendley.fusion import DesignPart
from hendley.pcba import (
    BOM_FIELDS,
    CPL_FIELDS,
    Placement,
    build_bom_rows,
    build_cpl_rows,
    is_dnp,
    is_pseudo_part,
    load_rotations,
    natural_key,
    part_from_row,
    rotation_for,
    write_csv,
)


def _r(designator, code, value="10k", footprint="R-0603", x=1.0, y=2.0, angle=0):
    part = DesignPart(designator, jlc_code=code, value=value)
    placement = Placement(designator, x=x, y=y, angle=angle, footprint=footprint)
    return part, placement


def test_natural_key_orders_r2_before_r13():
    desigs = ["R13", "R2", "C1", "U1", "R1"]
    assert sorted(desigs, key=natural_key) == ["C1", "R1", "R2", "R13", "U1"]


def test_pseudo_part_rules():
    # GND/supply symbols carry no package
    assert is_pseudo_part({"name": "GND1", "package3d_object_id": 0}, {})
    # title block: U$ prefix and no part identity
    assert is_pseudo_part({"name": "U$1", "package3d_object_id": 7}, {})
    # ...but a U$-named part WITH an LCSC code is real
    assert not is_pseudo_part({"name": "U$2", "package3d_object_id": 7}, {"LCSC": "C1"})
    assert not is_pseudo_part({"name": "R1", "package3d_object_id": 7}, {})


def test_part_from_row_maps_attributes():
    p = part_from_row(
        {"name": "R6", "value": "220", "object_id": 5},
        {"LCSC": "C29719", "MP": "4D03WGJ0221T5E", "PACKAGE": "0603x4"},
    )
    assert p.jlc_code == "C29719"
    assert p.manufacturer_part == "4D03WGJ0221T5E"  # MP fallback when MPN absent
    assert p.value == "220" and p.package == "0603x4"


def test_bom_groups_identical_parts_and_sorts_designators():
    p1, pl1 = _r("R13", "C31850", value="22k")
    p2, pl2 = _r("R2", "C31850", value="22k")
    p3, pl3 = _r("C1", "C15849", value="1u", footprint="C-0603")
    rows = build_bom_rows([p1, p2, p3], [pl1, pl2, pl3])
    assert len(rows) == 2
    r22k = next(r for r in rows if r["JLCPCB Part #"] == "C31850")
    assert r22k["Designator"] == "R2,R13"  # natural order, not lexicographic
    assert r22k["Footprint"] == "R-0603"


def test_bom_comment_falls_back_to_mpn():
    part = DesignPart("D6", jlc_code="C19077482", value="", manufacturer_part="1SMA4744A")
    placement = Placement("D6", x=0, y=0, angle=0, footprint="DO-214AC(SMA)")
    rows = build_bom_rows([part], [placement])
    assert rows[0]["Comment"] == "1SMA4744A"


def test_dnp_parts_are_left_out_of_bom_and_cpl():
    p1, pl1 = _r("R1", "C1")
    p2, pl2 = _r("R2", "C1")
    pl2.populate = False
    bom = build_bom_rows([p1, p2], [pl1, pl2])
    assert bom[0]["Designator"] == "R1"
    cpl, _ = build_cpl_rows([p1, p2], [pl1, pl2])
    assert [r["Designator"] for r in cpl] == ["R1"]


def test_is_dnp_reads_the_schematic_attribute():
    assert is_dnp(DesignPart("M+", attributes={"DNP": "1"}))
    assert is_dnp(DesignPart("JP", attributes={"DNP": "true"}))
    # empty or "0" means populate; so does no DNP attribute at all
    assert not is_dnp(DesignPart("R1", attributes={"DNP": ""}))
    assert not is_dnp(DesignPart("R1", attributes={"DNP": "0"}))
    assert not is_dnp(DesignPart("R1"))


def test_dnp_attribute_excludes_part_from_bom_and_cpl():
    p1, pl1 = _r("R1", "C1")
    p2, pl2 = _r("M+", None, value="", footprint="TPTHRU-SLOT-1-3")
    p2.attributes = {"DNP": "1"}
    bom = build_bom_rows([p1, p2], [pl1, pl2])
    assert [r["Designator"] for r in bom] == ["R1"]
    cpl, _ = build_cpl_rows([p1, p2], [pl1, pl2])
    assert [r["Designator"] for r in cpl] == ["R1"]


def test_cpl_rows_and_layer_mapping():
    part, placement = _r("R1", "C1", x=-11.5, y=-5.2, angle=120)
    placement.mirror = True
    rows, applied = build_cpl_rows([part], [placement])
    assert rows == [
        {"Designator": "R1", "Mid X": "-11.5mm", "Mid Y": "-5.2mm",
         "Layer": "Bottom", "Rotation": 120}
    ]
    assert applied == []


def test_rotation_correction_matches_lcsc_or_footprint_and_wraps():
    corrections = [
        {"lcsc": "C19077482", "footprint": "DO-214AC(SMA)", "rotationOffsetDeg": 90},
        {"footprint": "SOT-23", "rotationOffsetDeg": 180},
    ]
    assert rotation_for(corrections, "C19077482", None)["rotationOffsetDeg"] == 90
    assert rotation_for(corrections, None, "SOT-23")["rotationOffsetDeg"] == 180
    assert rotation_for(corrections, "C999", "R-0603") is None

    part, placement = _r("D6", "C19077482", angle=300, footprint="DO-214AC(SMA)")
    rows, applied = build_cpl_rows([part], [placement], corrections)
    assert rows[0]["Rotation"] == 30  # (300 + 90) % 360
    assert applied[0]["designator"] == "D6" and applied[0]["rawAngle"] == 300


def test_load_rotations_missing_db_is_empty(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # nothing to walk up to
    assert load_rotations() == []


def test_load_rotations_walks_up_from_cwd(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "cpl-rotations.json").write_text(
        json.dumps({"corrections": [{"lcsc": "C1", "rotationOffsetDeg": 90}]})
    )
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)
    assert load_rotations()[0]["lcsc"] == "C1"


def test_write_csv_headers_and_rows(tmp_path):
    part, placement = _r("R1", "C1")
    rows, _ = build_cpl_rows([part], [placement])
    out = tmp_path / "cpl.csv"
    write_csv(rows, CPL_FIELDS, out)
    with out.open() as f:
        parsed = list(csv.reader(f))
    assert parsed[0] == list(CPL_FIELDS)
    assert parsed[1] == ["R1", "1.0mm", "2.0mm", "Top", "0"]

    bom = build_bom_rows([part], [placement])
    write_csv(bom, BOM_FIELDS, tmp_path / "bom.csv")
    with (tmp_path / "bom.csv").open() as f:
        assert next(csv.reader(f)) == list(BOM_FIELDS)
