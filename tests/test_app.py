"""Endpoint tests for the Hendley app — the JSON API over the library.

A real ThreadingHTTPServer on an ephemeral port, a temp knowledge DB, a fake
DataSource, and a fake Fusion bridge: the full intake → resolve → approve →
re-resolve → emit flow, driven exactly the way the page drives it.
"""

import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from hendley.app.server import HendleyApp, make_handler
from hendley.datasources.base import PartFact


class FakeSource:
    name = "fake"

    def __init__(self, stocks: dict[str, int], discovered: list[dict] | None = None):
        self.stocks = stocks
        self.discovered = discovered or []

    def verify(self, refs):
        out = {}
        for r in sorted(set(refs)):
            if r in self.stocks:
                out[r] = PartFact(
                    ref=r, found=True, stock=self.stocks[r], mpn=f"MPN-{r}",
                    manufacturer=f"MFR-{r}",
                    price_tiers=[{"startQuantity": 1, "unitPrice": 0.002}],
                    raw={"componentCode": r, "stockCount": self.stocks[r],
                         "componentModel": f"MPN-{r}",
                         "componentSpecification": "0603",
                         "libraryType": "Basic",
                         "priceRanges": [{"startQuantity": 1, "unitPrice": 0.002}]},
                    provenance=self.name)
            else:
                out[r] = PartFact(ref=r, found=False, provenance=self.name)
        return out

    def discover(self, query):
        return list(self.discovered)


class FakeBridge:
    """Two-part design: one LCSC-coded resistor, one DNP test point."""

    def read_all(self, entity_type, obj=None, page=1000):
        if entity_type == "electronics.Schematic":
            return [{"object_id": 1, "name": r"C:\T\demo sch.sch"}]
        if entity_type == "electronics.Part":
            return [{"object_id": 10, "name": "R1", "value": "22k",
                     "device_object_id": 100},
                    {"object_id": 11, "name": "TP1", "value": "",
                     "device_object_id": 101}]
        if entity_type == "electronics.Device":
            return [{"object_id": 100, "package_object_id": 412},
                    {"object_id": 101, "package_object_id": 415}]
        if entity_type == "electronics.Attribute":
            [flt] = obj["filters"]
            return ([{"name": "LCSC", "value": "C31850"}] if flt["value"] == 10
                    else [{"name": "DNP", "value": "1"}])
        if entity_type == "electronics.Element":
            return [{"object_id": 30, "name": "R1", "x": 1.0, "y": 2.0, "angle": 0,
                     "mirror": 0, "populate": 1, "package_object_id": 50},
                    {"object_id": 31, "name": "TP1", "x": 5.0, "y": 5.0, "angle": 0,
                     "mirror": 0, "populate": 1, "package_object_id": 51}]
        if entity_type == "electronics.Package":
            return [{"object_id": 50, "name": "R-0603"},
                    {"object_id": 51, "name": "TP-1MM"}]
        raise AssertionError(entity_type)

    def read(self, entity_type, obj=None):
        return {"items": self.read_all(entity_type, obj)}

    def run_eagle(self, command):
        return {}


def _no_interpreter():
    raise AssertionError("interpreter must not be consulted in this test")


@pytest.fixture
def client(tmp_path):
    source = FakeSource(
        stocks={"C31850": 40, "C_NEW": 90_000},
        discovered=[{"code": "C_NEW", "mfr": "0603WAF2202T5E", "package": "0603",
                     "jlcsearch_stock": 5, "price1": 0.001}])
    app = HendleyApp(db_path=tmp_path / "parts.db", outdir=tmp_path / "out",
                     datasource_factory=lambda: source,
                     bridge_factory=lambda host: FakeBridge(),
                     interpreter_factory=_no_interpreter,
                     draft_path=tmp_path / "draft.json",
                     cache_path=tmp_path / "design-cache.json")
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"

    def call(path, body=None, expect=200):
        req = urllib.request.Request(
            base + path,
            data=None if body is None else json.dumps(body).encode(),
            headers={"Content-Type": "application/json"} if body is not None else {},
        )
        try:
            with urllib.request.urlopen(req) as res:
                assert res.status == expect
                raw = res.read()
        except urllib.error.HTTPError as err:
            assert err.code == expect, f"{err.code}: {err.read()!r}"
            raw = err.read()
        return json.loads(raw) if raw else None

    yield call
    server.shutdown()
    server.server_close()


