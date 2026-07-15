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
        assert 'if (rl.family && !l.ref) return "pick"' in body
        assert 'if (state === "pick") return "unpicked"' in body
        assert 'id="rail-resizer" role="separator"' in body
        assert '--rail-width' in body and 'overflow-x:hidden' in body
        assert 'localStorage.setItem("hendley-rail-width"' in body
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
    approved = client("/api/approve", {"approvals": [{
        "spec": entry["spec"], "lcsc": "C_NEW", "mpn": "MPN-C_NEW",
        "liveStock": 90_000, "unitPrice": 0.001,
        "design": "demo", "note": "queue pick"}]})
    approved_choices = {
        c["lcscCode"]: c
        for c in approved["approvedLists"][0]["housePart"]["choices"]
    }
    assert approved_choices["C_NEW"]["lastStock"] == 90_000
    resolved = client("/api/resolve", {"requirements": req,
                                       "placements": intake["placements"]})
    assert resolved["resolution"]["escalations"] == []
    assert resolved["resolution"]["lines"][0]["ref"] == "C_NEW"
    [approved] = resolved["approvedLists"]
    assert approved["spec"] == spec
    choices = {c["lcscCode"]: c for c in approved["housePart"]["choices"]}
    # This is the same live snapshot resolution just used. The browser can put
    # it straight in the upper table instead of calling verify a second time.
    assert choices["C_NEW"]["lastStock"] == 90_000

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


def test_a_pinned_line_can_be_given_an_approved_list_that_survives_a_refresh(tmp_path):
    """The schematic's LCSC attribute is a DEFAULT, not a lock.

    C4 is pinned to C72487 in Fusion. Until now that line could never hold an
    approved list at all: no checkbox was ever rendered for it, the pinned part
    could not be ranked, and even the house part `/api/key` created was orphaned
    on the next Refresh — `_interpret_lines` skipped pinned lines *before* it
    ever looked at what the engineer had recorded.

    So: name the requirement, approve the pinned part at rank 1 and an alternate
    below it, and the next Refresh must resolve the line against that list —
    which is the only way a short pinned part can substitute down to the alternate.
    """
    from hendley.domain.model import RequirementsBom

    interp = PlanningInterpreter()
    app, _ = _searching_app(tmp_path, interp)
    intake = app.api_intake({"productionQuantity": 5})
    reqs = intake["requirements"]

    # the line the schematic pinned — no spec, just a part number
    reqs["lines"][0].pop("spec", None)
    reqs["lines"][0]["providerRefs"] = {"jlcpcb": "C_OK"}

    # Update: the agent names the requirement from the part actually mounted
    named = app.api_key({"lineIndex": 0, "requirements": reqs,
                         "terms": "10uF 0805 25V",
                         "part": {"code": "C_OK", "package": "0805"}})
    spec = named["spec"]
    app.api_approve({"approvals": [
        {"spec": spec, "lcsc": "C_OK", "rank": 1, "note": "the pinned part"},
        {"spec": spec, "lcsc": "C_LOW", "rank": 999, "note": "approved alt"}]})

    # ---- the next Refresh: the line still comes back PINNED from the schematic
    fresh = RequirementsBom.from_dict(json.loads(json.dumps(reqs)))
    assert fresh.lines[0].provider_refs == {"jlcpcb": "C_OK"}
    app._interpret_lines(fresh, consult_interpreter=False)

    # the recorded key converts it to spec-driven, so it resolves against the
    # approved list instead of hard-mounting the pin
    assert fresh.lines[0].spec.to_dict() == spec
    assert not fresh.lines[0].provider_refs
    house = app._store().lookup(fresh.lines[0].spec)
    assert [c["lcscCode"] for c in house["choices"]] == ["C_OK", "C_LOW"]


