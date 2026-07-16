"""Normalizer tests — extracted Fusion parts → canonical Requirements BOM."""

from hendley.ingestion.fusion.live_design import Placement
from hendley.ingestion.fusion.parts_json import DesignPart
from hendley.requirements import has_zener_evidence, requirements_from_design


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


def test_a_family_in_the_value_is_a_seed_not_a_spec():
    # The designer types ULN2003 into the VALUE, because the value shows on the
    # schematic. That is a family: it ships in SOIC-16, SOP-16, TSSOP-16 and DIP-16,
    # and the FOOTPRINT decides which of them may go on this board.
    part = DesignPart(designator="U1", value="ULN2003", footprint="SO16",
                      footprint_headline="Small Outline package 150 mil")
    line = requirements_from_design(None, [part], 1).lines[0]
    assert line.family == "ULN2003"
    assert line.mode is None                # NOT pinned — nothing to order yet
    assert line.footprint == "SO16"
    assert line.footprint_headline == "Small Outline package 150 mil"


def test_unresolved_same_value_semiconductors_stay_separate_for_visual_reading():
    parts = [
        DesignPart(designator="Q2", value="40V", footprint="SOT23-3"),
        DesignPart(designator="Q3", value="40V", footprint="SOT23-3"),
    ]

    bom = requirements_from_design(None, parts, 1)

    assert [line.designators for line in bom.lines] == [["Q2"], ["Q3"]]
    assert all(line.family == "40V" for line in bom.lines)


def test_a_family_in_the_mpn_attribute_does_not_pin_the_line():
    # THE BUG THIS FIXES. A family in the MPN attribute used to land in `mpn`, so
    # the line was PINNED: Hendley treated "ULN2003" as an exact orderable part,
    # never sieved it, and shipped it to the resolver as if it were real.
    part = DesignPart(designator="U1", manufacturer_part="ULN2003",
                      footprint="SO16", attributes={"MPN": "ULN2003"})
    line = requirements_from_design(None, [part], 1).lines[0]
    assert line.family == "ULN2003"
    assert line.mpn is None and line.mode is None


def test_the_mpn_attribute_outranks_the_value_as_the_family():
    part = DesignPart(designator="U1", value="a darlington array",
                      manufacturer_part="ULN2003", footprint="SO16")
    assert requirements_from_design(None, [part], 1).lines[0].family == "ULN2003"


def test_a_family_needs_a_footprint_to_be_resolvable():
    # family + footprint → package → the parts. With no footprint there is nothing
    # to narrow with, and searching a bare family would offer every package it
    # ships in. That stays a decision for the engineer.
    part = DesignPart(designator="U1", value="ULN2003")
    assert requirements_from_design(None, [part], 1).lines[0].family is None


def test_a_pinned_part_is_never_treated_as_a_family():
    part = DesignPart(designator="U3", value="MB10S", jlc_code="C2886577",
                      footprint="SOIC-4")
    line = requirements_from_design(None, [part], 1).lines[0]
    assert line.family is None and line.mode == "provider"


def test_a_passive_states_a_spec_and_is_never_a_family():
    # "22k" is a value, not a family. R/C/L keep the deterministic spec path.
    part = DesignPart(designator="R1", value="22k", footprint="R-0603")
    line = requirements_from_design(None, [part], 1).lines[0]
    assert line.family is None and line.mode == "spec"


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


def test_zener_evidence_requires_z_in_a_diode_specification():
    assert has_zener_evidence("D1", "VZ10")
    assert has_zener_evidence("D2", "10Z0")
    assert has_zener_evidence("D3", "10V", {"TYPE": "Zener"})
    assert not has_zener_evidence("D4", "10V0")
    assert not has_zener_evidence("D5", "1000V")
    assert not has_zener_evidence("R1", "VZ10")


def test_zener_evidence_scans_attribute_values_not_names_or_metadata():
    assert not has_zener_evidence("D1", "10V", {"SIZE": "SOD-323"})
    assert not has_zener_evidence("D2", "10V", {"MANUFACTURER": "Zetex"})
    assert not has_zener_evidence("D3", "10V", {"MP": "BZT52C10"})
    assert has_zener_evidence("D4", "10V", {"DESCRIPTION": "zener clamp"})


def test_requirement_carries_attributes_to_the_interpreter_boundary():
    part = DesignPart(designator="D1", value="10V", footprint="D-SOD323",
                      attributes={"TYPE": "Zener"})
    line = requirements_from_design(None, [part], 1).lines[0]
    assert line.attributes == {"TYPE": "Zener"}
    assert line.to_dict()["attributes"] == {"TYPE": "Zener"}


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


def test_a_dnp_part_names_no_family():
    # a DNP part's VALUE is often literally "DNP". Searching for it would fire a
    # nonsense query — and a paid web lookup — for a part that is not being fitted.
    part = DesignPart(designator="U9", value="DNP", footprint="SO16")
    line = requirements_from_design(None, [part], 1).lines[0]
    assert line.dnp is True and line.family is None