def test_root_serves_html(tmp_path):
    app = HendleyApp(db_path=tmp_path / "parts.db", outdir=tmp_path / "out",
                     draft_path=tmp_path / "draft.json",
                     cache_path=tmp_path / "design-cache.json")
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with urllib.request.urlopen(
                f"http://127.0.0.1:{server.server_port}/") as res:
            body = res.read().decode()
        assert res.status == 200 and "<title>Hendley</title>" in body
    finally:
        server.shutdown()
        server.server_close()


def test_avl_manager_flow(client):
    # record → list → rerank → history → remove (7a)
    spec = {"kind": "resistor", "value": "22k", "package": "0603"}
    got = client("/api/record", {**spec, "lcsc": "C31850", "mpn": "0603WAF2202T5E",
                                 "note": "first pick"})
    assert got["choice"]["rank"] == 1
    client("/api/record", {**spec, "lcsc": "C4190"})

    parts = client("/api/parts?kind=resistor")["parts"]
    assert [c["lcscCode"] for c in parts[0]["choices"]] == ["C4190", "C31850"]

    client("/api/rerank", {"spec": spec, "ref": "C31850", "rank": 1})
    one = client("/api/part?kind=resistor&value=22k&package=0603")
    assert [c["lcscCode"] for c in one["housePart"]["choices"]] == ["C31850", "C4190"]
    assert one["history"][0]["event"] == "reranked"

    client("/api/remove", {"spec": spec, "ref": "C4190", "note": "EOL"})
    one = client("/api/part?kind=resistor&value=22k&package=0603")
    assert [c["lcscCode"] for c in one["housePart"]["choices"]] == ["C31850"]

    # kind and package are the identity; an empty VALUE is legal (a
    # general-purpose diode has none) and must not be demanded
    bad = client("/api/record", {"kind": "resistor", "value": "22k",
                                 "package": "", "lcsc": "C1"}, expect=400)
    assert "package" in bad["error"]
    client("/api/record", {"kind": "diode", "value": "", "package": "SOD-323",
                           "lcsc": "C2128", "mpn": "1N4148WS"})
    unnamed = client("/api/part?kind=diode&value=&package=SOD-323")
    assert unnamed["housePart"]["choices"][0]["lcscCode"] == "C2128"


def test_full_resolution_flow_intake_to_emit(client, tmp_path):
    # 7b: intake from (fake) Fusion
    intake = client("/api/intake", {"productionQuantity": 100})
    req = intake["requirements"]
    assert req["design"] == "demo" and len(req["lines"]) == 2
    dnp_line = [ln for ln in req["lines"] if ln.get("dnp")]
    assert dnp_line and dnp_line[0]["designators"] == ["TP1"]

    # R1's code short on stock (40 < 100) → escalate; the line is explicit-ref,
    # so re-spec it as a requirements line to exercise the AVL + queue path.
    spec = {"kind": "resistor", "value": "22k", "package": "0603", "qualifier": ""}
    client("/api/record", {"spec": spec, "lcsc": "C31850"})
    req["lines"][0] = {"designators": ["R1"], "comment": "22k",
                       "footprint": "R-0603", "spec": spec}

    resolved = client("/api/resolve", {"requirements": req,
                                       "placements": intake["placements"]})
    assert resolved["resolution"]["escalations"]
    queue = resolved["queue"]
    [entry] = queue["entries"]
    assert entry["reason"] == "avl-exhausted"
    assert [c["code"] for c in entry["candidates"]] == ["C_NEW"]
    assert entry["candidates"][0]["manufacturer"] == "MFR-C_NEW"

    # approve the ranked candidate → re-resolve clean
    client("/api/approve", {"approvals": [{
        "spec": entry["spec"], "lcsc": "C_NEW", "mpn": "MPN-C_NEW",
        "design": "demo", "note": "queue pick"}]})
    resolved = client("/api/resolve", {"requirements": req,
                                       "placements": intake["placements"]})
    assert resolved["resolution"]["escalations"] == []
    assert resolved["resolution"]["lines"][0]["ref"] == "C_NEW"

    # 7c: emit — files + gate + snapshot
    emitted = client("/api/emit", {"resolution": resolved["resolution"]})
    assert emitted["readyToUpload"] and emitted["blockers"] == []
    assert [p.split("/")[-1] for p in emitted["files"]] == ["bom.csv", "cpl.csv"]
    bom = (tmp_path / "out" / "bom.csv").read_text()
    assert "22k,R1,R-0603,C_NEW" in bom and "TP1" not in bom
    assert emitted["snapshot"] and emitted["snapshot"].endswith(".snapshot.json")

    snaps = client("/api/snapshots")["snapshots"]
    assert len(snaps) == 1
    doc = client(f"/api/snapshot?name={snaps[0]['name']}")
    assert doc["resolution"]["lines"][0]["ref"] == "C_NEW"


