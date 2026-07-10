"""Tests for the house-parts database (spec → chosen-part store)."""

import pytest

from hendley.partsdb import (
    history,
    list_parts,
    lookup,
    open_db,
    record,
    resolve_db_path,
    update_verified,
)


@pytest.fixture
def db(tmp_path):
    conn = open_db(tmp_path / "parts.db")
    yield conn
    conn.close()


def test_open_db_creates_dir_and_schema(tmp_path):
    path = tmp_path / "nested" / "dir" / "parts.db"
    conn = open_db(path)
    assert path.exists()
    version = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
    assert version == "1"
    conn.close()


def test_resolve_db_path_order(tmp_path, monkeypatch):
    monkeypatch.setenv("HENDLEY_DB", str(tmp_path / "env.db"))
    assert resolve_db_path(tmp_path / "arg.db") == tmp_path / "arg.db"  # explicit wins
    assert resolve_db_path() == tmp_path / "env.db"  # then the env var
    monkeypatch.delenv("HENDLEY_DB")
    assert resolve_db_path().name == "parts.db"  # then the user-level default


def test_lookup_miss_returns_none(db):
    assert lookup(db, "resistor", "22k", "0603") is None


def test_record_then_lookup(db):
    rec = record(db, "resistor", "22k", "0603", "C31850",
                 mpn="0603WAF2202T5E", manufacturer="UNI-ROYAL", design="comet")
    assert rec["current"] is True and rec["lcscCode"] == "C31850"
    hit = lookup(db, "resistor", "22k", "0603")
    assert hit["lcscCode"] == "C31850" and hit["mpn"] == "0603WAF2202T5E"
    assert hit["design"] == "comet" and hit["pickedAt"]


def test_record_promotes_and_keeps_history(db):
    record(db, "resistor", "22k", "0603", "C31850")
    record(db, "resistor", "22k", "0603", "C4190", note="C31850 out of stock")
    hit = lookup(db, "resistor", "22k", "0603")
    assert hit["lcscCode"] == "C4190"  # new pick is the house part
    past = history(db, "resistor", "22k", "0603")
    assert [p["lcscCode"] for p in past] == ["C31850"]  # old pick demoted, not deleted
    assert past[0]["current"] is False


def test_qualifier_forms_a_distinct_spec_key(db):
    record(db, "capacitor", "100n", "0603", "C14663")  # house default
    record(db, "capacitor", "100n", "0603", "C77102", qualifier="100V")
    assert lookup(db, "capacitor", "100n", "0603")["lcscCode"] == "C14663"
    assert lookup(db, "capacitor", "100n", "0603", qualifier="100V")["lcscCode"] == "C77102"
    assert history(db, "capacitor", "100n", "0603") == []  # no cross-key demotion


def test_record_rejects_empty_key_fields(db):
    with pytest.raises(ValueError):
        record(db, "", "22k", "0603", "C31850")
    with pytest.raises(ValueError):
        record(db, "resistor", "22k", "0603", "  ")


def test_list_parts_current_only_and_kind_filter(db):
    record(db, "resistor", "22k", "0603", "C31850")
    record(db, "resistor", "22k", "0603", "C4190")  # demotes the first
    record(db, "capacitor", "100n", "0603", "C14663")
    all_current = list_parts(db)
    assert [p["lcscCode"] for p in all_current] == ["C14663", "C4190"]  # sorted by kind
    assert [p["kind"] for p in list_parts(db, kind="resistor")] == ["resistor"]


def test_update_verified_refreshes_cache_columns(db):
    record(db, "resistor", "22k", "0603", "C31850")
    n = update_verified(db, "C31850", stock=52000, price=0.0018, when="2026-07-09T00:00:00+00:00")
    assert n == 1
    hit = lookup(db, "resistor", "22k", "0603")
    assert hit["lastStock"] == 52000 and hit["lastPrice"] == 0.0018
    assert hit["lastVerifiedAt"] == "2026-07-09T00:00:00+00:00"
    assert update_verified(db, "C9999", stock=1, price=None) == 0  # unknown code: no rows
