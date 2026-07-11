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


@pytest.fixture
def client(tmp_path):
    source = FakeSource(
        stocks={"C31850": 40, "C_NEW": 90_000},
        discovered=[{"code": "C_NEW", "mfr": "0603WAF2202T5E", "package": "0603",
                     "jlcsearch_stock": 5, "price1": 0.001}])
    app = HendleyApp(db_path=tmp_path / "parts.db", outdir=tmp_path / "out",
                     datasource_factory=lambda: source,
                     bridge_factory=lambda host: FakeBridge())
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
    app = HendleyApp(db_path=tmp_path / "parts.db", outdir=tmp_path / "out")
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

    bad = client("/api/record", {"kind": "resistor", "value": "", "package": "0603",
                                 "lcsc": "C1"}, expect=400)
    assert "spec" in bad["error"]


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
