"""Tests for the Fusion .scr migration-script generator."""

import json

import pytest

from hendley.scr import PartSwap, load_swaps_json, render_script


def test_from_dict_aliases_and_order():
    s = PartSwap.from_dict(
        {"designator": "R2", "package": "-0402",
         "lcsc": "C25768", "manufacturer": "UNI-ROYAL", "mpn": "0402WGF2202TCE"}
    )
    assert s.designator == "R2"
    assert s.package == "-0402"
    # canonical alias order preserved
    assert list(s.attributes.items()) == [
        ("LCSC", "C25768"), ("MANUFACTURER", "UNI-ROYAL"), ("MPN", "0402WGF2202TCE")
    ]


def test_explicit_attributes_override_aliases_and_flow_through():
    s = PartSwap.from_dict(
        {"designator": "R1", "lcsc": "C1", "attributes": {"LCSC": "C2", "DESC": "1%"}}
    )
    assert s.attributes["LCSC"] == "C2"  # explicit wins
    assert s.attributes["DESC"] == "1%"  # arbitrary attrs pass through


def test_variant_alias_for_package():
    s = PartSwap.from_dict({"designator": "R1", "variant": "-0805", "lcsc": "C1"})
    assert s.package == "-0805"


def test_render_changes_package_before_attributes():
    lines = PartSwap.from_dict(
        {"designator": "R4", "package": "-0402", "lcsc": "C25768", "manufacturer": "UNI-ROYAL"}
    ).render()
    assert lines == [
        "CHANGE PACKAGE '-0402' R4;",
        "ATTRIBUTE R4 LCSC 'C25768';",
        "ATTRIBUTE R4 MANUFACTURER 'UNI-ROYAL';",
    ]


def test_render_attributes_only_when_no_package():
    lines = PartSwap.from_dict({"designator": "R8", "lcsc": "C25744"}).render()
    assert lines == ["ATTRIBUTE R8 LCSC 'C25744';"]


def test_empty_swap_rejected():
    with pytest.raises(ValueError):
        PartSwap.from_dict({"designator": "R1"}).render()


def test_designator_required():
    with pytest.raises(ValueError):
        PartSwap.from_dict({"lcsc": "C1"})


@pytest.mark.parametrize("payload", [
    {"designator": "R1", "lcsc": "C1'; DELETE"},        # quote + semicolon in value
    {"designator": "R1;EXPORT", "lcsc": "C1"},          # semicolon in designator
    {"designator": "R 1", "lcsc": "C1"},                # space in designator
    {"designator": "R1", "attributes": {"LC SC": "C1"}},  # space in attr name
])
def test_injection_chars_rejected(payload):
    with pytest.raises(ValueError):
        PartSwap.from_dict(payload).render()


def test_value_may_contain_spaces():
    lines = PartSwap.from_dict({"designator": "R1", "attributes": {"DESC": "1% 1/16W"}}).render()
    assert lines == ["ATTRIBUTE R1 DESC '1% 1/16W';"]


def test_render_script_header_and_blocks():
    swaps = [
        PartSwap.from_dict({"designator": "R1", "package": "-0402", "lcsc": "C25768"}),
        PartSwap.from_dict({"designator": "R2", "package": "-0402", "lcsc": "C25768"}),
    ]
    out = render_script(swaps, design="comet")
    assert out.startswith("# Hendley-generated")
    assert "# Design: comet" in out
    assert "# Parts: 2" in out
    assert "CHANGE PACKAGE '-0402' R1;" in out
    assert "CHANGE PACKAGE '-0402' R2;" in out
    assert out.endswith("\n")


def test_load_swaps_json_object_and_list(tmp_path):
    f = tmp_path / "swaps.json"
    f.write_text(json.dumps({"design": "comet", "swaps": [{"designator": "R1", "lcsc": "C1"}]}))
    swaps = load_swaps_json(f)
    assert len(swaps) == 1 and swaps[0].attributes["LCSC"] == "C1"

    f.write_text(json.dumps([{"designator": "R2", "mpn": "X"}]))
    swaps = load_swaps_json(f)
    assert swaps[0].designator == "R2" and swaps[0].attributes["MPN"] == "X"