def test_an_unrecorded_pin_is_still_a_pin(tmp_path):
    """No approved list means the schematic is still the whole answer — a
    pinned line the engineer never named must not start resolving against
    somebody else's key."""
    from hendley.domain.model import RequirementsBom

    app, _ = _searching_app(tmp_path, PlanningInterpreter())
    reqs = app.api_intake({"productionQuantity": 5})["requirements"]
    reqs["lines"][0].pop("spec", None)
    reqs["lines"][0]["providerRefs"] = {"jlcpcb": "C_OK"}

    fresh = RequirementsBom.from_dict(reqs)
    app._interpret_lines(fresh, consult_interpreter=False)
    assert fresh.lines[0].provider_refs == {"jlcpcb": "C_OK"}   # untouched
    assert fresh.lines[0].spec is None


def test_a_plan_that_sieves_on_a_lying_column_is_thrown_away(tmp_path):
    """Judgments are cached forever — but not a judgment made against a lie.

    A plan carrying `is_polarized isTrue` was cached BEFORE we measured that the
    column is false on every aluminium electrolytic. Replaying it would keep
    rejecting all 36 good parts long after the bug was fixed, and the engineer
    would have no way to know why. The DB has to heal itself.
    """
    interp = PlanningInterpreter()
    app, _ = _searching_app(tmp_path, interp)
    store = app._store()

    poisoned = {"mode": "parametric", "category": "capacitors",
                "net": {"package": "0805"},
                "sieve": [{"field": "voltage_rating", "op": "gte", "value": 25},
                          {"field": "is_polarized", "op": "isTrue"}],
                "say": "stale", "confidence": 0.9}
    assert app._stale_plan(poisoned) is True
    assert app._stale_plan({"sieve": [{"field": "voltage_rating", "op": "gte",
                                       "value": 25}]}) is False

    store.put_interpretation("search", poisoned, "llm", kind_hint="C",
                             raw_value="10uF 0805 25V\x1f\x1f", footprint="C-0603")
    intake = app.api_intake({"productionQuantity": 5})
    got = app.api_search({"terms": "10uF 0805 25V", "lineIndex": 0,
                          "requirements": intake["requirements"]})

    # the stale plan was NOT replayed — the agent was asked again
    assert interp.plans == 1
    assert not any(t["field"] == "is_polarized" for t in got["planned"]["sieve"])
    assert [c["code"] for c in got["candidates"]] == ["C_OK"]


# --------------------------------------------------------------------------
# The FAMILY (ADR-0008). A designer types "ULN2003" into the schematic VALUE.
# That is not a part: it ships in five packages and the board decides which one.
# --------------------------------------------------------------------------

# the real catalog rows for this family (measured 2026-07-13)
ULN2003_ROWS = [
    {"code": "C7512", "package": "SOIC-16"},          # D suffix: 3.9mm body
    {"code": "C94832", "package": "SOIC-16"},
    {"code": "C2859910", "package": "SO-16-208mil"},  # NS suffix: WIDE body
    {"code": "C126289", "package": "TSSOP-16"},
    {"code": "C93000", "package": "DIP-16"},
]

FAMILY_LINE = {
    "designators": ["U1"], "quantityPer": 1, "comment": "ULN2003",
    "family": "ULN2003", "footprint": "SO16",
    "footprintHeadline": "Small Outline package 150 mil",
}


class FamilyInterpreter:
    """Reads the footprint's geometry, and knows what the web knows."""

    name = "family"

    def __init__(self):
        self.footprint_calls = 0
        self.family_calls = 0
        self.saw_headline = []
        self.saw_packages = []

    def interpret_part(self, ctx):
        from hendley.ai.interpreter import Interpretation

        return Interpretation()

    def interpret_footprint(self, footprint, headline=""):
        self.footprint_calls += 1
        return {"package": "SOIC-16", "envelope": {"mount": "smd"},
                "confidence": 0.95, "rationale": "150 mil ⇒ the 3.9mm body"}

    def read_family(self, family, footprint="", headline="", packages=()):
        self.family_calls += 1
        self.saw_packages.append(list(packages))
        self.saw_headline.append(headline)
        # the package is CHOSEN from the catalog's own list, never invented
        assert ("SOIC-16", 2) in packages
        return {"packages": ["SOIC-16"],
                "partNumbers": ["ULN2003ADR"],
                "class": "darlington transistor array",
                "traps": [{"part": "ULN2003ANSR",
                           "why": "the NS suffix is the 5.3mm wide body"}],
                "rationale": "D = SOIC 3.9mm", "confidence": 0.9}

    def plan_search(self, ctx):
        raise AssertionError("a family line needs no plan — it already has one")