def test_emit_blocked_resolution_reports_blockers(client, tmp_path):
    emitted = client("/api/emit", {"resolution": {
        "design": "demo", "productionQuantity": 1,
        "lines": [{"designators": ["R9"], "comment": "47k"}]}})
    assert not emitted["readyToUpload"]
    assert [b["check"] for b in emitted["blockers"]] == ["unresolved"]
    assert emitted["snapshot"] is None
    assert client("/api/snapshots")["snapshots"] == []


def test_snapshot_name_is_sanitized(client):
    err = client("/api/snapshot?name=../../.keys", expect=400)
    assert "bad snapshot name" in err["error"]
    missing = client("/api/snapshot?name=nope.snapshot.json", expect=404)
    assert "no such" in missing["error"]


def test_unknown_routes_and_bad_json(client):
    assert client("/api/nope", expect=404)["error"] == "not found"
    resolved = client("/api/resolve", {"requirements": {"productionQuantity": 0,
                                                        "lines": []}}, expect=400)
    assert "requirements" in resolved["error"]


# ---------------------------------------------------------------------------
# interpretation: cache → LLM → confirm card (the C7 story)
# ---------------------------------------------------------------------------

class MysteryBridge(FakeBridge):
    """FakeBridge plus C7: '47u/50V' on the C-E-5 electrolytic footprint."""

    def read_all(self, entity_type, obj=None, page=1000):
        if entity_type == "electronics.Part":
            return super().read_all(entity_type, obj) + [
                {"object_id": 12, "name": "C7", "value": "47u/50V",
                 "device_object_id": 102}]
        if entity_type == "electronics.Device":
            return super().read_all(entity_type, obj) + [
                {"object_id": 102, "package_object_id": 470}]
        if entity_type == "electronics.Attribute":
            [flt] = obj["filters"]
            if flt["value"] == 12:
                return []
        if entity_type == "electronics.Element":
            return super().read_all(entity_type, obj) + [
                {"object_id": 32, "name": "C7", "x": 9.0, "y": 9.0, "angle": 0,
                 "mirror": 0, "populate": 1, "package_object_id": 52}]
        if entity_type == "electronics.Package":
            return super().read_all(entity_type, obj) + [
                {"object_id": 52, "name": "C-E-5"}]
        return super().read_all(entity_type, obj)


