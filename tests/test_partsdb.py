"""Tests for the house-parts database (spec → ranked approved-choices store)."""

import sqlite3

import pytest

from hendley.partsdb import (
    SCHEMA_VERSION,
    history,
    list_parts,
    lookup,
    open_db,
    record,
    remove_choice,
    rerank,
    resolve_db_path,
    update_verified,
)


@pytest.fixture
def db(tmp_path):
    conn = open_db(tmp_path / "parts.db")
    yield conn
    conn.close()


def codes(house: dict) -> list[str]:
    """Rank-ordered active LCSC codes of a lookup()/list_parts() house dict."""
    return [c["lcscCode"] for c in house["choices"]]


def test_open_db_creates_dir_and_schema(tmp_path):
    path = tmp_path / "nested" / "dir" / "parts.db"
    conn = open_db(path)
    assert path.exists()
    version = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
    assert version == str(SCHEMA_VERSION) == "2"
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
    assert rec["rank"] == 1 and rec["state"] == "active" and rec["lcscCode"] == "C31850"
    hit = lookup(db, "resistor", "22k", "0603")
    assert hit["id"] and hit["kind"] == "resistor"
    assert codes(hit) == ["C31850"]
    choice = hit["choices"][0]
    assert choice["mpn"] == "0603WAF2202T5E" and choice["design"] == "comet"
    assert choice["approvedAt"]


def test_record_promotes_and_keeps_old_choice_on_avl(db):
    record(db, "resistor", "22k", "0603", "C31850")
    record(db, "resistor", "22k", "0603", "C4190", note="C31850 out of stock")
    hit = lookup(db, "resistor", "22k", "0603")
    # new pick is rank 1; the old pick stays APPROVED at rank 2 (the AVL) —
    # it is not demoted off the list (that would be remove_choice()).
    assert codes(hit) == ["C4190", "C31850"]
    events = history(db, "resistor", "22k", "0603")
    assert [e["event"] for e in events] == ["recorded", "recorded"]  # newest first
    assert events[0]["lcscCode"] == "C4190"


def test_record_existing_code_moves_it_not_duplicates(db):
    record(db, "resistor", "22k", "0603", "C31850")
    record(db, "resistor", "22k", "0603", "C4190")
    record(db, "resistor", "22k", "0603", "C31850", mpn="0603WAF2202T5E")  # re-approve
    hit = lookup(db, "resistor", "22k", "0603")
    assert codes(hit) == ["C31850", "C4190"]  # moved to rank 1, no duplicate
    assert hit["choices"][0]["mpn"] == "0603WAF2202T5E"  # metadata updated
    assert history(db, "resistor", "22k", "0603")[0]["event"] == "promoted"


def test_record_rank_appends_below_and_clamps(db):
    record(db, "resistor", "22k", "0603", "C31850")
    record(db, "resistor", "22k", "0603", "C4190", rank=2)  # deliberate rank-2 approve
    record(db, "resistor", "22k", "0603", "C9999", rank=99)  # clamps to end
    assert codes(lookup(db, "resistor", "22k", "0603")) == ["C31850", "C4190", "C9999"]
    with pytest.raises(ValueError):
        record(db, "resistor", "22k", "0603", "C1", rank=0)


def test_rerank_moves_and_renumbers(db):
    for code in ("C1", "C2", "C3"):
        record(db, "resistor", "22k", "0603", code, rank=99)  # append order C1,C2,C3
    rec = rerank(db, "resistor", "22k", "0603", "C3", 1)
    assert rec["rank"] == 1
    hit = lookup(db, "resistor", "22k", "0603")
    assert codes(hit) == ["C3", "C1", "C2"]
    assert [c["rank"] for c in hit["choices"]] == [1, 2, 3]  # contiguous
    assert history(db, "resistor", "22k", "0603")[0]["event"] == "reranked"
    with pytest.raises(ValueError):
        rerank(db, "resistor", "22k", "0603", "C9999", 1)  # not on the AVL


def test_remove_choice_is_state_change_not_delete(db):
    record(db, "resistor", "22k", "0603", "C31850")
    record(db, "resistor", "22k", "0603", "C4190")
    removed = remove_choice(db, "resistor", "22k", "0603", "C4190", note="EOL")
    assert removed["state"] == "removed" and removed["rank"] is None
    hit = lookup(db, "resistor", "22k", "0603")
    assert codes(hit) == ["C31850"] and hit["choices"][0]["rank"] == 1  # gap closed
    # the row survives in the table (never deleted)
    kept = db.execute("SELECT state FROM part_choices WHERE lcsc_code='C4190'").fetchone()
    assert kept["state"] == "removed"
    assert history(db, "resistor", "22k", "0603")[0]["event"] == "removed"


def test_qualifier_forms_a_distinct_spec_key(db):
    record(db, "capacitor", "100n", "0603", "C14663")  # house default
    record(db, "capacitor", "100n", "0603", "C77102", qualifier="100V")
    assert codes(lookup(db, "capacitor", "100n", "0603")) == ["C14663"]
    assert codes(lookup(db, "capacitor", "100n", "0603", qualifier="100V")) == ["C77102"]
    # no cross-key contamination: each audit trail is its own
    assert len(history(db, "capacitor", "100n", "0603")) == 1


def test_record_rejects_empty_key_fields(db):
    with pytest.raises(ValueError):
        record(db, "", "22k", "0603", "C31850")
    with pytest.raises(ValueError):
        record(db, "resistor", "22k", "0603", "  ")


