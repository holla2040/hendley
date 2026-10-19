"""DigiKey and Mouser sources (ADR-0010): exact-MPN matching, and the
parsing of each API's quirks — offline, over canned responses shaped like
the published OpenAPI/Swagger contracts."""

from hendley.datasources import digikey, mouser
from hendley.datasources.digikey import DigiKeyDataSource
from hendley.datasources.mouser import MouserDataSource


class _Resp:
    def __init__(self, doc):
        self.doc = doc

    def raise_for_status(self):
        pass

    def json(self):
        return self.doc


def _dk_product(mpn, qty=500, status="Active"):
    return {
        "ManufacturerProductNumber": mpn,
        "Manufacturer": {"Name": "Diodes Incorporated"},
        "Description": {"ProductDescription": "IC REG LINEAR 3.3V 600MA SOT23-5"},
        "ProductStatus": {"Status": status},
        "QuantityAvailable": qty,
        "ManufacturerLeadWeeks": "24",
        "DatasheetUrl": "https://example.com/ds.pdf",
        "ProductUrl": "https://example.com/p",
        "ProductVariations": [
            {"DigiKeyProductNumber": "X-TR-ND", "MinimumOrderQuantity": 3000,
             "StandardPricing": [{"BreakQuantity": 3000, "UnitPrice": 0.08}]},
            {"DigiKeyProductNumber": "X-CT-ND", "MinimumOrderQuantity": 1,
             "StandardPricing": [{"BreakQuantity": 1, "UnitPrice": 0.28},
                                 {"BreakQuantity": 10, "UnitPrice": 0.19}]},
        ],
    }


def _dk(products):
    def post(url, **kw):
        if url == digikey.TOKEN_URL:
            return _Resp({"access_token": "t", "expires_in": 600})
        return _Resp({"Products": products(kw["json"]["Keywords"]), "ExactMatches": []})
    return DigiKeyDataSource("id", "secret", post=post)


def test_digikey_keeps_only_the_exact_mpn():
    ds = _dk(lambda kw: [_dk_product(kw + "-7"), _dk_product(kw.lower())])
    fact = ds.verify(["AP2112K-3.3TRG1"])["AP2112K-3.3TRG1"]
    assert fact.found and fact.mpn == "ap2112k-3.3trg1"       # case-insensitive
    assert fact.lifecycle == "Active" and fact.stock == 500


def test_digikey_a_near_miss_is_not_found():
    ds = _dk(lambda kw: [_dk_product(kw + "-7")])
    assert not ds.verify(["AP2112K-3.3TRG1"])["AP2112K-3.3TRG1"].found


def test_digikey_prices_the_small_order_variation():
    fact = _dk(lambda kw: [_dk_product(kw)]).verify(["X"])["X"]
    assert fact.price_tiers[0] == {"qty": 1, "price": 0.28, "currency": "USD"}
    assert digikey.offer(fact) == {
        "leadTime": "24 weeks", "datasheetUrl": "https://example.com/ds.pdf",
        "productUrl": "https://example.com/p", "distributorPart": "X-CT-ND"}


def _mouser(parts, calls=None):
    def post(url, **kw):
        if calls is not None:
            calls.append(kw["json"]["SearchByPartRequest"]["mouserPartNumber"])
        return _Resp({"Errors": [], "SearchResults": {"Parts": parts}})
    return MouserDataSource("key", post=post)


def _m_part(mpn, stock, mouser_pn="621-X"):
    return {"ManufacturerPartNumber": mpn, "Manufacturer": "Diodes Incorporated",
            "MouserPartNumber": mouser_pn, "AvailabilityInStock": stock,
            "Availability": f"{stock} In Stock", "LifecycleStatus": "New Product",
            "PriceBreaks": [{"Quantity": 1, "Price": "$0.28", "Currency": "USD"}],
            "LeadTime": "84 Days", "DataSheetUrl": "", "ProductDetailUrl": "https://m/x"}


def test_mouser_picks_the_stocked_listing_of_an_mpn():
    ds = _mouser([_m_part("X", "0", "621-X-RL"), _m_part("X", "1200", "621-X-CT")])
    fact = ds.verify(["X"])["X"]
    assert fact.stock == 1200 and mouser.offer(fact)["distributorPart"] == "621-X-CT"
    assert fact.price_tiers == [{"qty": 1, "price": 0.28, "currency": "USD"}]
    assert mouser.offer(fact)["datasheetUrl"] is None              # "" is absence


def test_mouser_batches_ten_per_call():
    calls = []
    _mouser([], calls).verify([f"P{i}" for i in range(23)])
    assert [c.count("|") + 1 for c in calls] == [10, 10, 3]


def test_mouser_parsers_refuse_to_guess():
    assert mouser._stock({"AvailabilityInStock": "1,234"}) == 1234
    assert mouser._stock({"Availability": "On Order"}) is None
    assert mouser._money("$1,234.50") == 1234.5
    assert mouser._money("Quote") is None


def test_mouser_http_error_never_carries_the_key():
    import pytest
    import requests

    class _Bad:
        status_code = 403

        def raise_for_status(self):
            raise requests.HTTPError("403 for url: ...?apiKey=SECRET")

    ds = MouserDataSource("SECRET", post=lambda url, **kw: _Bad())
    with pytest.raises(RuntimeError) as exc:
        ds.verify(["X"])
    assert "SECRET" not in str(exc.value)