class CountingInterpreter:
    name = "fake-llm"

    def __init__(self, confidence=0.9):
        self.calls = 0
        self.keys = 0
        self.confidence = confidence

    def interpret_part(self, ctx):
        from hendley.ai.interpreter import Interpretation
        from hendley.domain.model import SpecKey

        self.calls += 1
        assert ctx["value"] == "47u/50V" and ctx["footprint"] == "C-E-5"
        return Interpretation(
            spec=SpecKey("capacitor", "47u", "C-E-5", "50V"),
            envelope={"mount": "tht", "maxDiaMm": 10, "leadSpacingMm": 5},
            confidence=self.confidence,
            rationale="electrolytic, 5mm lead spacing")

    def derive_key(self, ctx):
        self.keys += 1
        return {"spec": {"kind": "capacitor", "value": "47u",
                         "package": "C-E-5", "qualifier": "50V"},
                "rationale": "47u/50V on a 5mm electrolytic footprint",
                "confidence": 0.9}


def _mystery_app(tmp_path, interp):
    app = HendleyApp(db_path=tmp_path / "parts.db", outdir=tmp_path / "out",
                     datasource_factory=lambda: FakeSource({}),
                     bridge_factory=lambda host: MysteryBridge(),
                     interpreter_factory=lambda: interp,
                     draft_path=tmp_path / "draft.json",
                     cache_path=tmp_path / "design-cache.json")
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"

    def call(path, body=None, expect=200):
        req = urllib.request.Request(
            base + path,
            data=None if body is None else json.dumps(body).encode(),
            headers={"Content-Type": "application/json"} if body is not None else {})
        try:
            with urllib.request.urlopen(req) as res:
                assert res.status == expect
                return json.loads(res.read())
        except urllib.error.HTTPError as err:
            assert err.code == expect
            return json.loads(err.read())
    return call, server


def test_llm_interprets_and_caches_once(tmp_path):
    interp = CountingInterpreter(confidence=0.9)
    call, server = _mystery_app(tmp_path, interp)
    try:
        data = call("/api/intake", {"productionQuantity": 5})
        assert data["uninterpreted"] == []
        c7 = next(ln for ln in data["requirements"]["lines"]
                  if "C7" in ln["designators"])
        assert c7["spec"] == {"kind": "capacitor", "value": "47u",
                              "package": "C-E-5", "qualifier": "50V"}
        assert interp.calls == 1
        # second intake: cache hit, the LLM is never asked again
        call("/api/intake", {"productionQuantity": 5})
        assert interp.calls == 1
    finally:
        server.shutdown()
        server.server_close()


class TwoMysteryBridge(MysteryBridge):
    """C7 (47u/50V on C-E-5) plus D6: a diode with NO value, on D-SOD323."""

    def read_all(self, entity_type, obj=None, page=1000):
        if entity_type == "electronics.Attribute":
            [flt] = obj["filters"]
            if flt["value"] in (12, 13):
                return []
        if entity_type == "electronics.Part":
            return super().read_all(entity_type, obj) + [
                {"object_id": 13, "name": "D6", "value": "",
                 "device_object_id": 103}]
        if entity_type == "electronics.Device":
            return super().read_all(entity_type, obj) + [
                {"object_id": 103, "package_object_id": 471}]
        if entity_type == "electronics.Element":
            return super().read_all(entity_type, obj) + [
                {"object_id": 33, "name": "D6", "x": 3.0, "y": 3.0, "angle": 0,
                 "mirror": 0, "populate": 1, "package_object_id": 53}]
        if entity_type == "electronics.Package":
            return super().read_all(entity_type, obj) + [
                {"object_id": 53, "name": "D-SOD323"}]
        return super().read_all(entity_type, obj)


class PartialThenComplete:
    """Answers C7 with an INCOMPLETE reading, D6 with a complete spec."""

    name = "fake-llm"

    def __init__(self):
        self.seen = []

    def interpret_part(self, ctx):
        from hendley.ai.interpreter import Interpretation
        from hendley.domain.model import SpecKey

        self.seen.append(ctx["designator"])
        if ctx["footprint"] == "C-E-5":   # value unreadable: ask the engineer
            return Interpretation(
                partial={"kind": "capacitor", "package": "C-E-5"},
                envelope={"mount": "tht"}, confidence=0.9,
                rationale="can't read the value")
        return Interpretation(
            spec=SpecKey("diode", "1n4148", "SOD-323", ""),
            confidence=0.9, rationale="clear")