def test_list_parts_nested_choices_and_kind_filter(db):
    record(db, "resistor", "22k", "0603", "C31850")
    record(db, "resistor", "22k", "0603", "C4190")
    record(db, "capacitor", "100n", "0603", "C14663")
    parts = list_parts(db)
    assert [p["kind"] for p in parts] == ["capacitor", "resistor"]  # sorted by kind
    assert codes(parts[1]) == ["C4190", "C31850"]  # full AVL, rank order
    assert [p["kind"] for p in list_parts(db, kind="resistor")] == ["resistor"]


def test_update_verified_refreshes_cache_columns(db):
    record(db, "resistor", "22k", "0603", "C31850")
    n = update_verified(db, "C31850", stock=52000, price=0.0018, when="2026-07-09T00:00:00+00:00")
    assert n == 1
    choice = lookup(db, "resistor", "22k", "0603")["choices"][0]
    assert choice["lastStock"] == 52000 and choice["lastPrice"] == 0.0018
    assert choice["lastVerifiedAt"] == "2026-07-09T00:00:00+00:00"
    assert update_verified(db, "C9999", stock=1, price=None) == 0  # unknown code: no rows


# ---------------------------------------------------------------------------
# v1 → v2 migration
# ---------------------------------------------------------------------------

_V1_SCHEMA = """
CREATE TABLE house_parts (
  id          INTEGER PRIMARY KEY,
  kind        TEXT NOT NULL,
  value       TEXT NOT NULL,
  package     TEXT NOT NULL,
  qualifier   TEXT NOT NULL DEFAULT '',
  lcsc_code   TEXT NOT NULL,
  mpn         TEXT,
  manufacturer TEXT,
  description TEXT,
  current     INTEGER NOT NULL DEFAULT 1,
  picked_at   TEXT NOT NULL,
  design      TEXT,
  note        TEXT,
  last_stock  INTEGER,
  last_price  REAL,
  last_verified_at TEXT
);
CREATE UNIQUE INDEX ux_house_current
  ON house_parts(kind, value, package, qualifier) WHERE current = 1;
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
INSERT INTO meta VALUES ('schema_version', '1');
"""


@pytest.fixture
def v1_db_path(tmp_path):
    """A realistic v1 database: one spec with history, one without, a qualifier."""
    path = tmp_path / "v1.db"
    conn = sqlite3.connect(path)
    conn.executescript(_V1_SCHEMA)
    rows = [
        # (kind, value, package, qualifier, code, mpn, current, picked_at, note)
        ("resistor", "22k", "0603", "", "C31850", "0603WAF2202T5E", 0,
         "2026-05-01T00:00:00+00:00", "original pick"),
        ("resistor", "22k", "0603", "", "C4190", "RC0603FR-0722KL", 1,
         "2026-06-15T00:00:00+00:00", "C31850 went out of stock"),
        ("capacitor", "100n", "0603", "", "C14663", None, 1,
         "2026-05-20T00:00:00+00:00", None),
        ("capacitor", "100n", "0603", "100V", "C77102", None, 1,
         "2026-05-21T00:00:00+00:00", None),
    ]
    for kind, value, package, qual, code, mpn, cur, at, note in rows:
        conn.execute(
            "INSERT INTO house_parts (kind, value, package, qualifier, lcsc_code, mpn, "
            "current, picked_at, note, last_stock) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (kind, value, package, qual, code, mpn, cur, at, note, 1000),
        )
    conn.commit()
    conn.close()
    return path


def test_migration_v1_to_v2(v1_db_path):
    conn = open_db(v1_db_path)
    version = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
    assert version == "2"

    # current=1 rows became the sole rank-1 active choice per spec
    hit = lookup(conn, "resistor", "22k", "0603")
    assert codes(hit) == ["C4190"]  # ONLY the current part — history NOT auto-approved
    assert hit["choices"][0]["rank"] == 1
    assert hit["choices"][0]["approvedAt"] == "2026-06-15T00:00:00+00:00"  # preserved
    assert hit["choices"][0]["lastStock"] == 1000  # advisory cache carried over

    # demoted history row → audit only
    events = history(conn, "resistor", "22k", "0603")
    assert len(events) == 1 and events[0]["event"] == "superseded"
    assert events[0]["lcscCode"] == "C31850"
    assert events[0]["detail"]["mpn"] == "0603WAF2202T5E"

    # qualifier keys migrate as distinct House Parts
    assert codes(lookup(conn, "capacitor", "100n", "0603"))[0] == "C14663"
    assert codes(lookup(conn, "capacitor", "100n", "0603", qualifier="100V"))[0] == "C77102"

    # v1 table kept as rollback backup
    backup = conn.execute("SELECT COUNT(*) FROM house_parts_v1").fetchone()[0]
    assert backup == 4
    conn.close()


def test_migration_is_idempotent(v1_db_path):
    open_db(v1_db_path).close()
    conn = open_db(v1_db_path)  # second open must not re-migrate or error
    assert codes(lookup(conn, "resistor", "22k", "0603")) == ["C4190"]
    assert len(history(conn, "resistor", "22k", "0603")) == 1
    conn.close()


def test_migrated_db_supports_new_semantics(v1_db_path):
    conn = open_db(v1_db_path)
    record(conn, "resistor", "22k", "0603", "C31850", rank=2)  # deliberate re-approval
    assert codes(lookup(conn, "resistor", "22k", "0603")) == ["C4190", "C31850"]
    conn.close()
