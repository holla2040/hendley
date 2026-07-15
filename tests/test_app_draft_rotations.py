"""The app's rotation-correction and order-draft endpoints (single-page UI).

Method-level tests over HendleyApp — the HTTP plumbing is exercised by
test_app.py; these cover the new JSON behavior: rotation upsert/remove keyed
by footprint or LCSC, draft save/reapply/clear, and the draft wipe on a clean
emit path (_clear_draft).
"""

import json

import pytest

from hendley.app.server import GET_ROUTES, POST_ROUTES, ApiError, HendleyApp


@pytest.fixture
def app(tmp_path):
    rotations = tmp_path / "cpl-rotations.json"
    rotations.write_text(json.dumps({
        "schemaVersion": 1,
        "corrections": [
            {"footprint": "D-SOD123", "rotationOffsetDeg": 180,
             "verified": "seed"},
        ],
    }))
    return HendleyApp(db_path=tmp_path / "parts.db", outdir=tmp_path / "out",
                      rotations_path=rotations,
                      draft_path=tmp_path / "draft.json")


def test_new_routes_are_registered():
    assert GET_ROUTES["/api/rotations"] == "api_rotations"
    assert GET_ROUTES["/api/draft"] == "api_draft_get"
    assert POST_ROUTES["/api/rotation"] == "api_rotation"
    assert POST_ROUTES["/api/draft"] == "api_draft_put"


# ---------------------------------------------------------------------------
# rotations
# ---------------------------------------------------------------------------

def test_rotations_lists_the_file(app):
    got = app.api_rotations({})
    assert [c["footprint"] for c in got["corrections"]] == ["D-SOD123"]
    assert got["path"].endswith("cpl-rotations.json")


def test_rotation_upsert_update_and_remove_by_footprint(app, tmp_path):
    got = app.api_rotation({"footprint": "LED-0603", "lcsc": "C2286",
                            "rotationOffsetDeg": 90})
    entry = next(c for c in got["corrections"] if c.get("footprint") == "LED-0603")
    assert entry["rotationOffsetDeg"] == 90 and entry["lcsc"] == "C2286"
    assert "set via the app" in entry["verified"]

    # update in place — still one entry for the footprint
    got = app.api_rotation({"footprint": "LED-0603", "rotationOffsetDeg": 270,
                            "note": "checked against JLC preview"})
    entries = [c for c in got["corrections"] if c.get("footprint") == "LED-0603"]
    assert len(entries) == 1 and entries[0]["rotationOffsetDeg"] == 270
    assert entries[0]["verified"] == "checked against JLC preview"

    # offset 0 removes the correction; the seed entry is untouched
    got = app.api_rotation({"footprint": "LED-0603", "rotationOffsetDeg": 0})
    assert [c["footprint"] for c in got["corrections"]] == ["D-SOD123"]

    # the file on disk is the record
    doc = json.loads((tmp_path / "cpl-rotations.json").read_text())
    assert [c["footprint"] for c in doc["corrections"]] == ["D-SOD123"]


def test_rotation_lcsc_only_entry(app):
    got = app.api_rotation({"lcsc": "C970025", "rotationOffsetDeg": 270})
    entry = next(c for c in got["corrections"] if c.get("lcsc") == "C970025")
    assert "footprint" not in entry
    got = app.api_rotation({"lcsc": "C970025", "rotationOffsetDeg": 0})
    assert all(c.get("lcsc") != "C970025" for c in got["corrections"])


def test_rotation_rejects_bad_input(app):
    with pytest.raises(ApiError, match="footprint.*lcsc|'footprint' or 'lcsc'"):
        app.api_rotation({"rotationOffsetDeg": 90})
    with pytest.raises(ApiError, match="integer"):
        app.api_rotation({"footprint": "X", "rotationOffsetDeg": "sideways"})


def test_rotations_missing_file_is_operational_error(tmp_path):
    app = HendleyApp(db_path=tmp_path / "parts.db",
                     rotations_path=tmp_path / "nope.json",
                     draft_path=tmp_path / "draft.json")
    with pytest.raises(ApiError) as err:
        app.api_rotations({})
    assert err.value.status == 503