def _family_app(tmp_path, interp, rows=None):
    from test_search_executor import LyingIndex

    src = LyingIndex(rows if rows is not None else ULN2003_ROWS)
    app = HendleyApp(db_path=tmp_path / "parts.db", outdir=tmp_path / "out",
                     datasource_factory=lambda: src,
                     interpreter_factory=lambda: interp,
                     draft_path=tmp_path / "draft.json",
                     cache_path=tmp_path / "cache.json")
    return app, src


def test_a_family_line_searches_itself_with_no_words_typed(tmp_path):
    # The designer already typed "ULN2003" and the board already states the land.
    # There is nothing left for the engineer to type — asking them to would be
    # asking them to repeat the schematic back to us. And no agent plans it: every
    # term is already known (ADR-0008 — Python composes THIS query, and only this).
    interp = FamilyInterpreter()
    app, src = _family_app(tmp_path, interp)
    got = app.api_search({"lineIndex": 0,
                          "requirements": {"lines": [FAMILY_LINE]}})
    assert got["planned"]["net"] == {"search": "ULN2003", "package": "SOIC-16"}
    # two calls: first the catalog is asked which packages it stocks this family
    # in (its own vocabulary), then the real search fires with the chosen one
    assert src.queries == [
        {"category": "components", "params": {"search": "ULN2003"}},
        {"category": "components", "params": {"search": "ULN2003",
                                              "package": "SOIC-16"}},
    ]
    assert got["judged"] is False


def test_the_catalogs_vocabulary_is_asked_for_once_then_cached(tmp_path):
    interp = FamilyInterpreter()
    app, src = _family_app(tmp_path, interp)
    for _ in range(3):
        app.api_search({"lineIndex": 0, "requirements": {"lines": [FAMILY_LINE]}})
    probes = [q for q in src.queries if "package" not in q["params"]]
    assert len(probes) == 1        # the vocabulary probe never runs again


def test_the_package_is_chosen_from_the_catalogs_own_vocabulary(tmp_path):
    # THE BUG THIS FIXES. A package judged from the library's footprint name is a
    # guess AT the catalog's word, not a reading OF it — and they disagree exactly
    # where it hurts: the library calls a bridge rectifier's land "SOIC-4" and the
    # catalog calls it "MBS". `package=SOIC-4` returns ZERO rows while looking
    # entirely reasonable. So the agent picks from the list the catalog gives.
    MB10S = [{"code": "C2886577", "package": "MBS"},
             {"code": "C2488", "package": "MBS"},
             {"code": "C350537", "package": "SMD-4P"}]

    class Rectifier(FamilyInterpreter):
        def interpret_footprint(self, footprint, headline=""):
            self.footprint_calls += 1     # would say "SOIC-4" — a word JLC never uses
            return {"package": "SOIC-4", "envelope": {}, "confidence": 0.9,
                    "rationale": "a 4-pin small-outline land"}

        def read_family(self, family, footprint="", headline="", packages=()):
            self.family_calls += 1
            assert ("MBS", 2) in packages          # the catalog's own word
            return {"packages": ["MBS"], "partNumbers": ["MB10S"],
                    "class": "bridge rectifier",
                    "traps": [{"part": "MB6S", "why": "600V, not 1000V"}],
                    "rationale": "the catalog calls this land MBS",
                    "confidence": 0.9}

    interp = Rectifier()
    app, _ = _family_app(tmp_path, interp, rows=MB10S)
    line = {**FAMILY_LINE, "family": "MB10S", "footprint": "SOIC-4",
            "footprintHeadline": None}
    got = app.api_search({"lineIndex": 0, "requirements": {"lines": [line]}})
    assert got["planned"]["net"] == {"search": "MB10S", "package": "MBS"}
    assert [c["code"] for c in got["candidates"]] == ["C2886577", "C2488"]


