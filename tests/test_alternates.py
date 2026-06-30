"""Tests for the alternate-part discovery + verify pipeline.

All offline: the jlcsearch fetch is injected, and a FakeClient stands in for the
live JLC API, so no network is touched.
"""

import json

import pytest

from hendley.alternates import (
    discover_and_verify,
    fetch_candidates,
    format_alternates_report,
    normalize_code,
    parse_param_args,
)


class FakeClient:
    """Stand-in JLCClient: records calls and returns canned detail rows."""

    def __init__(self, details: dict[str, dict]):
        self._details = details
        self.calls: list[list[str]] = []

    def get_component_detail_by_code(self, codes):
        self.calls.append(list(codes))
        return [self._details[c] for c in codes if c in self._details]


def _attrs(d: dict) -> str:
    return json.dumps(d)


def _fake_jlcsearch(rows, key="mosfets"):
    """Build an injectable fetch returning a canned jlcsearch list.json doc."""

    def fetch(url, params):
        fetch.last = (url, params)
        return {key: rows}

    fetch.last = None
    return fetch


# -- small helpers -----------------------------------------------------------

def test_normalize_code_handles_int_str_and_prefix():
    assert normalize_code(315567) == "C315567"
    assert normalize_code("315567") == "C315567"
    assert normalize_code("C315567") == "C315567"
    assert normalize_code("c25091") == "c25091"  # already prefixed (any case)
    assert normalize_code("") == ""


def test_parse_param_args():
    assert parse_param_args(["resistance=220", "package=0402"]) == {
        "resistance": "220",
        "package": "0402",
    }
    # value may contain '=' (e.g. an attribute)
    assert parse_param_args(["a=b=c"]) == {"a": "b=c"}
    with pytest.raises(ValueError):
        parse_param_args(["nope"])
    with pytest.raises(ValueError):
        parse_param_args(["=v"])


# -- fetch_candidates --------------------------------------------------------

def test_fetch_candidates_normalizes_rows_and_keeps_order():
    rows = [
        {"lcsc": 111, "mfr": "A", "package": "DFN-8(3x3)", "stock": 50,
         "price1": 0.1, "is_basic": False, "attributes": _attrs({"Vds": "30V"})},
        {"lcsc": 222, "mfr": "B", "package": "DFN-8(3x3)", "stock": 999,
         "price1": 0.2, "is_basic": True, "attributes": _attrs({"Vds": "60V"})},
    ]
    cands = fetch_candidates("mosfets", {"package": "DFN-8(3x3)"}, fetch=_fake_jlcsearch(rows))
    assert [c["code"] for c in cands] == ["C111", "C222"]  # source order preserved
    assert cands[0]["attributes"] == {"Vds": "30V"}  # attribute JSON string decoded
    assert cands[1]["is_basic"] is True


def test_fetch_candidates_single_list_fallback():
    # response key does not equal the category slug → use the lone list value
    def fetch(url, params):
        return {"weird_key": [{"lcsc": 7, "mfr": "X", "package": "0402"}]}

    cands = fetch_candidates("mosfets", {}, fetch=fetch)
    assert cands[0]["code"] == "C7"


# -- discover_and_verify -----------------------------------------------------

def _result():
    rows = [
        {"lcsc": 315567, "mfr": "AON7544", "package": "DFN-8(3x3)", "stock": 55303,
         "price1": 0.12, "is_basic": False, "attributes": "{}"},          # the target itself
        # verified candidate; its live stock differs from the stale jlcsearch stock
        {"lcsc": 2758429, "mfr": "WSD3056DN33", "package": "DFN-8(3x3)", "stock": 14101,
         "price1": 0.10, "is_basic": False, "attributes": "{}"},
        {"lcsc": 99999, "mfr": "GHOST", "package": "DFN-8(3x3)", "stock": 800,
         "price1": 0.05, "is_basic": False, "attributes": "{}"},          # NOT in live API
    ]
    client = FakeClient({
        "C315567": {"componentCode": "C315567", "componentModel": "AON7544",
                    "componentSpecification": "DFN-8(3x3)", "libraryType": "expand",
                    "stockCount": 252404, "description": "30V 30A",
                    "priceRanges": [{"startQuantity": 1, "unitPrice": 0.1173}]},
        "C2758429": {"componentCode": "C2758429", "componentModel": "WSD3056DN33",
                     "componentSpecification": "DFN-8(3x3)", "libraryType": "expand",
                     "stockCount": 9000, "description": "30V 35A",
                     "priceRanges": [{"startQuantity": 1, "unitPrice": 0.09}]},
    })
    result = discover_and_verify(
        "C315567", "mosfets", {"package": "DFN-8(3x3)"}, client,
        fetch=_fake_jlcsearch(rows),
    )
    return result, client


def test_discover_excludes_target_and_verifies_all_in_one_call():
    result, client = _result()
    codes = [c["code"] for c in result["candidates"]]
    assert "C315567" not in codes               # target excluded from candidates
    assert codes == ["C2758429", "C99999"]      # order preserved
    assert result["totalFound"] == 2
    # exactly one batched verify call, covering target + both candidates
    assert len(client.calls) == 1
    assert set(client.calls[0]) == {"C315567", "C2758429", "C99999"}


def test_live_stock_overrides_stale_index_and_flags_unverified():
    result, _ = _result()
    by_code = {c["code"]: c for c in result["candidates"]}
    # verified candidate: live stock from API, jlcsearch stock retained for comparison
    assert by_code["C2758429"]["verified"] is True
    assert by_code["C2758429"]["liveStock"] == 9000
    assert by_code["C2758429"]["jlcsearchStock"] == 14101
    assert by_code["C2758429"]["unitPrice1"] == 0.09
    # unverified candidate: present in jlcsearch, absent from the live API
    assert by_code["C99999"]["verified"] is False
    assert by_code["C99999"]["liveStock"] is None
    # target summary reflects the live API
    assert result["target"]["liveStock"] == 252404
    assert result["target"]["model"] == "AON7544"


# -- report ------------------------------------------------------------------

def test_report_shows_target_candidates_and_disclaimers():
    result, _ = _result()
    out = format_alternates_report(result)
    assert "C315567" in out and "AON7544" in out      # target
    assert "C2758429" in out                            # candidate
    assert "252,404" in out                             # live target stock, formatted
    assert "NOT a recommendation" in out               # no-ranking disclaimer
    assert "[UNVERIFIED]" in out                        # the ghost candidate
    assert "C99999" in out                              # listed in the unverified footer


def test_report_top_cap_notes_truncation():
    result, _ = _result()
    out = format_alternates_report(result, top=1)
    assert "showing first 1 of 2" in out
    assert "C2758429" in out          # first candidate shown
    # second candidate not shown in the table body, but still in unverified footer
