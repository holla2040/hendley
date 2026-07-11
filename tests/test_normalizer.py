"""Normalizer tests — extracted Fusion parts → canonical Requirements BOM."""

from hendley.ingestion.fusion.live_design import Placement
from hendley.ingestion.fusion.parts_json import DesignPart
from hendley.requirements import requirements_from_design


def _part(desig, value=None, lcsc=None, mpn=None, attrs=None):
    a = dict(attrs or {})
    if mpn:
        a.setdefault("MPN", mpn)
    return DesignPart(designator=desig, value=value, jlc_code=lcsc,
                      manufacturer_part=mpn, attributes=a)


def test_identical_parts_group_with_natural_sorted_designators():
    parts = [_part("R13", "22k", lcsc="C31850"), _part("R2", "22k", lcsc="C31850")]
    bom = requirements_from_design("comet", parts, 25)
    assert len(bom.lines) == 1
    assert bom.lines[0].designators == ["R2", "R13"]
    assert bom.lines[0].provider_refs == {"jlcpcb": "C31850"}
    assert bom.lines[0].required_qty(bom.production_quantity) == 50


def test_lcsc_wins_over_mpn_as_selection_mode():
    bom = requirements_from_design(
        None, [_part("U1", "STM32", lcsc="C8734", mpn="STM32F103C8T6")], 1)
    line = bom.lines[0]
    assert line.mode == "provider" and line.mpn is None


def test_mpn_line_carries_manufacturer_attribute():
    bom = requirements_from_design(
        None, [_part("U2", "LDO", mpn="AMS1117-3.3",
                     attrs={"MANUFACTURER": "AMS"})], 1)
    line = bom.lines[0]
    assert line.mode == "mpn"
    assert (line.mpn, line.manufacturer) == ("AMS1117-3.3", "AMS")


def test_dnp_attribute_and_populate_flag_mark_but_keep_lines():
    parts = [_part("TP1", attrs={"DNP": "1"}), _part("J2", "CONN-2")]
    placements = [Placement("J2", x=0, y=0, angle=0, populate=False)]
    bom = requirements_from_design(None, parts, 10, placements)
    by_desig = {ln.designators[0]: ln for ln in bom.lines}
    assert by_desig["TP1"].dnp is True
    assert by_desig["J2"].dnp is True  # board populate flag off
    assert by_desig["J2"].required_qty(10) == 0


def test_footprint_prefers_board_package_name():
    parts = [_part("R1", "22k", lcsc="C31850", attrs={"PACKAGE": "0603"})]
    placements = [Placement("R1", x=0, y=0, angle=0, footprint="R-0603")]
    bom = requirements_from_design(None, parts, 1, placements)
    assert bom.lines[0].footprint == "R-0603"


def test_comment_falls_back_to_mpn():
    bom = requirements_from_design(None, [_part("D1", "", mpn="1SMA4744A")], 1)
    assert bom.lines[0].comment == "1SMA4744A"


def test_bare_part_has_no_mode():
    bom = requirements_from_design(None, [_part("J1", "CONN-4")], 1)
    assert bom.lines[0].mode is None  # surfaces as a check downstream, not an error


def test_generic_passive_states_its_own_spec():
    parts = [_part("R10", "82K")]
    placements = [Placement("R10", x=0, y=0, angle=0, footprint="R-0402")]
    bom = requirements_from_design(None, parts, 1, placements)
    line = bom.lines[0]
    assert line.mode == "spec"
    assert (line.spec.kind, line.spec.value, line.spec.package) == \
        ("resistor", "82k", "0402")


def test_spec_inference_never_overrides_explicit_ids():
    parts = [_part("R1", "22k", lcsc="C31850")]
    placements = [Placement("R1", x=0, y=0, angle=0, footprint="R-0603")]
    bom = requirements_from_design(None, parts, 1, placements)
    assert bom.lines[0].mode == "provider" and bom.lines[0].spec is None


def test_equivalent_value_spellings_group_by_spec():
    parts = [_part("C9", ".1u"), _part("C11", "100n")]
    placements = [Placement("C9", x=0, y=0, angle=0, footprint="C-0603"),
                  Placement("C11", x=1, y=0, angle=0, footprint="C-0603")]
    bom = requirements_from_design(None, parts, 1, placements)
    # same canonical spec, but different comments keep separate lines is fine;
    # what matters: both lines carry the SAME spec key
    specs = {ln.spec for ln in bom.lines}
    assert len(specs) == 1 and next(iter(specs)).value == "100n"