def test_an_incomplete_reading_does_not_kill_the_interpreter(tmp_path):
    # regression: an answer that isn't a complete spec used to look like a
    # dead interpreter, so every later part in the design went unjudged
    interp = PartialThenComplete()
    app = HendleyApp(db_path=tmp_path / "parts.db", outdir=tmp_path / "out",
                     datasource_factory=lambda: FakeSource({}),
                     bridge_factory=lambda host: TwoMysteryBridge(),
                     interpreter_factory=lambda: interp,
                     draft_path=tmp_path / "draft.json",
                     cache_path=tmp_path / "cache.json")
    data = app.api_intake({"productionQuantity": 5})
    assert interp.seen == ["C7", "D6"]   # D6 still got asked
    d6 = next(ln for ln in data["requirements"]["lines"]
              if "D6" in ln["designators"])
    assert d6["spec"]["package"] == "SOD-323"
    # C7's partial reading rides onto the card as prefill
    [card] = data["uninterpreted"]
    assert card["designators"] == ["C7"]
    assert card["guess"]["spec"] is None
    assert card["guess"]["partial"] == {"kind": "capacitor", "package": "C-E-5"}
    # the package was already read — no second judgment call is spent
    assert "judgedPackage" not in card


class JudgingInterpreter:
    """Recognizes nothing as a part, but judges footprints (counted)."""

    name = "fake-judge"

    def __init__(self, package="SMD-5x5"):
        self.footprint_calls = 0
        self.package = package

    def interpret_part(self, ctx):
        from hendley.ai.interpreter import Interpretation

        return Interpretation()   # honest shrug: no spec, confidence 0

    def interpret_footprint(self, footprint):
        self.footprint_calls += 1
        assert footprint == "C-E-5"
        return {"package": self.package, "envelope": {"mount": "smd"},
                "confidence": 0.9, "rationale": "catalog form of the name"}


def test_confirm_card_carries_the_judged_catalog_package(tmp_path):
    # the card must never seed the raw library footprint as the package —
    # the agent-judged catalog form rides along for the prefill
    interp = JudgingInterpreter(package="SMD-5x5")
    call, server = _mystery_app(tmp_path, interp)
    try:
        data = call("/api/intake", {"productionQuantity": 5})
        [card] = data["uninterpreted"]
        assert card["judgedPackage"] == "SMD-5x5"
        assert card["judgedEnvelope"] == {"mount": "smd"}
        assert interp.footprint_calls == 1
        # judged once, ever — the cache answers on the next intake
        data = call("/api/intake", {"productionQuantity": 5})
        [card] = data["uninterpreted"]
        assert card["judgedPackage"] == "SMD-5x5"
        assert interp.footprint_calls == 1
    finally:
        server.shutdown()
        server.server_close()


def test_guess_with_a_package_skips_the_footprint_judgment(tmp_path):
    class GuessWithPackage(CountingInterpreter):
        def interpret_footprint(self, footprint):
            raise AssertionError("footprint judgment must not run")

    interp = GuessWithPackage(confidence=0.4)  # guess already has a package
    call, server = _mystery_app(tmp_path, interp)
    try:
        data = call("/api/intake", {"productionQuantity": 5})
        [card] = data["uninterpreted"]
        assert "judgedPackage" not in card
    finally:
        server.shutdown()
        server.server_close()


def test_judged_nothing_standard_gives_no_prefill(tmp_path):
    # '' is the valid "nothing standard recognizable" answer — the card
    # falls back to the raw footprint, per the verbatim convention
    interp = JudgingInterpreter(package="")
    call, server = _mystery_app(tmp_path, interp)
    try:
        data = call("/api/intake", {"productionQuantity": 5})
        [card] = data["uninterpreted"]
        assert "judgedPackage" not in card
        assert interp.footprint_calls == 1
    finally:
        server.shutdown()
        server.server_close()


