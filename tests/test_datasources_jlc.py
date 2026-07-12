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