def test_the_footprints_geometry_reaches_the_judgment(tmp_path):
    interp = FamilyInterpreter()
    app, _ = _family_app(tmp_path, interp)
    app.api_search({"lineIndex": 0, "requirements": {"lines": [FAMILY_LINE]}})
    assert interp.saw_headline == ["Small Outline package 150 mil"]


def test_a_package_the_catalog_does_not_use_is_never_fired(tmp_path):
    # if the web answers with a package the catalog has never heard of, it is
    # dropped — firing it would return nothing while looking like a real search
    class Inventing(FamilyInterpreter):
        def read_family(self, family, footprint="", headline="", packages=()):
            self.family_calls += 1
            return {"packages": ["SOIC-16-NARROW"],   # not a word JLC uses
                    "partNumbers": [], "class": "", "traps": [],
                    "rationale": "", "confidence": 0.9}

    interp = Inventing()
    app, _ = _family_app(tmp_path, interp)
    got = app.api_search({"lineIndex": 0,
                          "requirements": {"lines": [FAMILY_LINE]}})
    # it fell back to the footprint judgment, which the catalog DOES use
    assert got["planned"]["net"]["package"] == "SOIC-16"
    assert interp.footprint_calls == 1


def test_a_family_search_offers_only_what_fits_the_land(tmp_path):
    # The wide body, the TSSOP and the DIP all answer to the name "ULN2003" and
    # none of them can go on this board. The index ANDs the words against part
    # NAMES, so if it quietly dropped `package` — which is what it does to every
    # param it doesn't know — a DIP-16 part would be offered for a 150-mil land
    # and nothing on screen would say so. The sieve re-asserts it and proves it.
    from test_search_executor import LyingIndex

    class IgnoresPackage(LyingIndex):
        def discover(self, query):
            self.queries.append(query)
            return list(self.rows)

    interp = FamilyInterpreter()
    app, _ = _family_app(tmp_path, interp)
    app._datasource_factory = lambda: IgnoresPackage(ULN2003_ROWS)
    got = app.api_search({"lineIndex": 0,
                          "requirements": {"lines": [FAMILY_LINE]}})
    assert [c["code"] for c in got["candidates"]] == ["C7512", "C94832"]
    rejected = {c["code"]: c["failed"][0]["field"] for c in got["misses"]}
    assert set(rejected) == {"C2859910", "C126289", "C93000"}
    assert set(rejected.values()) == {"package"}     # named, with a reason


def test_the_web_names_the_right_variant_and_the_traps(tmp_path):
    interp = FamilyInterpreter()
    app, _ = _family_app(tmp_path, interp)
    got = app.api_search({"lineIndex": 0,
                          "requirements": {"lines": [FAMILY_LINE]}})
    assert got["family"]["partNumbers"] == ["ULN2003ADR"]
    [trap] = got["family"]["traps"]
    assert trap["part"] == "ULN2003ANSR" and "wide body" in trap["why"]


def test_the_family_is_read_from_the_web_once_ever(tmp_path):
    # what a part-number suffix MEANS does not change; a web call is slow and
    # costs money. Asked once per (family, footprint), then cached forever.
    interp = FamilyInterpreter()
    app, _ = _family_app(tmp_path, interp)
    for _ in range(3):
        app.api_search({"lineIndex": 0, "requirements": {"lines": [FAMILY_LINE]}})
    assert interp.family_calls == 1
    # and the footprint judgment never ran at all: the web read the package off
    # the catalog's own list, which is a better answer than a name can give
    assert interp.footprint_calls == 0


