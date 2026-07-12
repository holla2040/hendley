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
    # still unanswered: the card survives WITH the read-time guess prefill,
    # and the LLM is never consulted on a cache load
    [ccard] = cached["uninterpreted"]
    assert ccard["guess"]["spec"]["kind"] == "capacitor"
    assert interp.calls == calls

    # the answer arrives after the read (the Search gesture) …
    app.api_confirm_spec({
        "kindHint": card["kindHint"], "value": card["value"],
        "footprint": card["footprint"],
        "spec": {"kind": "capacitor", "value": "47u", "package": "C-E-5",
                 "qualifier": "50V"}})
    # … and the repopulated design carries it
    cached = app.api_intake_cache({})["cached"]
    assert cached["uninterpreted"] == []
    c7 = next(ln for ln in cached["requirements"]["lines"]
              if "C7" in ln["designators"])
    assert c7["spec"]["value"] == "47u"
    assert interp.calls == calls


def test_clean_emit_clears_the_design_draft(app):
    app.api_draft_put({"design": "demo", "draft": {"productionQuantity": 5}})
    app._clear_draft("demo")   # the hook api_emit runs on a clean export
    assert app.api_draft_get({"design": "demo"})["draft"] is None
    app._clear_draft(None)     # a design-less resolution is a no-op