def test_low_confidence_leaves_the_line_unread_for_the_search_box(tmp_path):
    # nothing is invented and nothing is demanded: the line simply has no key
    # yet, and the search box (seeded from what WAS read) is how it gets one
    interp = CountingInterpreter(confidence=0.4)  # honest doubt
    call, server = _mystery_app(tmp_path, interp)
    try:
        data = call("/api/intake", {"productionQuantity": 5})
        [card] = data["uninterpreted"]
        assert card["designators"] == ["C7"] and card["value"] == "47u/50V"
        assert card["guess"]["spec"]["kind"] == "capacitor"   # seeds the box
        c7 = next(ln for ln in data["requirements"]["lines"]
                  if "C7" in ln["designators"])
        assert "spec" not in c7 or not c7["spec"]
    finally:
        server.shutdown()
        server.server_close()


# ---------------------------------------------------------------------------
# the search box: the agent plans, Python proves, the agent names the key
# ---------------------------------------------------------------------------

class PlanningInterpreter(CountingInterpreter):
    """Plans a query from the engineer's words and names the requirement."""

    def __init__(self):
        super().__init__(confidence=0.4)
        self.plans = 0
        self.keys = 0
        self.saw_terms = []
        self.forced = []
        self.conventions = []

    def plan_search(self, ctx):
        self.plans += 1
        self.saw_terms.append(ctx["terms"])
        if ctx.get("category"):
            self.forced.append(ctx["category"])
        self.conventions.append(ctx.get("convention") or {})
        return {"mode": "parametric",
                "category": ctx.get("category") or "capacitors",
                "net": {"package": "0805"},
                "sieve": [{"field": "voltage_rating", "op": "gte", "value": 25}],
                "lookingFor": {"kind": "capacitor", "value": "10u",
                               "package": "0805", "qualifier": "25V"},
                "say": "10uF 0805, 25V or better", "confidence": 0.9}

    def derive_key(self, ctx):
        self.keys += 1
        assert ctx["part"]["code"] == "C_OK"      # the VERIFIED part, not a guess
        return {"spec": {"kind": "capacitor", "value": "10u",
                         "package": "0805", "qualifier": "25V"},
                "rationale": "the engineer asked for 25V", "confidence": 0.9}


def _searching_app(tmp_path, interp):
    from test_search_executor import LyingIndex

    src = LyingIndex([{"code": "C_OK", "package": "0805", "voltage_rating": 50},
                      {"code": "C_LOW", "package": "0805", "voltage_rating": 16}])
    app = HendleyApp(db_path=tmp_path / "parts.db", outdir=tmp_path / "out",
                     datasource_factory=lambda: src,
                     bridge_factory=lambda host: MysteryBridge(),
                     interpreter_factory=lambda: interp,
                     draft_path=tmp_path / "draft.json",
                     cache_path=tmp_path / "cache.json")
    return app, src


def test_search_plans_proves_and_caches(tmp_path):
    interp = PlanningInterpreter()
    app, src = _searching_app(tmp_path, interp)
    intake = app.api_intake({"productionQuantity": 5})
    body = {"terms": "10uF 0805 25V", "lineIndex": 0,
            "requirements": intake["requirements"]}
    got = app.api_search(body)
    # the engineer's words reach the agent verbatim
    assert interp.saw_terms == ["10uF 0805 25V"]
    # and only parts PROVEN against every term are offered
    assert [c["code"] for c in got["candidates"]] == ["C_OK"]
    [miss] = got["misses"]
    assert miss["code"] == "C_LOW" and "25" in miss["failed"][0]["why"]
    assert got["planned"]["say"] == "10uF 0805, 25V or better"
    # the same words on the same line are never judged twice
    app.api_search(body)
    assert interp.plans == 1