# ---------------------------------------------------------------------------
# draft
# ---------------------------------------------------------------------------

def test_draft_roundtrip_and_clear(app):
    assert app.api_draft_get({"design": "demo"})["draft"] is None

    draft = {"productionQuantity": 25,
             "overrides": {"R6,R7": {"code": "C25768"}},
             "savedAt": "2026-07-12T10:00:00Z"}
    assert app.api_draft_put({"design": "demo", "draft": draft})["draft"] == draft
    assert app.api_draft_get({"design": "demo"})["draft"] == draft
    # per-design isolation
    assert app.api_draft_get({"design": "other"})["draft"] is None

    assert app.api_draft_put({"design": "demo", "draft": None})["draft"] is None
    assert app.api_draft_get({"design": "demo"})["draft"] is None


def test_draft_requires_design(app):
    with pytest.raises(ApiError, match="design"):
        app.api_draft_put({"draft": {}})


def test_intake_cache_repopulates_with_later_corrections(tmp_path):
    from test_app import CountingInterpreter, FakeSource, MysteryBridge

    interp = CountingInterpreter(confidence=0.4)  # C7 needs the engineer
    app = HendleyApp(db_path=tmp_path / "parts.db", outdir=tmp_path / "out",
                     datasource_factory=lambda: FakeSource({}),
                     bridge_factory=lambda host: MysteryBridge(),
                     interpreter_factory=lambda: interp,
                     rotations_path=tmp_path / "rot.json",
                     draft_path=tmp_path / "draft.json",
                     cache_path=tmp_path / "cache.json")
    assert app.api_intake_cache({})["cached"] is None

    intake = app.api_intake({"productionQuantity": 5})
    [card] = intake["uninterpreted"]
    calls = interp.calls

    cached = app.api_intake_cache({})["cached"]
    assert cached["design"] == "demo" and cached["savedAt"]
    # Still unanswered: Refresh and cache load both preserve the card without
    # launching the agent. The guess remains empty until this line is opened.
    [ccard] = cached["uninterpreted"]
    assert ccard["guess"]["spec"] is None
    assert interp.calls == calls == 0

    # the answer arrives after the read — the engineer picked a part, and the
    # AGENT named the requirement from it (no form was ever shown)
    app.api_key({
        "lineIndex": card["lineIndex"], "requirements": intake["requirements"],
        "terms": "47u 50V electrolytic",
        "part": {"code": "C_E", "mpn": "EEU-FR1H470", "package": "C-E-5"}})
    # … and the repopulated design carries it
    cached = app.api_intake_cache({})["cached"]
    assert cached["uninterpreted"] == []
    c7 = next(ln for ln in cached["requirements"]["lines"]
              if "C7" in ln["designators"])
    assert c7["spec"]["value"] == "47u"
    assert interp.calls == calls


def test_intake_cache_does_not_eagerly_judge_a_package(tmp_path):
    from test_app import FakeSource, JudgingInterpreter, MysteryBridge

    interp = JudgingInterpreter(package="SMD-5x5")
    app = HendleyApp(db_path=tmp_path / "parts.db", outdir=tmp_path / "out",
                     datasource_factory=lambda: FakeSource({}),
                     bridge_factory=lambda host: MysteryBridge(),
                     interpreter_factory=lambda: interp,
                     rotations_path=tmp_path / "rot.json",
                     draft_path=tmp_path / "draft.json",
                     cache_path=tmp_path / "cache.json")
    intake = app.api_intake({"productionQuantity": 5})
    [card] = intake["uninterpreted"]
    assert "judgedPackage" not in card
    calls = interp.footprint_calls

    # A cache load also stays cache-only; neither path invents a prefill.
    cached = app.api_intake_cache({})["cached"]
    [ccard] = cached["uninterpreted"]
    assert "judgedPackage" not in ccard
    assert "judgedEnvelope" not in ccard
    assert interp.footprint_calls == calls == 0


