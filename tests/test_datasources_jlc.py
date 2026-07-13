"""JLCDataSource — manufacturer (brand slug) extraction from dataManualUrl.

The official API has no manufacturer field; the datasheet filename embeds the
LCSC brand slug (``<digits>_<brand>-<MPN>_<Ccode>.pdf``). The parse is
anchored on the known MPN and code and refuses anything that doesn't match —
a manufacturer is never fabricated.
"""

from hendley.datasources.jlc.source import JLCDataSource, _brand_from_manual_url


def _detail(**kw):
    d = {"componentCode": "C19077482", "componentModel": "1SMA4744A",
         "dataManualUrl": ("https://cdn.example.com/"
                           "2402281642_hongjiacheng-1SMA4744A_C19077482.pdf"),
         "stockCount": 5, "priceRanges": []}
    d.update(kw)
    return d


def test_brand_slug_documented_example():
    assert _brand_from_manual_url(_detail()) == "hongjiacheng"


def test_brand_slug_survives_hyphenated_mpn():
    d = _detail(componentCode="C137378", componentModel="RC0402FR-0722KL",
                dataManualUrl=("https://cdn.example.com/"
                               "2301010101_yageo-RC0402FR-0722KL_C137378.pdf"))
    assert _brand_from_manual_url(d) == "yageo"


def test_brand_slug_refuses_mismatches():
    assert _brand_from_manual_url(_detail(dataManualUrl="")) is None
    assert _brand_from_manual_url(
        _detail(dataManualUrl="https://cdn.example.com/whatever.pdf")) is None
    assert _brand_from_manual_url(_detail(componentCode="C1")) is None  # suffix
    assert _brand_from_manual_url(_detail(componentModel="XYZ")) is None  # mpn
    assert _brand_from_manual_url(_detail(dataManualUrl=(
        "https://cdn.example.com/"
        "notadate_hongjiacheng-1SMA4744A_C19077482.pdf"))) is None  # prefix


class _FakeClient:
    def get_component_detail_by_code(self, codes):
        return [_detail()]


def test_verify_fills_manufacturer_from_the_slug():
    facts = JLCDataSource(client=_FakeClient()).verify(["C19077482"])
    fact = facts["C19077482"]
    assert fact.found and fact.manufacturer == "hongjiacheng"


def test_a_column_that_cannot_prove_anything_is_never_offered():
    """The index's flags LIE, and the agent trusts the menu it is handed.

    `is_polarized` is false on every aluminium electrolytic; `is_schottky`,
    `is_zener` and `is_tvs` are false on every schottky, zener and TVS. A plan
    that sieves on one returns ZERO parts while looking like it filtered — that
    is not hypothetical, it is what rejected all 36 candidates for a 10uF 50V
    can with a wall of "False is not true". Measured, and held here.
    """
    from hendley.datasources.jlc.alternates import (
        CATEGORY_COLUMNS,
        UNPROVABLE_COLUMNS,
    )

    for category, dead in UNPROVABLE_COLUMNS.items():
        offered = set(CATEGORY_COLUMNS.get(category, ()))
        leaked = offered & set(dead)
        assert not leaked, (
            f"{category}: {sorted(leaked)} cannot prove anything and must not "
            "be offered to the agent or the engineer")

    # the specific ones that cost us a search
    assert "is_polarized" not in CATEGORY_COLUMNS["capacitors"]
    assert "is_schottky" not in CATEGORY_COLUMNS["diodes"]
    # a category stripped to `package` alone is an HONEST answer, not a gap: the
    # index cannot filter it, so the catalog's parameters must do the proving
    assert CATEGORY_COLUMNS["fpgas"] == ("package",)
