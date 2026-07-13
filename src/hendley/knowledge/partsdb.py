"""The house-parts database — Hendley's memory of spec → approved-part decisions.

The user designs in *specifications* ("22k, 0603"), not part numbers. This
module persists, across designs, which concrete orderable parts are approved
for each spec — the industry "house parts list", modeled per
``docs/hendley-sourcing-design.md`` and amended by the PRD audit
(``docs/audit-house-parts-bom.md``):

- A **House Part** is the spec-level identity: an opaque integer id, found via
  the unique spec-tuple lookup index. Identity is the id, not the tuple.
- A **Part Choice** is an approved concrete part attached to one House Part,
  with a **rank** (1 = tried first at resolution time) and a **state**
  (``active`` | ``removed``). Multiple choices per House Part form the ranked
  AVL; resolution walks them in rank order and falls back silently.
- Since schema v3 a choice's identity is **provider-neutral**: the preferred
  human identity is ``(mpn, manufacturer)``; provider-specific part numbers
  (the LCSC code, a future PCBWay/distributor ref) live in the
  ``choice_provider_ids`` mapping, one row per provider, together with that
  provider's advisory stock/price cache. Choices recorded LCSC-only (no MPN)
  are legal — the live-verify path backfills ``mpn`` opportunistically.
- The **audit trail** records every decision event (recorded, promoted,
  reranked, removed, superseded) — removal is a state change, never a delete.

A spec key is four exact strings, **supplied canonical by the caller** — this
module does no value normalization or spec parsing on purpose (that judgment
belongs to the engineer/agent/app, not Python):

- ``kind``      — 'resistor', 'capacitor', ... (derived from designator prefix)
- ``value``     — canonical value string, e.g. '22k', '100n'
- ``package``   — e.g. '0603'
- ``qualifier`` — '' for the house default; a part needing more than the house
  standard (e.g. '100V', '1%') gets its own spec key via this field

The advisory cache on each provider mapping is display-only, refreshed after
live verifies. **Never order against it** — stock is always re-verified live
at BOM time.

Older databases migrate automatically on open (v1 → v2 → v3 as needed), each
step in ONE explicit transaction, with a file-copy backup
(``parts.db.v<N>.bak``) written first and the pre-migration tables kept
(``house_parts_v1``, ``part_choices_v2``) for rollback.

DB location: ``--db`` flag / explicit arg → ``HENDLEY_DB`` env var →
``~/.hendley/parts.db`` (user-level: the house-parts list spans designs).
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from ..domain.model import SpecKey

SCHEMA_VERSION = 4

# Interpretation provenance, weakest → strongest. A stronger source
# overwrites a weaker one; never the reverse (a user's confirmation is
# authoritative and is never re-asked or silently replaced by an LLM).
INTERPRETATION_SOURCES = ("deterministic", "llm", "user")

CHOICE_STATES = ("active", "removed")
AUDIT_EVENTS = ("recorded", "promoted", "reranked", "removed", "superseded")

DEFAULT_PROVIDER = "jlcpcb"

_SCHEMA_STATEMENTS = (
    """CREATE TABLE IF NOT EXISTS house_parts (
  id          INTEGER PRIMARY KEY,
  kind        TEXT NOT NULL,
  value       TEXT NOT NULL,
  package     TEXT NOT NULL,
  qualifier   TEXT NOT NULL DEFAULT '',
  description TEXT,
  created_at  TEXT NOT NULL
)""",
    """CREATE UNIQUE INDEX IF NOT EXISTS ux_house_spec
  ON house_parts(kind, value, package, qualifier)""",
    """CREATE TABLE IF NOT EXISTS part_choices (
  id            INTEGER PRIMARY KEY,
  house_part_id INTEGER NOT NULL REFERENCES house_parts(id),
  mpn           TEXT,
  manufacturer  TEXT,
  description   TEXT,
  rank          INTEGER,
  state         TEXT NOT NULL DEFAULT 'active',
  approved_at   TEXT NOT NULL,
  design        TEXT,
  note          TEXT
)""",
    """CREATE UNIQUE INDEX IF NOT EXISTS ux_choice_rank
  ON part_choices(house_part_id, rank) WHERE state = 'active'""",
    """CREATE TABLE IF NOT EXISTS choice_provider_ids (
  choice_id     INTEGER NOT NULL REFERENCES part_choices(id),
  provider      TEXT NOT NULL,
  provider_ref  TEXT NOT NULL,
  last_stock    INTEGER,
  last_price    REAL,
  last_verified_at TEXT,
  PRIMARY KEY (choice_id, provider)
)""",
    """CREATE INDEX IF NOT EXISTS ix_provider_ref
  ON choice_provider_ids(provider, provider_ref)""",
    """CREATE TABLE IF NOT EXISTS part_audit (
  id            INTEGER PRIMARY KEY,
  house_part_id INTEGER NOT NULL REFERENCES house_parts(id),
  event         TEXT NOT NULL,
  provider      TEXT,
  provider_ref  TEXT,
  at            TEXT NOT NULL,
  design        TEXT,
  note          TEXT,
  detail        TEXT
)""",
    """CREATE INDEX IF NOT EXISTS ix_audit_house ON part_audit(house_part_id, id)""",
    """CREATE TABLE IF NOT EXISTS interpretations (
  id          INTEGER PRIMARY KEY,
  scope       TEXT NOT NULL,
  kind_hint   TEXT NOT NULL DEFAULT '',
  raw_value   TEXT NOT NULL DEFAULT '',
  footprint   TEXT NOT NULL DEFAULT '',
  result      TEXT NOT NULL,
  source      TEXT NOT NULL,
  confidence  REAL,
  at          TEXT NOT NULL
)""",
    """CREATE UNIQUE INDEX IF NOT EXISTS ux_interpretation
  ON interpretations(scope, kind_hint, raw_value, footprint)""",
    """CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)""",
)

# The v2 shape, kept verbatim for the v1→v2 migration step (which must build
# exactly the schema the v2→v3 step then upgrades).
_SCHEMA_V2_STATEMENTS = (
    _SCHEMA_STATEMENTS[0],  # house_parts is unchanged across v2/v3
    _SCHEMA_STATEMENTS[1],
    """CREATE TABLE IF NOT EXISTS part_choices (
  id            INTEGER PRIMARY KEY,
  house_part_id INTEGER NOT NULL REFERENCES house_parts(id),
  lcsc_code     TEXT NOT NULL,
  mpn           TEXT,
  manufacturer  TEXT,
  description   TEXT,
  rank          INTEGER,
  state         TEXT NOT NULL DEFAULT 'active',
  approved_at   TEXT NOT NULL,
  design        TEXT,
  note          TEXT,
  last_stock    INTEGER,
  last_price    REAL,
  last_verified_at TEXT
)""",
    """CREATE UNIQUE INDEX IF NOT EXISTS ux_choice_rank
  ON part_choices(house_part_id, rank) WHERE state = 'active'""",
    """CREATE UNIQUE INDEX IF NOT EXISTS ux_choice_code
  ON part_choices(house_part_id, lcsc_code) WHERE state = 'active'""",
    """CREATE TABLE IF NOT EXISTS part_audit (
  id            INTEGER PRIMARY KEY,
  house_part_id INTEGER NOT NULL REFERENCES house_parts(id),
  event         TEXT NOT NULL,
  lcsc_code     TEXT,
  at            TEXT NOT NULL,
  design        TEXT,
  note          TEXT,
  detail        TEXT
)""",
    """CREATE INDEX IF NOT EXISTS ix_audit_house ON part_audit(house_part_id, id)""",
    """CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)""",
)

DEFAULT_DB_PATH = Path.home() / ".hendley" / "parts.db"


def resolve_db_path(path: str | Path | None = None) -> Path:
    """Resolve the DB path: explicit arg → ``HENDLEY_DB`` env → the default."""
    if path:
        return Path(path)
    env = os.environ.get("HENDLEY_DB")
    if env:
        return Path(env)
    return DEFAULT_DB_PATH


def open_db(path: str | Path | None = None) -> sqlite3.Connection:
    """Open (creating dir + schema, migrating older versions) the house-parts DB."""
    db_path = resolve_db_path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    version = _schema_version(conn)
    if version is not None and version < SCHEMA_VERSION:
        _backup(db_path, version)
        if version == 1:
            _run_in_transaction(conn, _migrate_v1_to_v2_body)
            version = 2
        if version == 2:
            _run_in_transaction(conn, _migrate_v2_to_v3_body)
            version = 3
        if version == 3:
            _run_in_transaction(conn, _migrate_v3_to_v4_body)
    else:
        for stmt in _SCHEMA_STATEMENTS:
            conn.execute(stmt)
        conn.execute(
            "INSERT OR IGNORE INTO meta (key, value) VALUES ('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
        conn.commit()
    return conn


def _backup(db_path: Path, version: int) -> Path:
    """File-copy backup before a migration touches anything (cheap, real rollback)."""
    bak = db_path.with_name(f"{db_path.name}.v{version}.bak")
    shutil.copy2(db_path, bak)
    return bak


def _schema_version(conn: sqlite3.Connection) -> int | None:
    """Read the stored schema version; None for a fresh (or pre-meta) database."""
    has_meta = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='meta'"
    ).fetchone()
    if not has_meta:
        return None
    row = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
    return int(row[0]) if row else None


def _run_in_transaction(conn: sqlite3.Connection, body) -> None:
    """Run a migration body in ONE explicit transaction (SQLite DDL is
    transactional). ``executescript`` or autocommitted DDL would commit early,
    and a failure after that would leave a half-migrated DB that re-fails on
    every later open. A failed migration must roll back to the prior version.
    """
    old_isolation = conn.isolation_level
    conn.isolation_level = None  # manual transaction control: no implicit BEGIN/COMMIT
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            body(conn)
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.isolation_level = old_isolation


def _migrate_v1_to_v2_body(conn: sqlite3.Connection) -> None:
    """v1 (single ``current`` part per spec) → v2, per the signed-off design:
    each distinct spec tuple → one House Part; each ``current=1`` row → the
    rank-1 active Part Choice; ``current=0`` rows → ``superseded`` audit
    events only. The v1 table is kept as ``house_parts_v1`` for rollback.
    """
    conn.execute("ALTER TABLE house_parts RENAME TO house_parts_v1")
    for stmt in _SCHEMA_V2_STATEMENTS:
        conn.execute(stmt)
    conn.execute(
        "INSERT INTO house_parts (kind, value, package, qualifier, created_at) "
        "SELECT kind, value, package, qualifier, MIN(picked_at) FROM house_parts_v1 "
        "GROUP BY kind, value, package, qualifier"
    )
    conn.execute(
        "INSERT INTO part_choices (house_part_id, lcsc_code, mpn, manufacturer, "
        "  description, rank, state, approved_at, design, note, "
        "  last_stock, last_price, last_verified_at) "
        "SELECT hp.id, v1.lcsc_code, v1.mpn, v1.manufacturer, v1.description, "
        "  1, 'active', v1.picked_at, v1.design, v1.note, "
        "  v1.last_stock, v1.last_price, v1.last_verified_at "
        "FROM house_parts_v1 v1 JOIN house_parts hp "
        "  ON hp.kind=v1.kind AND hp.value=v1.value AND hp.package=v1.package "
        "  AND hp.qualifier=v1.qualifier "
        "WHERE v1.current = 1"
    )
    rows = conn.execute(
        "SELECT v1.*, hp.id AS house_part_id "
        "FROM house_parts_v1 v1 JOIN house_parts hp "
        "  ON hp.kind=v1.kind AND hp.value=v1.value AND hp.package=v1.package "
        "  AND hp.qualifier=v1.qualifier "
        "WHERE v1.current = 0 ORDER BY v1.id"
    ).fetchall()
    for r in rows:
        detail = {k: r[c] for k, c in
                  (("mpn", "mpn"), ("manufacturer", "manufacturer"),
                   ("description", "description")) if r[c]}
        conn.execute(
            "INSERT INTO part_audit (house_part_id, event, lcsc_code, at, design, "
            "  note, detail) VALUES (?, 'superseded', ?, ?, ?, ?, ?)",
            (r["house_part_id"], r["lcsc_code"], r["picked_at"], r["design"],
             r["note"], json.dumps(detail) if detail else None),
        )
    conn.execute("UPDATE meta SET value='2' WHERE key='schema_version'")


def _migrate_v2_to_v3_body(conn: sqlite3.Connection) -> None:
    """v2 (LCSC code as choice identity) → v3 (provider-neutral identity).

    Every ``lcsc_code`` becomes one ``('jlcpcb', code)`` row in the new
    ``choice_provider_ids`` mapping, carrying the advisory cache columns.
    Choice row ids are preserved. The v2 table is kept as ``part_choices_v2``
    for rollback. The audit table is upgraded in place (``lcsc_code`` →
    ``provider_ref`` + a ``provider`` column backfilled ``'jlcpcb'``).
    """
    conn.execute("ALTER TABLE part_choices RENAME TO part_choices_v2")
    conn.execute("DROP INDEX IF EXISTS ux_choice_rank")
    conn.execute("DROP INDEX IF EXISTS ux_choice_code")
    for stmt in _SCHEMA_STATEMENTS:
        if "part_audit" in stmt:
            continue  # upgraded in place below
        conn.execute(stmt)
    conn.execute(
        "INSERT INTO part_choices (id, house_part_id, mpn, manufacturer, "
        "  description, rank, state, approved_at, design, note) "
        "SELECT id, house_part_id, mpn, manufacturer, description, rank, state, "
        "  approved_at, design, note FROM part_choices_v2"
    )
    conn.execute(
        "INSERT INTO choice_provider_ids (choice_id, provider, provider_ref, "
        "  last_stock, last_price, last_verified_at) "
        "SELECT id, 'jlcpcb', lcsc_code, last_stock, last_price, last_verified_at "
        "FROM part_choices_v2"
    )
    conn.execute("ALTER TABLE part_audit RENAME COLUMN lcsc_code TO provider_ref")
    conn.execute("ALTER TABLE part_audit ADD COLUMN provider TEXT")
    conn.execute(
        "UPDATE part_audit SET provider='jlcpcb' WHERE provider_ref IS NOT NULL")
    conn.execute("UPDATE meta SET value='3' WHERE key='schema_version'")


def _migrate_v3_to_v4_body(conn: sqlite3.Connection) -> None:
    """v3 → v4: the interpretation cache (purely additive)."""
    for stmt in _SCHEMA_STATEMENTS:
        if "interpretations" in stmt or "ux_interpretation" in stmt:
            conn.execute(stmt)
    conn.execute("UPDATE meta SET value='4' WHERE key='schema_version'")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _house_to_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "kind": row["kind"],
        "value": row["value"],
        "package": row["package"],
        "qualifier": row["qualifier"],
        "description": row["description"],
        "createdAt": row["created_at"],
    }


def _provider_rows(conn: sqlite3.Connection, choice_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM choice_provider_ids WHERE choice_id=? ORDER BY provider",
        (choice_id,),
    ).fetchall()


def _choice_to_dict(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
    providers = _provider_rows(conn, row["id"])
    refs = {p["provider"]: p["provider_ref"] for p in providers}
    advisory = {
        p["provider"]: {
            "stock": p["last_stock"],
            "price": p["last_price"],
            "verifiedAt": p["last_verified_at"],
        }
        for p in providers
    }
    jlc = advisory.get(DEFAULT_PROVIDER, {})
    return {
        "id": row["id"],
        "housePartId": row["house_part_id"],
        "mpn": row["mpn"],
        "manufacturer": row["manufacturer"],
        "description": row["description"],
        "rank": row["rank"],
        "state": row["state"],
        "approvedAt": row["approved_at"],
        "design": row["design"],
        "note": row["note"],
        "providerRefs": refs,
        "advisory": advisory,
        # Convenience mirrors of the JLC entry (the daily-driver provider).
        "lcscCode": refs.get(DEFAULT_PROVIDER),
        "lastStock": jlc.get("stock"),
        "lastPrice": jlc.get("price"),
        "lastVerifiedAt": jlc.get("verifiedAt"),
    }


def _audit_to_dict(row: sqlite3.Row) -> dict:
    return {
        "event": row["event"],
        "provider": row["provider"],
        "providerRef": row["provider_ref"],
        "at": row["at"],
        "design": row["design"],
        "note": row["note"],
        "detail": json.loads(row["detail"]) if row["detail"] else None,
    }


def _find_house(
    conn: sqlite3.Connection, kind: str, value: str, package: str, qualifier: str
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM house_parts WHERE kind=? AND value=? AND package=? AND qualifier=?",
        (kind, value, package, qualifier),
    ).fetchone()


def _active_choices(conn: sqlite3.Connection, house_part_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM part_choices WHERE house_part_id=? AND state='active' ORDER BY rank",
        (house_part_id,),
    ).fetchall()


def lookup(
    conn: sqlite3.Connection, kind: str, value: str, package: str, qualifier: str = ""
) -> dict | None:
    """Return the House Part for a spec with its ranked active choices, or None.

    ``choices`` is rank-ordered (rank 1 first — the part resolution tries
    first). A House Part with an empty ``choices`` list exists but has nothing
    approved (the ``no-part-choices`` state).
    """
    house = _find_house(conn, kind, value, package, qualifier)
    if house is None:
        return None
    out = _house_to_dict(house)
    out["choices"] = [_choice_to_dict(conn, r) for r in _active_choices(conn, house["id"])]
    return out


def history(
    conn: sqlite3.Connection, kind: str, value: str, package: str, qualifier: str = ""
) -> list[dict]:
    """The audit trail for a spec, newest first — every decision, never pruned."""
    house = _find_house(conn, kind, value, package, qualifier)
    if house is None:
        return []
    rows = conn.execute(
        "SELECT * FROM part_audit WHERE house_part_id=? ORDER BY id DESC", (house["id"],)
    ).fetchall()
    return [_audit_to_dict(r) for r in rows]


def _shift_ranks(conn: sqlite3.Connection, house_part_id: int, delta: int, rank: int) -> None:
    """Shift active ranks by ``delta``: +1 opens a gap at ``rank`` (ranks >= rank
    move down the list), -1 closes the gap left at ``rank`` (ranks > rank move up).

    Two-step through negative ranks so the unique (house_part_id, rank) index
    never sees a transient collision mid-UPDATE.
    """
    op = ">=" if delta > 0 else ">"
    conn.execute(
        f"UPDATE part_choices SET rank = -(rank + ?) "
        f"WHERE house_part_id=? AND state='active' AND rank {op} ?",
        (delta, house_part_id, rank),
    )
    conn.execute(
        "UPDATE part_choices SET rank = -rank WHERE house_part_id=? AND rank < 0",
        (house_part_id,),
    )


def _require_house(
    conn: sqlite3.Connection, kind: str, value: str, package: str, qualifier: str
) -> sqlite3.Row:
    house = _find_house(conn, kind, value, package, qualifier)
    if house is None:
        raise ValueError(
            f"no house part for spec ({kind}, {value}, {package}, {qualifier!r})")
    return house


def _find_active_choice(
    conn: sqlite3.Connection, house_part_id: int, ref: str
) -> sqlite3.Row | None:
    """Find an active choice by any identity: MPN or an attached provider ref."""
    row = conn.execute(
        "SELECT * FROM part_choices WHERE house_part_id=? AND state='active' AND mpn=?",
        (house_part_id, ref),
    ).fetchone()
    if row is not None:
        return row
    return conn.execute(
        "SELECT c.* FROM part_choices c JOIN choice_provider_ids p ON p.choice_id=c.id "
        "WHERE c.house_part_id=? AND c.state='active' AND p.provider_ref=?",
        (house_part_id, ref),
    ).fetchone()


def _conflicting_ref(conn: sqlite3.Connection, choice_id: int,
                     refs: dict[str, str]) -> bool:
    """True when the choice already carries a DIFFERENT ref for any provider
    being recorded — same MPN, different catalog part."""
    for provider, ref in refs.items():
        row = conn.execute(
            "SELECT provider_ref FROM choice_provider_ids "
            "WHERE choice_id=? AND provider=?",
            (choice_id, provider),
        ).fetchone()
        if row is not None and row["provider_ref"] != ref:
            return True
    return False


def _require_active_choice(
    conn: sqlite3.Connection, house_part_id: int, ref: str
) -> sqlite3.Row:
    choice = _find_active_choice(conn, house_part_id, ref)
    if choice is None:
        raise ValueError(f"{ref} is not an active choice for this spec")
    return choice


def _primary_ref(conn: sqlite3.Connection, choice_id: int) -> tuple[str | None, str | None]:
    """The (provider, ref) recorded for a choice, preferring the default provider."""
    rows = _provider_rows(conn, choice_id)
    for r in rows:
        if r["provider"] == DEFAULT_PROVIDER:
            return r["provider"], r["provider_ref"]
    if rows:
        return rows[0]["provider"], rows[0]["provider_ref"]
    return None, None


def _audit(conn, house_id: int, event: str, provider: str | None, ref: str | None,
           design: str | None, note: str | None, detail: dict | None) -> None:
    conn.execute(
        "INSERT INTO part_audit (house_part_id, event, provider, provider_ref, at, "
        "design, note, detail) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (house_id, event, provider, ref, _now(), design, note,
         json.dumps(detail) if detail else None),
    )


def record(
    conn: sqlite3.Connection,
    kind: str,
    value: str,
    package: str,
    qualifier: str = "",
    *,
    lcsc: str | None = None,
    provider_refs: dict[str, str] | None = None,
    mpn: str | None = None,
    manufacturer: str | None = None,
    description: str | None = None,
    design: str | None = None,
    note: str | None = None,
    rank: int = 1,
) -> dict:
    """Approve a part as a ranked choice for a spec (creating the House Part).

    The part needs at least one identity: an ``mpn`` and/or a provider ref
    (``lcsc`` is the JLC shorthand for ``provider_refs={'jlcpcb': …}``).

    Default ``rank=1`` is promotion: the new choice is tried first and every
    existing active choice shifts down one — **nothing is demoted off the
    list** (removal is explicit, via :func:`remove_choice`). A part already
    active on the AVL (matched by MPN or provider ref) is *moved* to the
    requested rank (metadata and provider refs updated from any non-None
    arguments) rather than duplicated. Out-of-range ranks clamp to the end of
    the list.
    """
    # 'value' may be empty: a general-purpose diode has none, and demanding one
    # only ever gets a fabricated answer (see SpecKey)
    for name, val in (("kind", kind), ("package", package)):
        if not val or not str(val).strip():
            raise ValueError(f"record() requires a non-empty {name!r}")
    refs = dict(provider_refs or {})
    if lcsc:
        if refs.get(DEFAULT_PROVIDER, lcsc) != lcsc:
            raise ValueError(f"'lcsc' {lcsc!r} conflicts with provider_refs {refs!r}")
        refs[DEFAULT_PROVIDER] = lcsc
    if not mpn and not refs:
        raise ValueError("record() needs an identity: an 'mpn' and/or a provider ref")
    if rank < 1:
        raise ValueError(f"record() rank must be >= 1, got {rank}")
    now = _now()
    with conn:  # one transaction: house part + rank shift + choice + audit
        house = _find_house(conn, kind, value, package, qualifier)
        if house is None:
            cur = conn.execute(
                "INSERT INTO house_parts (kind, value, package, qualifier, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (kind, value, package, qualifier, now),
            )
            house_id = cur.lastrowid
        else:
            house_id = house["id"]

        # Identity: a provider ref decides first. An MPN match alone is NOT
        # the same part when the matched row carries a CONFLICTING ref for a
        # provider we're recording — different manufacturers publish the
        # same MPN (e.g. 1N4148WS), and collapsing them overwrites one
        # catalog part with another. A ref-less MPN row still matches, so a
        # later-arriving ref backfills rather than duplicates.
        existing = None
        for ident in list(refs.values()) + ([mpn] if mpn else []):
            cand = _find_active_choice(conn, house_id, ident)
            if cand is None:
                continue
            if refs and _conflicting_ref(conn, cand["id"], refs):
                continue
            existing = cand
            break
        n_active = len(_active_choices(conn, house_id))

        audit_provider, audit_ref = (
            (DEFAULT_PROVIDER, refs[DEFAULT_PROVIDER]) if DEFAULT_PROVIDER in refs
            else (next(iter(refs)), next(iter(refs.values()))) if refs
            else (None, None))

        if existing:
            target = min(rank, n_active)
            old_rank = existing["rank"]
            if target != old_rank:
                conn.execute(
                    "UPDATE part_choices SET rank=NULL WHERE id=?", (existing["id"],)
                )
                _shift_ranks(conn, house_id, -1, old_rank)
                _shift_ranks(conn, house_id, +1, target)
            updates = {k: v for k, v in (("mpn", mpn), ("manufacturer", manufacturer),
                                         ("description", description), ("design", design),
                                         ("note", note)) if v is not None}
            sets = ", ".join(f"{k}=?" for k in updates)
            conn.execute(
                f"UPDATE part_choices SET rank=?{', ' + sets if sets else ''} WHERE id=?",
                (target, *updates.values(), existing["id"]),
            )
            for provider, ref in refs.items():
                conn.execute(
                    "INSERT INTO choice_provider_ids (choice_id, provider, provider_ref) "
                    "VALUES (?, ?, ?) ON CONFLICT(choice_id, provider) "
                    "DO UPDATE SET provider_ref=excluded.provider_ref",
                    (existing["id"], provider, ref),
                )
            if audit_ref is None:
                audit_provider, audit_ref = _primary_ref(conn, existing["id"])
            _audit(conn, house_id, "promoted", audit_provider, audit_ref, design, note,
                   {"fromRank": old_rank, "toRank": target})
            choice_id = existing["id"]
        else:
            target = min(rank, n_active + 1)
            _shift_ranks(conn, house_id, +1, target)
            cur = conn.execute(
                "INSERT INTO part_choices (house_part_id, mpn, manufacturer, "
                "description, rank, state, approved_at, design, note) "
                "VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?)",
                (house_id, mpn, manufacturer, description, target, now, design, note),
            )
            choice_id = cur.lastrowid
            for provider, ref in refs.items():
                conn.execute(
                    "INSERT INTO choice_provider_ids (choice_id, provider, provider_ref) "
                    "VALUES (?, ?, ?)",
                    (choice_id, provider, ref),
                )
            _audit(conn, house_id, "recorded", audit_provider, audit_ref, design, note,
                   {"rank": target, **({"mpn": mpn} if mpn else {})})
    row = conn.execute("SELECT * FROM part_choices WHERE id=?", (choice_id,)).fetchone()
    return _choice_to_dict(conn, row)


def rerank(
    conn: sqlite3.Connection,
    kind: str,
    value: str,
    package: str,
    ref: str,
    new_rank: int,
    qualifier: str = "",
    note: str | None = None,
) -> dict:
    """Move an active choice (matched by MPN or provider ref) to a new rank."""
    if new_rank < 1:
        raise ValueError(f"rerank() new_rank must be >= 1, got {new_rank}")
    with conn:
        house = _require_house(conn, kind, value, package, qualifier)
        choice = _require_active_choice(conn, house["id"], ref)
        n_active = len(_active_choices(conn, house["id"]))
        target = min(new_rank, n_active)
        old_rank = choice["rank"]
        if target != old_rank:
            conn.execute("UPDATE part_choices SET rank=NULL WHERE id=?", (choice["id"],))
            _shift_ranks(conn, house["id"], -1, old_rank)
            _shift_ranks(conn, house["id"], +1, target)
            conn.execute(
                "UPDATE part_choices SET rank=? WHERE id=?", (target, choice["id"])
            )
        provider, pref = _primary_ref(conn, choice["id"])
        _audit(conn, house["id"], "reranked", provider, pref or choice["mpn"], None, note,
               {"fromRank": old_rank, "toRank": target})
    row = conn.execute("SELECT * FROM part_choices WHERE id=?", (choice["id"],)).fetchone()
    return _choice_to_dict(conn, row)


def remove_choice(
    conn: sqlite3.Connection,
    kind: str,
    value: str,
    package: str,
    ref: str,
    qualifier: str = "",
    note: str | None = None,
) -> dict:
    """Remove a choice from the AVL — a state change to ``removed``, never a delete."""
    with conn:
        house = _require_house(conn, kind, value, package, qualifier)
        choice = _require_active_choice(conn, house["id"], ref)
        old_rank = choice["rank"]
        conn.execute(
            "UPDATE part_choices SET state='removed', rank=NULL WHERE id=?",
            (choice["id"],),
        )
        _shift_ranks(conn, house["id"], -1, old_rank)
        provider, pref = _primary_ref(conn, choice["id"])
        _audit(conn, house["id"], "removed", provider, pref or choice["mpn"], None, note,
               {"fromRank": old_rank})
    row = conn.execute("SELECT * FROM part_choices WHERE id=?", (choice["id"],)).fetchone()
    return _choice_to_dict(conn, row)


def list_parts(conn: sqlite3.Connection, kind: str | None = None) -> list[dict]:
    """All House Parts with their ranked active choices, optionally by kind."""
    if kind:
        houses = conn.execute(
            "SELECT * FROM house_parts WHERE kind=? ORDER BY kind, value, package, qualifier",
            (kind,),
        ).fetchall()
    else:
        houses = conn.execute(
            "SELECT * FROM house_parts ORDER BY kind, value, package, qualifier"
        ).fetchall()
    out = []
    for h in houses:
        d = _house_to_dict(h)
        d["choices"] = [_choice_to_dict(conn, r) for r in _active_choices(conn, h["id"])]
        out.append(d)
    return out


def update_verified(
    conn: sqlite3.Connection,
    ref: str,
    stock: int | None,
    price: float | None,
    when: str | None = None,
    *,
    provider: str = DEFAULT_PROVIDER,
    mpn: str | None = None,
    manufacturer: str | None = None,
) -> int:
    """Refresh the advisory cache on every mapping carrying (provider, ref).

    When the live response supplied an ``mpn``/``manufacturer``, backfill it
    onto choices that lack one (LCSC-only records gain their neutral identity
    opportunistically).
    """
    with conn:
        cur = conn.execute(
            "UPDATE choice_provider_ids SET last_stock=?, last_price=?, "
            "last_verified_at=? WHERE provider=? AND provider_ref=?",
            (stock, price, when or _now(), provider, ref),
        )
        if mpn:
            conn.execute(
                "UPDATE part_choices SET mpn=? WHERE mpn IS NULL AND id IN "
                "(SELECT choice_id FROM choice_provider_ids "
                " WHERE provider=? AND provider_ref=?)",
                (mpn, provider, ref),
            )
        if manufacturer:
            conn.execute(
                "UPDATE part_choices SET manufacturer=? WHERE manufacturer IS NULL "
                "AND id IN (SELECT choice_id FROM choice_provider_ids "
                " WHERE provider=? AND provider_ref=?)",
                (manufacturer, provider, ref),
            )
    return cur.rowcount


def get_interpretation(
    conn: sqlite3.Connection, scope: str, kind_hint: str = "",
    raw_value: str = "", footprint: str = "",
) -> dict | None:
    """The cached judgment for an ad-hoc string, or None (never re-judge)."""
    row = conn.execute(
        "SELECT * FROM interpretations WHERE scope=? AND kind_hint=? "
        "AND raw_value=? AND footprint=?",
        (scope, kind_hint, raw_value, footprint),
    ).fetchone()
    if row is None:
        return None
    return {
        "result": json.loads(row["result"]),
        "source": row["source"],
        "confidence": row["confidence"],
        "at": row["at"],
    }


def put_interpretation(
    conn: sqlite3.Connection, scope: str, result: dict, source: str,
    kind_hint: str = "", raw_value: str = "", footprint: str = "",
    confidence: float | None = None,
) -> bool:
    """Cache a judgment. Provenance is ordered: a weaker source never
    overwrites a stronger one (user > llm > deterministic). Returns whether
    the row was written."""
    if source not in INTERPRETATION_SOURCES:
        raise ValueError(f"unknown interpretation source {source!r}")
    with conn:
        existing = conn.execute(
            "SELECT source FROM interpretations WHERE scope=? AND kind_hint=? "
            "AND raw_value=? AND footprint=?",
            (scope, kind_hint, raw_value, footprint),
        ).fetchone()
        if existing is not None:
            if (INTERPRETATION_SOURCES.index(source)
                    < INTERPRETATION_SOURCES.index(existing["source"])):
                return False
            conn.execute(
                "UPDATE interpretations SET result=?, source=?, confidence=?, at=? "
                "WHERE scope=? AND kind_hint=? AND raw_value=? AND footprint=?",
                (json.dumps(result, ensure_ascii=False), source, confidence, _now(),
                 scope, kind_hint, raw_value, footprint),
            )
        else:
            conn.execute(
                "INSERT INTO interpretations (scope, kind_hint, raw_value, footprint, "
                "result, source, confidence, at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (scope, kind_hint, raw_value, footprint,
                 json.dumps(result, ensure_ascii=False), source, confidence, _now()),
            )
    return True


class PartsDb:
    """The SQLite house-parts store behind the KnowledgeStore contract.

    Thin object wrapper over the module functions: same semantics, SpecKey in
    place of the four loose spec strings, one place to hold the connection.
    """

    def __init__(self, path: str | Path | None = None,
                 conn: sqlite3.Connection | None = None):
        self.conn = conn if conn is not None else open_db(path)

    def lookup(self, spec: SpecKey) -> dict | None:
        return lookup(self.conn, spec.kind, spec.value, spec.package, spec.qualifier)

    def record(self, spec: SpecKey, *, mpn: str | None = None,
               manufacturer: str | None = None,
               provider_refs: dict[str, str] | None = None,
               rank: int = 1, description: str | None = None,
               design: str | None = None, note: str | None = None) -> dict:
        return record(self.conn, spec.kind, spec.value, spec.package, spec.qualifier,
                      provider_refs=provider_refs, mpn=mpn, manufacturer=manufacturer,
                      description=description, design=design, note=note, rank=rank)

    def rerank(self, spec: SpecKey, ref: str, rank: int,
               note: str | None = None) -> dict:
        return rerank(self.conn, spec.kind, spec.value, spec.package, ref, rank,
                      qualifier=spec.qualifier, note=note)

    def remove_choice(self, spec: SpecKey, ref: str, note: str | None = None) -> dict:
        return remove_choice(self.conn, spec.kind, spec.value, spec.package, ref,
                             qualifier=spec.qualifier, note=note)

    def history(self, spec: SpecKey) -> list[dict]:
        return history(self.conn, spec.kind, spec.value, spec.package, spec.qualifier)

    def list_parts(self, kind: str | None = None) -> list[dict]:
        return list_parts(self.conn, kind=kind)

    def update_verified(self, ref: str, stock: int | None, price: float | None,
                        when: str | None = None, *,
                        provider: str = DEFAULT_PROVIDER,
                        mpn: str | None = None,
                        manufacturer: str | None = None) -> int:
        return update_verified(self.conn, ref, stock, price, when,
                               provider=provider, mpn=mpn, manufacturer=manufacturer)

    def get_interpretation(self, scope: str, kind_hint: str = "",
                           raw_value: str = "", footprint: str = "") -> dict | None:
        return get_interpretation(self.conn, scope, kind_hint, raw_value, footprint)

    def put_interpretation(self, scope: str, result: dict, source: str,
                           kind_hint: str = "", raw_value: str = "",
                           footprint: str = "",
                           confidence: float | None = None) -> bool:
        return put_interpretation(self.conn, scope, result, source,
                                  kind_hint=kind_hint, raw_value=raw_value,
                                  footprint=footprint, confidence=confidence)