def test_a_cached_generic_spec_cannot_overwrite_a_family_line(tmp_path):
    interp = FamilyInterpreter()
    app, _ = _family_app(tmp_path, interp)
    app._store().put_interpretation(
        "part", {"spec": {"kind": "ic", "value": "GENERIC48",
                           "package": "LQFP-48", "qualifier": ""}},
        "llm", kind_hint="U", raw_value="GENERIC48", footprint="LOCAL-48")
    from hendley.domain.model import RequirementsBom

    reqs = RequirementsBom.from_dict({"productionQuantity": 1, "lines": [{
        "designators": ["U42"], "comment": "GENERIC48", "family": "GENERIC48",
        "footprint": "LOCAL-48",
    }]})
    app._interpret_lines(reqs, consult_interpreter=False)

    assert reqs.lines[0].family == "GENERIC48"
    assert reqs.lines[0].spec is None
    assert reqs.lines[0].mode is None


def test_a_cached_diode_spec_replaces_its_provisional_family(tmp_path):
    app, _ = _family_app(tmp_path, FamilyInterpreter())
    app._store().put_interpretation(
        "part", {"spec": {"kind": "diode", "value": "3.3V",
                           "package": "SOD-323", "qualifier": "zener"}},
        "llm", kind_hint="D", raw_value="3V3", footprint="D-SOD323")
    from hendley.domain.model import RequirementsBom

    reqs = RequirementsBom.from_dict({"productionQuantity": 1, "lines": [{
        "designators": ["D42"], "comment": "3V3", "family": "3V3",
        "footprint": "D-SOD323",
    }]})
    app._interpret_lines(reqs, consult_interpreter=False)

    assert reqs.lines[0].family is None
    assert reqs.lines[0].spec.value == "3.3V"
    assert reqs.lines[0].mode == "spec"


def test_a_family_whose_package_nobody_can_name_asks_rather_than_guessing(tmp_path):
    # Neither the web nor the footprint judgment can say which of the catalog's
    # packages this land is. Guessing would fire a query that returns nothing and
    # looks like "JLC doesn't stock it". Instead: say so, and NAME the packages
    # the catalog does have, so the engineer can choose.
    from hendley.app.server import ApiError

    class Baffled(FamilyInterpreter):
        def interpret_footprint(self, footprint, headline=""):
            return {"package": "", "envelope": {}, "confidence": 0.95,
                    "rationale": "nothing standard recognizable"}

        def read_family(self, family, footprint="", headline="", packages=()):
            self.family_calls += 1
            return {"packages": [], "partNumbers": [], "class": "", "traps": [],
                    "rationale": "cannot tell", "confidence": 0.2}

    app, _ = _family_app(tmp_path, Baffled())
    line = {**FAMILY_LINE, "footprint": "WEIRD-LOCAL-THING"}
    with pytest.raises(ApiError) as e:
        app.api_search({"lineIndex": 0, "requirements": {"lines": [line]}})
    assert "SOIC-16" in str(e.value)      # the catalog's own packages, named


def test_an_ambiguous_function_label_is_not_presented_as_a_family(tmp_path):
    from hendley.app.server import ApiError

    class FunctionalLabel(FamilyInterpreter):
        def read_family(self, family, footprint="", headline="", packages=()):
            return {"packages": ["SOIC-8"], "partNumbers": ["PART3V3", "PART5V"],
                    "class": "bus transceiver", "traps": [],
                    "rationale": "the design does not state 3.3V or 5V",
                    "confidence": 0.75}

    app, src = _family_app(tmp_path, FunctionalLabel(), rows=[
        {"code": "C_3V3", "package": "SOIC-8"},
        {"code": "C_5V", "package": "SOIC-8"},
    ])
    line = {**FAMILY_LINE, "family": "BUS TRANSCEIVER", "footprint": "SO8"}

    with pytest.raises(ApiError, match="not specific enough"):
        app.api_search({"lineIndex": 0, "requirements": {"lines": [line]}})
    # Only the vocabulary probe ran; neither plausible but electrically
    # incompatible candidate was presented as an orderable answer.
    assert len(src.queries) == 1