class _Planner:
    """Plans whatever it is asked; counts the judgments."""

    name = "planner"

    def __init__(self):
        self.calls = 0

    def plan_search(self, ctx):
        self.calls += 1
        return {"mode": "fts", "category": "components",
                "net": {"search": ctx["terms"]}, "sieve": [],
                "lookingFor": {}, "say": "by name", "confidence": 0.9}


def test_the_catalog_is_searchable_without_opening_a_part(tmp_path):
    # the overview's box: no design line, no spec, no recording — just a
    # verified answer to "what is out there"
    from test_app import FakeSource

    planner = _Planner()
    src = FakeSource(stocks={"C1": 500},
                     discovered=[{"code": "C1"}, {"code": "C_GONE"}])
    app = HendleyApp(db_path=tmp_path / "parts.db",
                     datasource_factory=lambda: src,
                     interpreter_factory=lambda: planner,
                     draft_path=tmp_path / "draft.json",
                     cache_path=tmp_path / "cache.json")
    got = app.api_search({"terms": "zener 10V"})     # no lineIndex
    assert got["terms"] == "zener 10V"
    assert [c["code"] for c in got["candidates"]] == ["C1"]  # C_GONE unverified
    assert got["candidates"][0]["manufacturer"] == "MFR-C1"
    assert got["misses"][0]["code"] == "C_GONE"
    with pytest.raises(ApiError, match="terms"):
        app.api_search({})


def test_a_plan_is_judged_once_per_words_and_line(tmp_path):
    from test_app import FakeSource

    planner = _Planner()
    app = HendleyApp(db_path=tmp_path / "parts.db",
                     datasource_factory=lambda: FakeSource({"C1": 5}),
                     interpreter_factory=lambda: planner,
                     draft_path=tmp_path / "draft.json",
                     cache_path=tmp_path / "cache.json")
    app.api_search({"terms": "1n4148ws"})
    app.api_search({"terms": "1n4148ws"})
    assert planner.calls == 1        # cached forever
    app.api_search({"terms": "1n4148 sod-123"})
    assert planner.calls == 2        # different words, a new judgment


def test_part_verify_refreshes_live_stock(tmp_path):
    from test_app import FakeSource

    app = HendleyApp(db_path=tmp_path / "parts.db",
                     datasource_factory=lambda: FakeSource({"C1": 777}),
                     draft_path=tmp_path / "draft.json",
                     cache_path=tmp_path / "cache.json")
    spec = {"kind": "resistor", "value": "1k", "package": "0603",
            "qualifier": ""}
    app.api_record({"spec": spec, "lcsc": "C1"})
    cached = app.api_part(dict(spec))["housePart"]
    assert cached["choices"][0]["lastStock"] is None   # advisory cache empty
    live = app.api_part({**spec, "verify": "1"})["housePart"]
    assert live["choices"][0]["lastStock"] == 777      # verified NOW


def test_part_verify_down_says_unknown_not_stale(tmp_path):
    def no_live():
        raise ApiError("live JLC access needs credentials", status=503)

    app = HendleyApp(db_path=tmp_path / "parts.db",
                     datasource_factory=no_live,
                     draft_path=tmp_path / "draft.json",
                     cache_path=tmp_path / "cache.json")
    spec = {"kind": "resistor", "value": "1k", "package": "0603",
            "qualifier": ""}
    app.api_record({"spec": spec, "lcsc": "C1"})
    got = app.api_part({**spec, "verify": "1"})["housePart"]
    [c] = got["choices"]
    assert c["stockUnknown"] is True
    assert c["lastStock"] is None and c["lastPrice"] is None


def test_clean_emit_clears_the_design_draft(app):
    app.api_draft_put({"design": "demo", "draft": {"productionQuantity": 5}})
    app._clear_draft("demo")   # the hook api_emit runs on a clean export
    assert app.api_draft_get({"design": "demo"})["draft"] is None
    app._clear_draft(None)     # a design-less resolution is a no-op
