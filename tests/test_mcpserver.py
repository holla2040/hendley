"""The MCP tool functions (ADR-0010) over fake sources — they add shaping and
isolation, never search logic of their own."""

from hendley import mcpserver
from hendley.datasources.base import PartFact


class _JLC:
    name = "jlc-api"

    def discover(self, query):
        return [{"code": "C1", "package": "SOT-23"}, {"code": "C2", "package": "SOT-23"}]

    def verify(self, refs):
        def fact(code, volts):
            return PartFact(ref=code, found=True, stock=1000, mpn=f"LDO-{code}",
                            offer_class="base", raw={
                                "componentModel": f"LDO-{code}",
                                "componentSpecification": "SOT-23",
                                "libraryType": "base", "stockCount": 1000,
                                "dataManualUrl": "https://example.com/ds.pdf",
                                "parameters": [{"parameterName": "Output Voltage",
                                                "parameterValue": volts}]})
        return {r: fact(r, {"C1": "3.3V", "C2": "1.8V"}[r]) for r in refs}


def test_search_parts_proves_and_shapes():
    out = mcpserver.search_parts(
        {"mode": "category", "category": "ldos", "net": {"package": "SOT-23"},
         "sieve": [{"field": "Output Voltage", "op": "eq", "value": 3.3, "unit": "V"}]},
        datasource=_JLC())
    assert [c["code"] for c in out["candidates"]] == ["C1"]
    assert out["candidates"][0]["library"] == "Basic"
    assert out["candidates"][0]["proved"]["Output Voltage"] == "3.3V"
    assert out["misses"][0]["code"] == "C2" and out["misses"][0]["failed"]


def test_part_detail_flattens_parameters():
    out = mcpserver.part_detail(["C1"], datasource=_JLC())
    assert out["C1"]["parameters"] == {"Output Voltage": "3.3V"}
    assert out["C1"]["datasheetUrl"] == "https://example.com/ds.pdf"


class _Source:
    def __init__(self, name, configured=True, boom=False):
        self.name, self.configured, self.boom = name, configured, boom

    def verify(self, mpns):
        if self.boom:
            raise RuntimeError("down")
        return {m: PartFact(ref=m, found=m == "GOOD", stock=5, lifecycle="Active")
                for m in mpns}


def test_us_availability_isolates_each_source():
    out = mcpserver.us_availability(["GOOD", "NOPE"], sources=[
        (_Source("digikey"), lambda f: {"productUrl": "u"}),
        (_Source("mouser", configured=False), None),
        (_Source("arrow", boom=True), None)])
    assert out["GOOD"]["digikey"] == {"found": True, "manufacturer": None, "stock": 5,
                                      "lifecycle": "Active", "priceBreaks": [],
                                      "productUrl": "u"}
    assert out["NOPE"]["digikey"] == {"found": False}
    assert out["GOOD"]["mouser"] == {"error": "not configured"}
    assert out["GOOD"]["arrow"] == {"error": "down"}


def test_tool_signatures_hide_the_test_seams():
    import inspect
    for fn in (mcpserver.search_parts, mcpserver.part_detail,
               mcpserver.us_availability, mcpserver.approved_parts):
        params = inspect.signature(mcpserver._public(fn)).parameters
        assert not {"datasource", "sources", "store"} & set(params)
