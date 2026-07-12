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


def test_explore_returns_only_verified_candidates(tmp_path):
    from test_app import FakeSource

    src = FakeSource(stocks={"C1": 500},
                     discovered=[{"code": "C1"}, {"code": "C_GONE"}])
    app = HendleyApp(db_path=tmp_path / "parts.db",
                     datasource_factory=lambda: src,
                     draft_path=tmp_path / "draft.json",
                     cache_path=tmp_path / "cache.json")
    got = app.api_explore({"search": "zener 10V"})
    assert got["search"] == "zener 10V"
    assert [c["code"] for c in got["candidates"]] == ["C1"]  # C_GONE unverified
    assert got["candidates"][0]["manufacturer"] == "MFR-C1"
    with pytest.raises(ApiError, match="search"):
        app.api_explore({})


class _PackageSource:
    """Verified candidates with per-code packages, for the explore filter."""

    name = "pkg"

    def __init__(self, packages: dict):
        self.packages = packages

    def discover(self, query):
        return [{"code": c} for c in self.packages]

    def verify(self, refs):
        from hendley.datasources.base import PartFact

        return {r: PartFact(
            ref=r, found=True, stock=1000, mpn=f"MPN-{r}",
            price_tiers=[{"startQuantity": 1, "unitPrice": 0.01}],
            raw={"componentCode": r, "componentModel": f"MPN-{r}",
                 "componentSpecification": self.packages[r],
                 "stockCount": 1000, "libraryType": "Basic",
                 "priceRanges": [{"startQuantity": 1, "unitPrice": 0.01}],
                 "parameters": []},
            provenance=self.name) for r in refs}


class _FootprintJudge:
    def __init__(self, package="0603", confidence=0.9):
        self.calls = 0
        self.package = package
        self.confidence = confidence

    def interpret_footprint(self, footprint):
        self.calls += 1
        return {"package": self.package, "envelope": {"mount": "smd"},
                "confidence": self.confidence, "rationale": "chip size"}


def test_explore_filters_to_the_agent_judged_package(tmp_path):
    judge = _FootprintJudge()
    app = HendleyApp(db_path=tmp_path / "parts.db",
                     datasource_factory=lambda: _PackageSource(
                         {"C_0603": "0603", "C_0805": "0805"}),
                     interpreter_factory=lambda: judge,
                     draft_path=tmp_path / "draft.json",
                     cache_path=tmp_path / "cache.json")
    got = app.api_explore({"search": "4.7u", "footprint": "C-0603"})
    assert got["package"] == "0603"
    # ALL verified candidates return — the page does the package split,
    # so nothing filtered is ever unreachable
    assert [c["code"] for c in got["candidates"]] == ["C_0603", "C_0805"]
    assert judge.calls == 1

    # judged once, ever — the cache answers from now on
    app.api_explore({"search": "4.7u", "footprint": "C-0603"})
    assert judge.calls == 1


def test_explore_explicit_package_skips_the_judgment(tmp_path):
    # a spec line's package is already agent-normalized — no interpreter call
    def no_interpreter():
        raise AssertionError("interpreter must not be consulted")

    app = HendleyApp(db_path=tmp_path / "parts.db",
                     datasource_factory=lambda: _PackageSource(
                         {"C_0603": "0603", "C_0805": "0805"}),
                     interpreter_factory=no_interpreter,
                     draft_path=tmp_path / "draft.json",
                     cache_path=tmp_path / "cache.json")
    got = app.api_explore({"search": "100n", "package": "0603"})
    assert got["package"] == "0603"
    assert len(got["candidates"]) == 2   # all returned; the page splits


def test_explore_low_confidence_judgment_means_no_filter(tmp_path):
    judge = _FootprintJudge(confidence=0.4)
    app = HendleyApp(db_path=tmp_path / "parts.db",
                     datasource_factory=lambda: _PackageSource(
                         {"C_0603": "0603", "C_0805": "0805"}),
                     interpreter_factory=lambda: judge,
                     draft_path=tmp_path / "draft.json",
                     cache_path=tmp_path / "cache.json")
    got = app.api_explore({"search": "4.7u", "footprint": "C-WEIRD"})
    assert got["package"] is None and len(got["candidates"]) == 2


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