def test_the_web_being_down_does_not_stop_the_catalog_sweep(tmp_path):
    # the sweep is family + package and needs no agent. If read_family is
    # unavailable we lose the traps — we do NOT lose the parts.
    class WebDown(FamilyInterpreter):
        def read_family(self, family, footprint="", headline="", packages=()):
            return None

    app, _ = _family_app(tmp_path, WebDown())
    got = app.api_search({"lineIndex": 0,
                          "requirements": {"lines": [FAMILY_LINE]}})
    assert got["family"] == {}
    # the footprint judgment carried it, and the parts still arrive
    assert got["planned"]["net"]["package"] == "SOIC-16"
    assert [c["code"] for c in got["candidates"]] == ["C7512", "C94832"]


def test_a_land_with_two_catalog_names_fires_one_request_each(tmp_path):
    # SOIC-8 and SOP-8 are the same 3.9mm body. The index takes ONE package per
    # request, and it caps a listing at 100 rows and will not go higher (measured:
    # 1N4148, LM358 and AMS1117 all return exactly 100; limit=500 changes nothing).
    # So we fire one narrow request per spelling rather than widening the net to
    # the bare family, which would quietly truncate a popular part.
    SP3485 = [{"code": "C8963", "package": "SOIC-8"},        # Basic, big stock
              {"code": "C668205", "package": "SOP-8"},       # same land
              {"code": "C5199842", "package": "MSOP-8"}]     # a DIFFERENT land

    class TwoNames(FamilyInterpreter):
        def read_family(self, family, footprint="", headline="", packages=()):
            self.family_calls += 1
            return {"packages": ["SOIC-8", "SOP-8"],
                    "partNumbers": ["SP3485EN-L"], "class": "RS-485 transceiver",
                    "traps": [{"part": "MAX485", "why": "a +5V part, same pinout"}],
                    "rationale": "one land, two of the catalog's words",
                    "confidence": 0.9}

    app, src = _family_app(tmp_path, TwoNames(), rows=SP3485)
    line = {**FAMILY_LINE, "family": "SP3485", "footprint": "IC-SO8",
            "footprintHeadline": "D (R-PDSO-G8)"}
    got = app.api_search({"lineIndex": 0, "requirements": {"lines": [line]}})

    # one request per spelling, each narrow — never a bare-family net
    assert got["queries"] == [
        {"category": "components", "params": {"search": "SP3485",
                                              "package": "SOIC-8"}},
        {"category": "components", "params": {"search": "SP3485",
                                              "package": "SOP-8"}},
    ]
    # ONE table: the engineer is picking a part, not reading a query log
    assert [c["code"] for c in got["candidates"]] == ["C8963", "C668205"]
    # and every part is proven against the LAND, not the spelling that fetched it
    assert got["proved"] == [{"field": "package", "op": "in",
                              "value": ["SOIC-8", "SOP-8"]}]