def test_the_search_on_screen_is_the_search_that_fires(tmp_path):
    """The panel seeds its terms from the part's own catalog spec table — the
    C4/C12/C13/C14 case: a 10uF 50V electrolytic in a D5 x 5.4mm can. Pressing
    Search fires EXACTLY those terms: the index-named ones rebuild the request,
    the catalog-named ones are proven per part. The 63 V part is a strictly
    better drop-in, and until the unit could be declared it was uncheckable —
    which meant invisible."""
    from test_search_executor import LyingIndex

    rows = [{"code": c, "package": "SMD,D5xL5.4mm", "capacitance_farads": 1e-5}
            for c in ("C_50", "C_63", "C_25")]
    src = LyingIndex(rows, catalog={
        "C_50": {"Voltage Rating": "50V", "Diameter": "5mm"},
        "C_63": {"Voltage Rating": "63V", "Diameter": "5mm"},
        "C_25": {"Voltage Rating": "25V", "Diameter": "5mm"}})
    app = HendleyApp(db_path=tmp_path / "parts.db", outdir=tmp_path / "out",
                     datasource_factory=lambda: src,
                     bridge_factory=lambda host: MysteryBridge(),
                     interpreter_factory=lambda: PlanningInterpreter(),
                     draft_path=tmp_path / "draft.json",
                     cache_path=tmp_path / "cache.json")
    intake = app.api_intake({"productionQuantity": 5})
    got = app.api_search({
        "terms": "10uF 50V electrolytic", "lineIndex": 0,
        "requirements": intake["requirements"], "category": "capacitors",
        "sieve": [
            {"field": "package", "op": "eq", "value": "SMD,D5xL5.4mm"},
            {"field": "capacitance_farads", "op": "eq", "value": 1e-5},
            {"field": "Voltage Rating", "op": "gte", "value": 50, "unit": "V"},
            {"field": "Diameter", "op": "eq", "value": "5mm"}]})
    # the request is REBUILT from the terms — only the index-named ones can be
    # query params, so a term you drop cannot come back as one
    assert got["query"] == {"category": "capacitors",
                            "params": {"package": "SMD,D5xL5.4mm",
                                       "capacitance": 1e-5}}
    assert got["judged"] is False        # edited terms fire verbatim: no agent
    assert sorted(c["code"] for c in got["candidates"]) == ["C_50", "C_63"]
    [miss] = got["misses"]
    assert miss["code"] == "C_25" and "≥ 50V" in miss["failed"][0]["why"]


def test_the_agent_names_the_key_the_engineer_never_does(tmp_path):
    interp = PlanningInterpreter()
    app, _ = _searching_app(tmp_path, interp)
    intake = app.api_intake({"productionQuantity": 5})
    got = app.api_key({
        "lineIndex": 0, "requirements": intake["requirements"],
        "terms": "10uF 0805 25V",
        "part": {"code": "C_OK", "mpn": "CL21B106", "package": "0805"}})
    assert got["spec"] == {"kind": "capacitor", "value": "10u",
                           "package": "0805", "qualifier": "25V"}
    assert interp.keys == 1
    # it is the engineer's own act, so it is recorded as theirs — and the next
    # intake applies it with no judgment call at all
    before = interp.calls
    data = app.api_intake({"productionQuantity": 5})
    line = data["requirements"]["lines"][0]
    assert line["spec"]["qualifier"] == "25V"
    assert interp.calls == before and data["uninterpreted"] == []


def test_the_engineer_can_see_and_change_the_query(tmp_path):
    # the category is the biggest decision in a search (it picks the table, so
    # it decides what can appear AND which columns exist to filter on). It must
    # be visible and overridable — an X is a connector in one library and a
    # socket in another, and only the engineer knows which.
    interp = PlanningInterpreter()
    app, src = _searching_app(tmp_path, interp)
    got = app.api_search({"terms": "10uF 0805 25V"})
    # what was actually sent, and what every result had to satisfy, come back
    assert got["query"] == {"category": "capacitors",
                            "params": {"package": "0805"}}
    assert {t["field"] for t in got["proved"]} == {"voltage_rating", "package"}

    # the engineer edits the terms: fired EXACTLY as given, no agent call
    before = interp.plans
    edited = app.api_search({"terms": "10uF 0805 25V", "category": "capacitors",
                             "sieve": []})
    assert interp.plans == before          # their query outranks the agent's
    assert edited["judged"] is False
    assert {c["code"] for c in edited["candidates"]} == {"C_OK", "C_LOW"}
    # A DROPPED TERM STAYS DROPPED. The query is rebuilt from the terms, so a
    # constraint they removed can't sneak back in as a query param (the sieve
    # re-asserts every net param — which would have silently undone the edit).
    assert edited["query"] == {"category": "capacitors", "params": {}}
    assert edited["proved"] == []
    kept = app.api_search({
        "terms": "10uF 0805 25V", "category": "capacitors",
        "sieve": [{"field": "package", "op": "eq", "value": "0805"}]})
    assert kept["query"] == {"category": "capacitors",
                             "params": {"package": "0805"}}


