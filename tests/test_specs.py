"""Spec inference — generic parts state their own spec; nothing else guesses."""

import pytest

from hendley.requirements.specs import (
    base_value,
    canonical_value,
    infer_spec,
    kind_for_designator,
    package_from_footprint,
)


def test_kind_from_designator_prefix():
    assert kind_for_designator("R10") == "resistor"
    assert kind_for_designator("C3") == "capacitor"
    assert kind_for_designator("L2") == "inductor"
    # not auto-spec kinds: never guess
    for d in ("D1", "U1", "J7", "Q3", "TP1", "LED1", "RV1", "SW2"):
        assert kind_for_designator(d) is None


def test_package_from_footprint_names():
    assert package_from_footprint("R-0402") == "0402"
    assert package_from_footprint("C-0603") == "0603"
    assert package_from_footprint("0805") == "0805"
    # no recognizable chip package → no inference
    assert package_from_footprint("L-SMD-7.3X6.6") is None
    assert package_from_footprint("SOT95P280X145-6N") is None
    assert package_from_footprint(None) is None


def test_value_parsing_and_canonicalization():
    assert base_value("resistor", "82K") == 82000
    assert base_value("resistor", "4k7") == 4700
    assert base_value("resistor", "220") == 220
    assert base_value("capacitor", ".1u") == pytest.approx(1e-7)
    assert base_value("capacitor", "100n") == pytest.approx(1e-7)
    assert canonical_value("resistor", "82K") == "82k"
    assert canonical_value("resistor", "4k7") == "4.7k"
    assert canonical_value("resistor", "309K") == "309k"
    assert canonical_value("resistor", "1M") == "1M"
    assert canonical_value("capacitor", ".1u") == "100n"  # same spec key as 100n
    assert canonical_value("capacitor", "22u") == "22u"
    assert canonical_value("inductor", "22uH") == "22u"
    # unparseable → None, never a guess
    assert canonical_value("resistor", "FET-NCH") is None
    assert canonical_value("resistor", "") is None


def test_infer_spec_needs_all_three_legs():
    spec = infer_spec("R10", "82K", "R-0402")
    assert (spec.kind, spec.value, spec.package) == ("resistor", "82k", "0402")
    # equivalent spellings land on the SAME spec key
    assert infer_spec("C9", ".1u", "C-0603") == infer_spec("C4", "100n", "0603")
    assert infer_spec("U5", "82K", "R-0402") is None  # not an auto-spec kind
    assert infer_spec("R10", "82K", "WEIRD-FP") is None  # no chip package
    assert infer_spec("R10", "mystery", "R-0402") is None  # unparseable value