def test_a_capped_package_sample_does_not_hide_an_unseen_familys_land(tmp_path):
    """A new design must not be limited to packages in a capped 100-row sample."""
    from test_search_executor import LyingIndex

    rows = [{"code": f"C_SAMPLE_{i}", "package": "QFN-32"} for i in range(100)]
    rows.append({"code": "C_RIGHT", "package": "LQFP-48"})

    class CappedCatalog(LyingIndex):
        def discover(self, query):
            self.queries.append(query)
            package = (query.get("params") or {}).get("package")
            if package:
                return [r for r in self.rows if r["package"] == package]
            return list(self.rows[:100])

    class UnseenMcu(FamilyInterpreter):
        def read_family(self, family, footprint="", headline="", packages=()):
            self.family_calls += 1
            assert getattr(packages, "truncated", False)
            assert "LQFP-48" not in {p for p, _ in packages}
            return {"packages": ["LQFP-48"], "partNumbers": ["GENERIC48-A"],
                    "class": "microcontroller", "traps": [],
                    "rationale": "the ordering table maps A to LQFP-48",
                    "confidence": 0.9}

    src = CappedCatalog(rows)
    interp = UnseenMcu()
    app = HendleyApp(db_path=tmp_path / "parts.db", outdir=tmp_path / "out",
                     datasource_factory=lambda: src,
                     interpreter_factory=lambda: interp,
                     draft_path=tmp_path / "draft.json",
                     cache_path=tmp_path / "cache.json")
    line = {**FAMILY_LINE, "family": "GENERIC48", "footprint": "LOCAL-MCU-48"}
    got = app.api_search({"lineIndex": 0, "requirements": {"lines": [line]}})

    assert [c["code"] for c in got["candidates"]] == ["C_RIGHT"]
    # Its spelling was absent from the sample, so it was proved narrowly before
    # becoming the real search plan. No trust is placed in either guess alone.
    hidden = {"category": "components",
              "params": {"search": "GENERIC48", "package": "LQFP-48"}}
    assert src.queries.count(hidden) == 2


def test_an_empty_cached_family_judgment_is_re_read_once(tmp_path):
    """A transient first answer must not poison every later unseen design."""
    rows = [{"code": "C_HEALED", "package": "TSSOP-20"}]

    class HealedFamily(FamilyInterpreter):
        def read_family(self, family, footprint="", headline="", packages=()):
            self.family_calls += 1
            return {"packages": ["TSSOP-20"], "partNumbers": ["FRESH20A"],
                    "class": "interface IC", "traps": [],
                    "rationale": "fresh catalog-backed read", "confidence": 0.9}

    interp = HealedFamily()
    app, src = _family_app(tmp_path, interp, rows=rows)
    line = {**FAMILY_LINE, "family": "FRESH20", "footprint": "LOCAL-20"}
    app._store().put_interpretation(
        "family", {"packages": ["QFN-20"], "partNumbers": [], "traps": []},
        "llm", raw_value="FRESH20", footprint="LOCAL-20", confidence=0.8)

    got = app.api_search({"lineIndex": 0, "requirements": {"lines": [line]}})

    assert [c["code"] for c in got["candidates"]] == ["C_HEALED"]
    assert interp.family_calls == 1
    assert any(q["params"].get("package") == "QFN-20" for q in src.queries)
    assert any(q["params"].get("package") == "TSSOP-20" for q in src.queries)


def test_a_dead_column_is_dead_only_in_its_own_category(tmp_path):
    # A column is a lie IN A CATEGORY, not everywhere. `color` proves nothing on
    # a 7-segment display and proves plenty on an LED; `has_i2c` is a lie on an
    # accelerometer and is the whole point of an io_expander. Testing against a
    # FLAT UNION condemned 16 categories' honest columns — every LED, LDO, MCU,
    # ADC and I/O-expander plan was discarded on sight and the agent re-asked
    # from scratch, for ever. A cache that never hits is not a cache.
    app = HendleyApp(db_path=tmp_path / "parts.db", outdir=tmp_path / "out",
                     draft_path=tmp_path / "draft.json",
                     cache_path=tmp_path / "cache.json")
    honest = {"category": "leds",
              "sieve": [{"field": "color", "op": "eq", "value": "red"}]}
    assert not app._stale_plan(honest)          # `color` is real on an LED

    lie = {"category": "capacitors",
           "sieve": [{"field": "is_polarized", "op": "isTrue"}]}
    assert app._stale_plan(lie)                 # and false on every electrolytic

    # the family search's own table: the index's class columns are a lie there
    klass = {"category": "components",
             "sieve": [{"field": "subcategory", "op": "eq",
                        "value": "Bridge Rectifiers"}]}
    assert app._stale_plan(klass)               # would reject the MB10S on the board
