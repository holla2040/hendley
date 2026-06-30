"""Tests for the Fusion parts-export ingest contract."""

import json

import pytest

from hendley.fusion import DesignPart, check_stock, format_stock_report, load_parts_json


class FakeClient:
    """Stand-in JLCClient: returns canned detail rows for known codes."""

    def __init__(self, details: dict[str, dict]):
        self._details = details

    def get_component_detail_by_code(self, codes):
        return [self._details[c] for c in codes if c in self._details]


def test_from_dict_maps_fields_and_aliases():
    p = DesignPart.from_dict(
        {"designator": "R1", "mpn": "RC0402", "lcsc": "C25744", "quantity": 3, "value": "10k"}
    )
    assert p.designator == "R1"
    assert p.manufacturer_part == "RC0402"  # 'mpn' alias
    assert p.jlc_code == "C25744"  # 'lcsc' alias
    assert p.quantity == 3
    assert p.value == "10k"


def test_designator_is_required():
    with pytest.raises(ValueError):
        DesignPart.from_dict({"jlcCode": "C1"})


def test_load_parts_json_object_and_list_forms(tmp_path):
    obj = {"parts": [{"designator": "R1", "jlcCode": "C25744"}]}
    f = tmp_path / "parts.json"
    f.write_text(json.dumps(obj))
    parts = load_parts_json(f)
    assert len(parts) == 1 and parts[0].jlc_code == "C25744"

    f.write_text(json.dumps([{"designator": "U1"}]))  # bare-list form
    parts = load_parts_json(f)
    assert parts[0].designator == "U1" and parts[0].quantity == 1


def _stock_client():
    return FakeClient({
        "C1": {"componentCode": "C1", "stockCount": 500, "libraryType": "Basic"},
        "C2": {"componentCode": "C2", "stockCount": 0, "libraryType": "Extended"},
        "C3": {"componentCode": "C3", "stockCount": 50, "libraryType": "Basic"},
    })


def test_check_stock_classifies_each_status():
    parts = [
        DesignPart("R1", jlc_code="C1", quantity=2),  # stock 500 → ok
        DesignPart("R2", jlc_code="C2"),              # stock 0 → out
        DesignPart("R3", jlc_code="C3"),              # stock 50, min 100 → low
        DesignPart("R4", jlc_code="C9"),              # code not in catalog → not_found
        DesignPart("R5"),                             # no code → no_code
    ]
    rows = check_stock(parts, _stock_client(), min_stock=100)
    status = {r["designator"]: r["status"] for r in rows}
    assert status == {"R1": "ok", "R2": "out", "R3": "low", "R4": "not_found", "R5": "no_code"}
    # the C1 row carries through stock + libraryType for reporting
    r1 = next(r for r in rows if r["designator"] == "R1")
    assert r1["stockCount"] == 500 and r1["libraryType"] == "Basic"


def test_default_min_stock_only_flags_out_of_stock():
    parts = [DesignPart("R3", jlc_code="C3")]  # stock 50
    rows = check_stock(parts, _stock_client())  # min_stock defaults to 1
    assert rows[0]["status"] == "ok"  # 50 >= 1, not "low"


def test_format_stock_report_groups_and_headlines():
    parts = [DesignPart("R1", jlc_code="C1"), DesignPart("R2", jlc_code="C2")]
    rows = check_stock(parts, _stock_client())
    out = format_stock_report(rows)
    assert "OUT OF STOCK (1)" in out
    assert "In stock (1)" in out
    assert "1 blocker(s)" in out
    assert "R2" in out and "C2" in out


def test_format_report_all_ok_headline():
    rows = check_stock([DesignPart("R1", jlc_code="C1")], _stock_client())
    assert "ALL OK" in format_stock_report(rows)
