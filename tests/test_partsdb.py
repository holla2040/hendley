"""Tests for the house-parts database (spec → ranked approved-choices store)."""

import sqlite3

import pytest

from hendley.knowledge.partsdb import (
    _SCHEMA_V2_STATEMENTS,
    SCHEMA_VERSION,
    PartsDb,
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
from hendley.domain.model import SpecKey


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
    assert version == str(SCHEMA_VERSION) == "4"
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
    rec = record(db, "resistor", "22k", "0603", lcsc="C31850",
                 mpn="0603WAF2202T5E", manufacturer="UNI-ROYAL", design="comet")
    assert rec["rank"] == 1 and rec["state"] == "active" and rec["lcscCode"] == "C31850"
    assert rec["providerRefs"] == {"jlcpcb": "C31850"}
    hit = lookup(db, "resistor", "22k", "0603")
    assert hit["id"] and hit["kind"] == "resistor"
    assert codes(hit) == ["C31850"]
    choice = hit["choices"][0]
    assert choice["mpn"] == "0603WAF2202T5E" and choice["design"] == "comet"
    assert choice["approvedAt"]


def test_record_promotes_and_keeps_old_choice_on_avl(db):
    record(db, "resistor", "22k", "0603", lcsc="C31850")
    record(db, "resistor", "22k", "0603", lcsc="C4190", note="C31850 out of stock")
    hit = lookup(db, "resistor", "22k", "0603")
    # new pick is rank 1; the old pick stays APPROVED at rank 2 (the AVL) —
    # it is not demoted off the list (that would be remove_choice()).
    assert codes(hit) == ["C4190", "C31850"]
    events = history(db, "resistor", "22k", "0603")
    assert [e["event"] for e in events] == ["recorded", "recorded"]  # newest first
    assert events[0]["providerRef"] == "C4190"


def test_record_existing_code_moves_it_not_duplicates(db):
    record(db, "resistor", "22k", "0603", lcsc="C31850")
    record(db, "resistor", "22k", "0603", lcsc="C4190")
    record(db, "resistor", "22k", "0603", lcsc="C31850", mpn="0603WAF2202T5E")
    hit = lookup(db, "resistor", "22k", "0603")
    assert codes(hit) == ["C31850", "C4190"]  # moved to rank 1, no duplicate
    assert hit["choices"][0]["mpn"] == "0603WAF2202T5E"  # metadata updated
    assert history(db, "resistor", "22k", "0603")[0]["event"] == "promoted"


def test_record_matches_existing_by_mpn_too(db):
    record(db, "resistor", "22k", "0603", mpn="0603WAF2202T5E")  # MPN-only approve
    record(db, "resistor", "22k", "0603", mpn="0603WAF2202T5E", lcsc="C31850")
    hit = lookup(db, "resistor", "22k", "0603")
    assert len(hit["choices"]) == 1  # matched, not duplicated
    assert hit["choices"][0]["providerRefs"] == {"jlcpcb": "C31850"}  # ref attached


def test_record_needs_some_identity(db):
    with pytest.raises(ValueError, match="identity"):
        record(db, "resistor", "22k", "0603")


def test_record_rank_appends_below_and_clamps(db):
    record(db, "resistor", "22k", "0603", lcsc="C31850")
    record(db, "resistor", "22k", "0603", lcsc="C4190", rank=2)
    record(db, "resistor", "22k", "0603", lcsc="C9999", rank=99)  # clamps to end
    assert codes(lookup(db, "resistor", "22k", "0603")) == ["C31850", "C4190", "C9999"]
    with pytest.raises(ValueError):
        record(db, "resistor", "22k", "0603", lcsc="C1", rank=0)


def test_rerank_moves_and_renumbers(db):
    for code in ("C1", "C2", "C3"):
        record(db, "resistor", "22k", "0603", lcsc=code, rank=99)  # append C1,C2,C3
    rec = rerank(db, "resistor", "22k", "0603", "C3", 1)
    assert rec["rank"] == 1
    hit = lookup(db, "resistor", "22k", "0603")
    assert codes(hit) == ["C3", "C1", "C2"]
    assert [c["rank"] for c in hit["choices"]] == [1, 2, 3]  # contiguous
    assert history(db, "resistor", "22k", "0603")[0]["event"] == "reranked"
    with pytest.raises(ValueError):
        rerank(db, "resistor", "22k", "0603", "C9999", 1)  # not on the AVL


def test_remove_choice_is_state_change_not_delete(db):
    record(db, "resistor", "22k", "0603", lcsc="C31850")
    record(db, "resistor", "22k", "0603", lcsc="C4190")
    removed = remove_choice(db, "resistor", "22k", "0603", "C4190", note="EOL")
    assert removed["state"] == "removed" and removed["rank"] is None
    hit = lookup(db, "resistor", "22k", "0603")
    assert codes(hit) == ["C31850"] and hit["choices"][0]["rank"] == 1  # gap closed
    # the row survives in the table (never deleted)
    kept = db.execute(
        "SELECT c.state FROM part_choices c JOIN choice_provider_ids p "
        "ON p.choice_id=c.id WHERE p.provider_ref='C4190'").fetchone()
    assert kept["state"] == "removed"
    assert history(db, "resistor", "22k", "0603")[0]["event"] == "removed"


def test_qualifier_forms_a_distinct_spec_key(db):
    record(db, "capacitor", "100n", "0603", lcsc="C14663")  # house default
    record(db, "capacitor", "100n", "0603", qualifier="100V", lcsc="C77102")
    assert codes(lookup(db, "capacitor", "100n", "0603")) == ["C14663"]
    assert codes(lookup(db, "capacitor", "100n", "0603", qualifier="100V")) == ["C77102"]
    # no cross-key contamination: each audit trail is its own
    assert len(history(db, "capacitor", "100n", "0603")) == 1


def test_record_rejects_empty_key_fields(db):
    with pytest.raises(ValueError):
        record(db, "", "22k", "0603", lcsc="C31850")


def test_list_parts_nested_choices_and_kind_filter(db):
    record(db, "resistor", "22k", "0603", lcsc="C31850")
    record(db, "resistor", "22k", "0603", lcsc="C4190")
    record(db, "capacitor", "100n", "0603", lcsc="C14663")
    parts = list_parts(db)
    assert [p["kind"] for p in parts] == ["capacitor", "resistor"]  # sorted by kind
    assert codes(parts[1]) == ["C4190", "C31850"]  # full AVL, rank order
    assert [p["kind"] for p in list_parts(db, kind="resistor")] == ["resistor"]


def test_update_verified_refreshes_cache_and_backfills_identity(db):
    record(db, "resistor", "22k", "0603", lcsc="C31850")
    n = update_verified(db, "C31850", stock=52000, price=0.0018,
                        when="2026-07-09T00:00:00+00:00", mpn="0603WAF2202T5E")
    assert n == 1
    choice = lookup(db, "resistor", "22k", "0603")["choices"][0]
    assert choice["lastStock"] == 52000 and choice["lastPrice"] == 0.0018
    assert choice["lastVerifiedAt"] == "2026-07-09T00:00:00+00:00"
    assert choice["advisory"]["jlcpcb"]["stock"] == 52000
    assert choice["mpn"] == "0603WAF2202T5E"  # backfilled onto the NULL identity
    assert update_verified(db, "C9999", stock=1, price=None) == 0  # unknown: no rows


def test_update_verified_never_overwrites_recorded_identity(db):
    record(db, "resistor", "22k", "0603", lcsc="C31850", mpn="DELIBERATE-MPN")
    update_verified(db, "C31850", stock=1, price=None, mpn="CATALOG-MPN")
    assert lookup(db, "resistor", "22k", "0603")["choices"][0]["mpn"] == "DELIBERATE-MPN"


def test_partsdb_class_wraps_module_functions(tmp_path):
    store = PartsDb(tmp_path / "parts.db")
    spec = SpecKey("resistor", "22k", "0603")
    store.record(spec, provider_refs={"jlcpcb": "C31850"}, mpn="0603WAF2202T5E")
    hit = store.lookup(spec)
    assert codes(hit) == ["C31850"]
    store.rerank(spec, "C31850", 1)
    assert store.history(spec)[0]["event"] == "reranked"
    assert store.update_verified("C31850", 100, 0.002) == 1
    store.remove_choice(spec, "C31850", note="test")
    assert store.lookup(spec)["choices"] == []


# ---------------------------------------------------------------------------
# v1 → v2 → v3 migration
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


@pytest.fixture
def v2_db_path(tmp_path):
    """A v2 database built from the module's own v2 DDL: two ranked choices."""
    path = tmp_path / "v2.db"
    conn = sqlite3.connect(path)
    for stmt in _SCHEMA_V2_STATEMENTS:
        conn.execute(stmt)
    conn.execute("INSERT INTO meta VALUES ('schema_version', '2')")
    conn.execute(
        "INSERT INTO house_parts (id, kind, value, package, qualifier, created_at) "
        "VALUES (1, 'resistor', '22k', '0603', '', '2026-05-01T00:00:00+00:00')")
    conn.execute(
        "INSERT INTO part_choices (id, house_part_id, lcsc_code, mpn, rank, state, "
        "approved_at, last_stock, last_price, last_verified_at) VALUES "
        "(1, 1, 'C4190', 'RC0603FR-0722KL', 1, 'active', "
        "'2026-06-15T00:00:00+00:00', 52000, 0.0018, '2026-07-01T00:00:00+00:00')")
    conn.execute(
        "INSERT INTO part_choices (id, house_part_id, lcsc_code, rank, state, "
        "approved_at) VALUES (2, 1, 'C31850', 2, 'active', '2026-05-01T00:00:00+00:00')")
    conn.execute(
        "INSERT INTO part_audit (house_part_id, event, lcsc_code, at) "
        "VALUES (1, 'recorded', 'C4190', '2026-06-15T00:00:00+00:00')")
    conn.commit()
    conn.close()
    return path


def test_migration_v1_chains_to_v4(v1_db_path):
    conn = open_db(v1_db_path)
    version = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
    assert version == "4"

    # current=1 rows became the sole rank-1 active choice per spec
    hit = lookup(conn, "resistor", "22k", "0603")
    assert codes(hit) == ["C4190"]  # ONLY the current part — history NOT auto-approved
    assert hit["choices"][0]["rank"] == 1
    assert hit["choices"][0]["approvedAt"] == "2026-06-15T00:00:00+00:00"  # preserved
    assert hit["choices"][0]["lastStock"] == 1000  # advisory cache carried over
    assert hit["choices"][0]["providerRefs"] == {"jlcpcb": "C4190"}

    # demoted history row → audit only
    events = history(conn, "resistor", "22k", "0603")
    assert len(events) == 1 and events[0]["event"] == "superseded"
    assert events[0]["providerRef"] == "C31850"
    assert events[0]["provider"] == "jlcpcb"
    assert events[0]["detail"]["mpn"] == "0603WAF2202T5E"

    # qualifier keys migrate as distinct House Parts
    assert codes(lookup(conn, "capacitor", "100n", "0603"))[0] == "C14663"
    assert codes(lookup(conn, "capacitor", "100n", "0603", qualifier="100V"))[0] == "C77102"

    # pre-migration tables kept for rollback; backup file written first
    assert conn.execute("SELECT COUNT(*) FROM house_parts_v1").fetchone()[0] == 4
    assert conn.execute("SELECT COUNT(*) FROM part_choices_v2").fetchone()[0] == 3
    assert v1_db_path.with_name("v1.db.v1.bak").exists()
    conn.close()


def test_migration_v2_chains_to_v4(v2_db_path):
    conn = open_db(v2_db_path)
    version = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
    assert version == "4"

    hit = lookup(conn, "resistor", "22k", "0603")
    assert codes(hit) == ["C4190", "C31850"]  # rank order preserved
    first = hit["choices"][0]
    assert first["providerRefs"] == {"jlcpcb": "C4190"}
    assert first["lastStock"] == 52000 and first["lastPrice"] == 0.0018  # cache moved
    assert first["mpn"] == "RC0603FR-0722KL"

    events = history(conn, "resistor", "22k", "0603")
    assert events[0]["providerRef"] == "C4190" and events[0]["provider"] == "jlcpcb"

    assert conn.execute("SELECT COUNT(*) FROM part_choices_v2").fetchone()[0] == 2
    assert v2_db_path.with_name("v2.db.v2.bak").exists()

    # new semantics work post-migration
    record(conn, "resistor", "22k", "0603", lcsc="C9999", rank=99)
    assert codes(lookup(conn, "resistor", "22k", "0603")) == ["C4190", "C31850", "C9999"]
    conn.close()


def test_migration_is_idempotent(v1_db_path):
    open_db(v1_db_path).close()
    conn = open_db(v1_db_path)  # second open must not re-migrate or error
    assert codes(lookup(conn, "resistor", "22k", "0603")) == ["C4190"]
    assert len(history(conn, "resistor", "22k", "0603")) == 1
    conn.close()


def test_failed_migration_rolls_back_to_pristine_v2(v2_db_path, monkeypatch):
    """A mid-migration failure must leave the v2 DB untouched and retryable.

    Without single-transaction DDL+DML, the table rename commits early and a
    later failure bricks the DB (every open re-fails on the rename). Force a
    failure inside the migration body and prove the rollback + clean retry.
    """
    import hendley.knowledge.partsdb as partsdb

    real_body = partsdb._migrate_v2_to_v3_body

    def exploding_body(conn):
        real_body(conn)
        raise RuntimeError("simulated crash after all migration work")

    monkeypatch.setattr(partsdb, "_migrate_v2_to_v3_body", exploding_body)
    with pytest.raises(RuntimeError):
        open_db(v2_db_path)

    # rollback left a pristine v2 database: still version 2, original tables only
    conn = sqlite3.connect(v2_db_path)
    version = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
    assert version == "2"
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert "part_choices" in tables and "part_choices_v2" not in tables
    assert "choice_provider_ids" not in tables
    conn.close()

    # and the migration simply succeeds on the next open
    monkeypatch.setattr(partsdb, "_migrate_v2_to_v3_body", real_body)
    conn = open_db(v2_db_path)
    assert codes(lookup(conn, "resistor", "22k", "0603")) == ["C4190", "C31850"]
    conn.close()


# ---------------------------------------------------------------------------
# interpretation cache (v4)
# ---------------------------------------------------------------------------

def test_interpretation_cache_roundtrip(db):
    from hendley.knowledge.partsdb import get_interpretation, put_interpretation

    assert get_interpretation(db, "part", "C", "47u/50V", "C-E-5") is None
    result = {"spec": {"kind": "capacitor", "value": "47u", "package": "C-E-5",
                       "qualifier": "50V"},
              "envelope": {"mount": "tht", "maxDiaMm": 10}}
    assert put_interpretation(db, "part", result, "llm", kind_hint="C",
                              raw_value="47u/50V", footprint="C-E-5",
                              confidence=0.9)
    hit = get_interpretation(db, "part", "C", "47u/50V", "C-E-5")
    assert hit["result"] == result and hit["source"] == "llm"
    assert hit["confidence"] == 0.9 and hit["at"]


def test_interpretation_user_beats_llm_never_reverse(db):
    from hendley.knowledge.partsdb import get_interpretation, put_interpretation

    key = dict(kind_hint="C", raw_value="47u/50V", footprint="C-E-5")
    put_interpretation(db, "part", {"spec": None, "note": "llm guess"}, "llm", **key)
    # user overrides llm
    assert put_interpretation(db, "part", {"spec": None, "note": "user says"},
                              "user", **key)
    assert get_interpretation(db, "part", **key)["source"] == "user"
    # llm can NEVER overwrite the user's answer
    assert not put_interpretation(db, "part", {"spec": None, "note": "llm again"},
                                  "llm", **key)
    hit = get_interpretation(db, "part", **key)
    assert hit["source"] == "user" and hit["result"]["note"] == "user says"


def test_interpretation_bad_source_rejected(db):
    from hendley.knowledge.partsdb import put_interpretation

    with pytest.raises(ValueError, match="source"):
        put_interpretation(db, "part", {}, "guess")


def test_migration_v3_to_v4_adds_cache(tmp_path, v2_db_path):
    # a DB opened pre-v4 chains up and gains the interpretations table
    conn = open_db(v2_db_path)
    from hendley.knowledge.partsdb import get_interpretation, put_interpretation

    put_interpretation(conn, "footprint", {"envelope": {"maxDiaMm": 10}},
                       "user", footprint="C-E-5")
    assert get_interpretation(conn, "footprint",
                              footprint="C-E-5")["source"] == "user"
    assert v2_db_path.with_name("v2.db.v2.bak").exists()
    conn.close()


def test_same_mpn_different_codes_are_distinct_choices(db):
    """Different manufacturers publish the SAME MPN (e.g. 1N4148WS): a bare
    MPN match must never collapse two catalog parts onto one row — that
    overwrote the first pick's LCSC code (the checkbox-Update bug)."""
    record(db, "diode", "1N4148WS", "SOD-323", lcsc="C5249630",
           mpn="1N4148WS", rank=1)
    record(db, "diode", "1N4148WS", "SOD-323", lcsc="C437156",
           mpn="1N4148WS", rank=999)
    record(db, "diode", "1N4148WS", "SOD-323", lcsc="C909968",
           mpn="1N4148WS", rank=999)
    hit = lookup(db, "diode", "1N4148WS", "SOD-323")
    assert codes(hit) == ["C5249630", "C437156", "C909968"]
    assert [c["rank"] for c in hit["choices"]] == [1, 2, 3]

    # re-recording the SAME code is still a move, never a duplicate
    record(db, "diode", "1N4148WS", "SOD-323", lcsc="C909968",
           mpn="1N4148WS", rank=1)
    hit = lookup(db, "diode", "1N4148WS", "SOD-323")
    assert codes(hit) == ["C909968", "C5249630", "C437156"]


def test_mpn_only_row_still_backfills_a_late_ref(db):
    record(db, "diode", "1N4148WS", "SOD-323", mpn="1N4148WS", rank=1)
    record(db, "diode", "1N4148WS", "SOD-323", lcsc="C5249630",
           mpn="1N4148WS", rank=1)
    hit = lookup(db, "diode", "1N4148WS", "SOD-323")
    assert codes(hit) == ["C5249630"]   # one row, ref backfilled
    assert len(hit["choices"]) == 1
