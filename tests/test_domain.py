"""Domain model tests — the canonical Requirements BOM contract."""

import pytest

from hendley.domain import (
    CHECKS,
    RequirementLine,
    RequirementsBom,
    SpecKey,
    make_check,
)


def test_spec_key_requires_kind_value_package():
    with pytest.raises(ValueError):
        SpecKey(kind="resistor", value="", package="0603")
    s = SpecKey.from_dict({"kind": "resistor", "value": "22k", "package": "0603"})
    assert s.qualifier == ""
    assert s.to_dict()["package"] == "0603"


def test_make_check_validates_names_and_stamps_severity():
    c = make_check("avl-exhausted", "no choice satisfies qty 500")
    assert c.severity == "error"
    with pytest.raises(ValueError):
        make_check("Made-Up-Check", "nope")
    # every table severity is one of the allowed three
    assert set(CHECKS.values()) <= {"error", "warning", "info"}


def test_line_rejects_multiple_selection_modes():
    with pytest.raises(ValueError, match="multiple selection modes"):
        RequirementLine(
            designators=["R1"],
            spec=SpecKey("resistor", "22k", "0603"),
            provider_refs={"jlcpcb": "C31850"},
        )
    with pytest.raises(ValueError, match="multiple selection modes"):
        RequirementLine(designators=["U1"], mpn="STM32F103C8T6",
                        provider_refs={"jlcpcb": "C8734"})


def test_line_mode_and_required_qty():
    line = RequirementLine(designators=["R1", "R4"], quantity_per=1,
                           spec=SpecKey("resistor", "22k", "0603"))
    assert line.mode == "spec"
    assert line.required_qty(25) == 50

    dnp = RequirementLine(designators=["TP1"], dnp=True)
    assert dnp.mode is None
    assert dnp.required_qty(25) == 0  # DNP lines need zero parts


def test_line_manufacturer_requires_mpn():
    with pytest.raises(ValueError, match="requires 'mpn'"):
        RequirementLine(designators=["U1"], manufacturer="ST")


def test_lcsc_shorthand_maps_to_provider_refs():
    line = RequirementLine.from_dict({"designators": ["U1"], "lcsc": "C8734"})
    assert line.provider_refs == {"jlcpcb": "C8734"}
    assert line.mode == "provider"
    # conflicting explicit providerRefs is an error, not a silent overwrite
    with pytest.raises(ValueError, match="conflicts"):
        RequirementLine.from_dict({"designators": ["U1"], "lcsc": "C8734",
                                   "providerRefs": {"jlcpcb": "C9999"}})


def test_bom_round_trip():
    bom = RequirementsBom(
        design="comet",
        production_quantity=25,
        lines=[
            RequirementLine(designators=["R1", "R4"], comment="22k", footprint="0603",
                            spec=SpecKey("resistor", "22k", "0603", "1%")),
            RequirementLine(designators=["U1"], comment="STM32F103C8T6",
                            provider_refs={"jlcpcb": "C8734"}),
            RequirementLine(designators=["TP1"], dnp=True, comment="testpoint"),
        ],
    )
    doc = bom.to_dict()
    assert doc["requirementsBomVersion"] == 1
    again = RequirementsBom.from_dict(doc)
    assert again.to_dict() == doc
    assert again.lines[0].spec.qualifier == "1%"
    assert again.lines[2].dnp is True


def test_bom_validation_is_loud():
    with pytest.raises(ValueError, match="productionQuantity"):
        RequirementsBom.from_dict({"productionQuantity": 0, "lines": [{}]})
    with pytest.raises(ValueError, match="lines"):
        RequirementsBom.from_dict({"productionQuantity": 1, "lines": []})
    with pytest.raises(ValueError, match="requirementsBomVersion"):
        RequirementsBom.from_dict({"requirementsBomVersion": 99,
                                   "productionQuantity": 1,
                                   "lines": [{"designators": ["R1"]}]})
    with pytest.raises(ValueError, match="quantityPer"):
        RequirementLine.from_dict({"designators": ["R1"], "quantityPer": 0})