def test_a_forced_category_is_remembered_as_the_shop_s_convention(tmp_path):
    # "X means a connector in MY library" — said once, held forever
    interp = PlanningInterpreter()
    app, _ = _searching_app(tmp_path, interp)
    line = {"lines": [{"designators": ["X1"], "footprint": "CON-JST-2"}]}
    app.api_search({"terms": "2 pin 2mm", "lineIndex": 0,
                    "requirements": line, "category": "jst_connectors"})
    assert interp.forced == ["jst_connectors"]
    assert app._convention("X4") == {"category": "jst_connectors",
                                     "kind": "capacitor",  # the fake's lookingFor
                                     "prefix": "X"}
    # every later X search carries the convention to the agent, unasked
    app.api_search({"terms": "3 pin", "lineIndex": 0, "requirements": line})
    assert interp.conventions[-1]["category"] == "jst_connectors"


def test_categories_are_offered_never_guessed(tmp_path):
    app, _ = _searching_app(tmp_path, PlanningInterpreter())
    cats = app.api_categories({})["categories"]
    slugs = {c["slug"] for c in cats}
    assert {"resistors", "capacitors", "diodes", "components"} <= slugs
    caps = next(c for c in cats if c["slug"] == "capacitors")
    # the columns a term can be proven against — so nobody guesses a field name
    assert "temperature_coefficient" in caps["columns"]
    assert next(c for c in cats if c["slug"] == "bjt_transistors")["empty"]


def test_the_recorded_key_outranks_a_stale_spec_on_the_line(tmp_path):
    # the read-time guess said "capacitor 47u C-E-5"; the engineer's pick then
    # named it "50V". A design carrying the OLD spec must not go looking up a
    # key nothing was ever approved under — the record wins, every time.
    interp = PlanningInterpreter()
    app, _ = _searching_app(tmp_path, interp)
    intake = app.api_intake({"productionQuantity": 5})
    app.api_key({"lineIndex": 0, "requirements": intake["requirements"],
                 "terms": "10uF 0805 25V",
                 "part": {"code": "C_OK", "package": "0805"}})

    stale = json.loads(json.dumps(intake["requirements"]))
    stale["lines"][0]["spec"] = {"kind": "capacitor", "value": "47u",
                                 "package": "C-E-5", "qualifier": ""}
    from hendley.domain.model import RequirementsBom

    bom = RequirementsBom.from_dict(stale)
    app._interpret_lines(bom, consult_interpreter=False)
    assert bom.lines[0].spec.to_dict() == {
        "kind": "capacitor", "value": "10u", "package": "0805",
        "qualifier": "25V"}


def test_a_search_with_no_agent_says_so_rather_than_pretending(tmp_path):
    class Mute(CountingInterpreter):
        def plan_search(self, ctx):
            return None      # the binary is gone

    interp = Mute(confidence=0.4)
    app, src = _searching_app(tmp_path, interp)
    intake = app.api_intake({"productionQuantity": 5})
    got = app.api_search({"terms": "10uF 0805 25V", "lineIndex": 0,
                          "requirements": intake["requirements"]})
    assert got["judged"] is False
    assert got["planned"]["mode"] == "fts"          # verbatim keyword fallback
    assert src.queries[-1] == {"category": "components",
                               "params": {"search": "10uF 0805 25V"}}
    assert "isn't available" in got["planned"]["say"]
