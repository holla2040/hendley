import pytest

from hendley.app.server import ApiError, HendleyApp
from hendley.knowledge.partsdb import PartsDb, open_db
from hendley.selection_history import component_identity


def line(version="7", *, urn="urn:adsk.eagle:deviceset:123", variant="NPN",
         modified=False, value="40V"):
    return {
        "designators": ["Q2"], "comment": value, "footprint": "SOT23-3",
        "footprintHeadline": "SOT-23 three lead",
        "attributes": {"TYPE": variant},
        "libraryIdentity": {"deviceSetUrn": urn, "libraryVersion": version,
                            "deviceVariant": variant, "packageVariant": "SOT23-3",
                            "locallyModified": modified},
    }


def test_identity_is_exact_only_for_stable_unmodified_same_version():
    q2 = component_identity(line(variant="NPN"))
    q3 = component_identity(line(variant="PNP"))
    newer = component_identity(line("8", variant="NPN"))
    assert q2["exactEligible"]
    assert q2["exactKey"] != q3["exactKey"]  # opposite channel isolation
    assert q2["exactKey"] != newer["exactKey"]
    assert q2["similarityKey"] == newer["similarityKey"]
    missing = component_identity(line(urn=""))
    assert not missing["exactEligible"]
    assert missing["similarityKey"] == q2["similarityKey"]
    assert not component_identity(line(modified=True))["exactEligible"]


def test_seed_replacement_forget_and_reactivation_keep_evidence(tmp_path):
    store = PartsDb(tmp_path / "parts.db")
    keys = component_identity(line())
    args = dict(exact_key=keys["exactKey"], similarity_key=keys["similarityKey"],
                identity=keys["identity"], category="transistors", sieve=[],
                canonical_spec={"kind": "transistor", "value": "NPN",
                                "package": "SOT-23"}, design="a", selected_ref="C1",
                receipt_id="r1", event="mounted")
    first = store.validate_search_seed(phrase="npn 40V", **args)
    second = store.validate_search_seed(phrase="npn 60V", **{**args, "receipt_id": "r2"})
    assert first["id"] == second["id"] and second["phrase"] == "npn 60V"
    assert store.forget_search_seed(first["id"], "b")
    assert store.lookup_search_seeds(keys["exactKey"], keys["similarityKey"])["match"] == "none"
    store.validate_search_seed(phrase="npn 80V", **{**args, "receipt_id": "r3"})
    events = store.conn.execute(
        "SELECT event FROM selection_search_evidence ORDER BY id").fetchall()
    assert [r[0] for r in events] == ["mounted", "mounted", "forgotten", "mounted"]


def test_v4_migration_is_transactional_and_backed_up(tmp_path):
    path = tmp_path / "parts.db"
    conn = open_db(path)
    conn.execute("DROP TABLE selection_search_evidence")
    conn.execute("DROP TABLE selection_search_seeds")
    conn.execute("UPDATE meta SET value='4' WHERE key='schema_version'")
    conn.commit()
    conn.close()
    migrated = open_db(path)
    assert migrated.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] == "5"
    assert path.with_name("parts.db.v4.bak").exists()


def test_validation_requires_live_eligible_selection_and_receipt_expiry(tmp_path, monkeypatch):
    app = HendleyApp(db_path=tmp_path / "parts.db", outdir=tmp_path / "out")
    req = {"design": "board-a", "lines": [line()]}
    app._search_receipts["fresh"] = {
        "created": 100.0, "phrase": "npn 40V", "category": "transistors",
        "sieve": [], "eligible": ["C1"],
        "identityKey": component_identity(line())["exactKey"],
    }
    monkeypatch.setattr("hendley.app.server.time.monotonic", lambda: 101.0)
    got = app.api_search_seed_validate({"receipt": "fresh", "action": "mounted",
        "selectedRef": "C1", "lineIndex": 0, "requirements": req})
    assert got["validated"]
    with pytest.raises(ApiError, match="not eligible"):
        app.api_search_seed_validate({"receipt": "fresh", "action": "alternate",
            "selectedRef": "C2", "lineIndex": 0, "requirements": req})
    monkeypatch.setattr("hendley.app.server.time.monotonic", lambda: 3701.0)
    with pytest.raises(ApiError, match="expired"):
        app.api_search_seed_validate({"receipt": "fresh", "action": "mounted",
            "selectedRef": "C1", "lineIndex": 0, "requirements": req})


def test_mixed_identity_is_suggestion_only():
    mixed = line()
    mixed["libraryIdentity"] = [line()["libraryIdentity"], line("8")["libraryIdentity"]]
    assert not component_identity(mixed)["exactEligible"]
