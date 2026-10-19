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
               mcpserver.us_availability, mcpserver.approved_parts,
               mcpserver.approve_part):
        params = inspect.signature(mcpserver._public(fn)).parameters
        assert not {"datasource", "sources", "store", "app"} & set(params)


# -- approve_part: the one write (Craig, 2026-10-19) --------------------------

class _Design:
    """A placed R1 (22k, R-0603, LCSC attribute C31850) and a DNP TP1."""

    def read_all(self, entity_type, obj=None, page=1000):
        if entity_type == "electronics.Schematic":
            return [{"name": r"C:\T\demo sch.sch"}]
        if entity_type == "electronics.Part":
            return [{"object_id": 10, "name": "R1", "value": "22k", "device_object_id": 100},
                    {"object_id": 11, "name": "TP1", "value": "", "device_object_id": 101}]
        if entity_type == "electronics.Device":
            return [{"object_id": 100, "package_object_id": 412},
                    {"object_id": 101, "package_object_id": 415}]
        if entity_type == "electronics.Package":
            return [{"object_id": 412, "name": "R-0603"}, {"object_id": 415, "name": "TP-1MM"}]
        if entity_type == "electronics.Attribute":
            [flt] = obj["filters"]
            return ([{"name": "LCSC", "value": "C31850"}] if flt["value"] == 10
                    else [{"name": "DNP", "value": "1"}])
        raise AssertionError(entity_type)

    def read(self, entity_type, obj=None):
        return {"items": self.read_all(entity_type, obj)}

    def run_eagle(self, command):
        raise AssertionError("approve_part must not drive Fusion")


class _Catalog:
    name = "jlc-api"

    def __init__(self):
        self.PACKAGES = {"C31850": "0603", "C25804": "0603", "C25744": "0402"}

    def verify(self, refs):
        return {r: PartFact(ref=r, found=r in self.PACKAGES, stock=1000, mpn=f"MPN-{r}",
                            raw={"componentSpecification": self.PACKAGES.get(r)})
                for r in refs}


class _Namer:
    calls = 0

    def derive_key(self, ctx):
        _Namer.calls += 1
        return {"spec": {"kind": "R", "value": "22k", "package": "0603"},
                "rationale": "22k chip resistor", "confidence": 0.95}


def _app(tmp_path):
    from hendley.app.server import HendleyApp
    return HendleyApp(db_path=tmp_path / "parts.db", bridge_factory=lambda host: _Design(),
                      datasource_factory=_Catalog, interpreter_factory=_Namer,
                      draft_path=tmp_path / "draft.json", cache_path=tmp_path / "cache.json")


def test_approve_part_records_a_list_the_next_refresh_resolves(tmp_path):
    from hendley.ingestion.fusion.live_design import extract_schematic
    from hendley.requirements import requirements_from_design

    app, _Namer.calls = _app(tmp_path), 0
    out = mcpserver.approve_part("R1", "C31850", ["C25804"], app=app, datasource=_Catalog())

    assert (out["spec"]["kind"], out["spec"]["value"], out["spec"]["package"]) == \
        ("R", "22k", "0603")
    assert out["recorded"] == ["C31850", "C25804"]
    assert [(c["code"], c["rank"]) for c in out["approvedList"]] == [("C31850", 1), ("C25804", 2)]
    assert out["resolvesOnRefresh"] is True and out["notes"] == []

    # The next Refresh names R1 from the recorded key, so it resolves against the list.
    design, parts = extract_schematic(_Design())
    req = requirements_from_design(design, parts, 1)
    app._interpret_lines(req, consult_interpreter=False, visual_available=True)
    r1 = next(ln for ln in req.lines if "R1" in ln.designators)
    assert r1.spec and r1.spec.package == "0603"

    # Approving again names nothing new and duplicates nothing.
    again = mcpserver.approve_part("R1", "C25804", app=app, datasource=_Catalog())
    assert again["recorded"] == [] and again["alreadyApproved"] == ["C25804"]
    assert _Namer.calls == 1


def test_approve_part_refuses_another_land_and_writes_nothing(tmp_path):
    app, _Namer.calls = _app(tmp_path), 0
    out = mcpserver.approve_part("R1", "C31850", ["C25744"], app=app, datasource=_Catalog())
    assert "C25744 is 0402" in out["error"]
    assert mcpserver.approved_parts(store=app._store())["houseParts"] == []
    assert _Namer.calls == 0   # refused before the requirement was named


def test_approve_part_needs_a_placed_part_and_a_real_code(tmp_path):
    app = _app(tmp_path)
    assert "place it first" in mcpserver.approve_part("U9", "C31850", app=app,
                                                      datasource=_Catalog())["error"]
    assert "DNP" in mcpserver.approve_part("TP1", "C31850", app=app,
                                           datasource=_Catalog())["error"]
    assert "not found" in mcpserver.approve_part("R1", "C0", app=app,
                                                 datasource=_Catalog())["error"]


def test_approve_part_answers_errors_instead_of_raising(tmp_path):
    from hendley.app.server import HendleyApp

    def down(host):
        raise OSError("connection refused")

    app = HendleyApp(db_path=tmp_path / "parts.db", bridge_factory=down)
    assert "connection refused" in mcpserver.approve_part("R1", "C31850", app=app)["error"]


def test_approve_part_promotes_a_cached_guess_to_the_engineers_key(tmp_path):
    """A model-sourced key would not be honoured on a pinned line at Refresh."""
    from hendley.app.server import _part_cache_value

    app = _app(tmp_path)
    app._store().put_interpretation(
        "part", {"spec": {"kind": "R", "value": "22k", "package": "0603"}}, "llm",
        kind_hint="R", raw_value=_part_cache_value("22k", {}), footprint="R-0603")
    out = mcpserver.approve_part("R1", "C31850", app=app, datasource=_Catalog())
    assert out["resolvesOnRefresh"] is True
