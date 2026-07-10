"""The house-parts database — Hendley's memory of spec → approved-part decisions.

The user designs in *specifications* ("22k, 0603"), not part numbers. This
module persists, across designs, which concrete orderable parts (LCSC code,
MPN, manufacturer) are approved for each spec — the industry "house parts
list", modeled per ``docs/hendley-sourcing-design.md``:

- A **House Part** is the spec-level identity: an opaque integer id, found via
  the unique spec-tuple lookup index. Identity is the id, not the tuple.
- A **Part Choice** is an approved concrete part attached to one House Part,
  with a **rank** (1 = tried first at resolution time) and a **state**
  (``active`` | ``removed``). Multiple choices per House Part form the ranked
  AVL; resolution walks them in rank order and falls back silently.
- The **audit trail** records every decision event (recorded, promoted,
  reranked, removed, superseded) — removal is a state change, never a delete.

A spec key is four exact strings, **supplied canonical by the agent** — this
module does no value normalization or spec parsing on purpose (that judgment
belongs to the agent, not Python):

- ``kind``      — 'resistor', 'capacitor', ... (derived from designator prefix)
- ``value``     — canonical value string, e.g. '22k', '100n'
- ``package``   — e.g. '0603'
- ``qualifier`` — '' for the house default; a part needing more than the house
  standard (e.g. '100V', '1%') gets its own spec key via this field

``last_stock`` / ``last_price`` / ``last_verified_at`` on each choice are an
advisory cache only, refreshed after live verifies. **Never order against
them** — stock is always re-verified live at BOM time.

Schema v1 databases (single ``current`` part per spec) migrate automatically
on open: each spec tuple becomes a House Part, its current part the rank-1
active Part Choice, and demoted history rows become ``superseded`` audit
events (NOT re-approved onto the AVL). The v1 table is kept as
``house_parts_v1`` for rollback.

DB location: ``--db`` flag / explicit arg → ``HENDLEY_DB`` env var →
``~/.hendley/parts.db`` (user-level: the house-parts list spans designs).
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 2

CHOICE_STATES = ("active", "removed")
AUDIT_EVENTS = ("recorded", "promoted", "reranked", "removed", "superseded")

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
    """Open (creating dir + schema, migrating v1 if found) the house-parts DB."""
    db_path = resolve_db_path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    version = _schema_version(conn)
    if version == 1:
        _migrate_v1_to_v2(conn)
    else:
        for stmt in _SCHEMA_STATEMENTS:
            conn.execute(stmt)
        conn.execute(
            "INSERT OR IGNORE INTO meta (key, value) VALUES ('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
        conn.commit()
    return conn


def _schema_version(conn: sqlite3.Connection) -> int | None:
    """Read the stored schema version; None for a fresh (or pre-meta) database."""
    has_meta = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='meta'"
    ).fetchone()
    if not has_meta:
        return None
    row = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
    return int(row[0]) if row else None


def _migrate_v1_to_v2(conn: sqlite3.Connection) -> None:
    """Upgrade a v1 database in place (v1 table kept as ``house_parts_v1``).

    Per the signed-off design: each distinct spec tuple → one House Part; each
    ``current=1`` row → the rank-1 active Part Choice; ``current=0`` rows →
    ``superseded`` audit events only — demoted parts are NOT re-approved onto
    the AVL (re-approve deliberately via :func:`record` if wanted).

    The whole migration — rename, DDL, data copy, version bump — runs in ONE
    explicit transaction (SQLite DDL is transactional). ``executescript`` or
    autocommitted DDL would commit the rename early, and a failure after that
    would leave a half-migrated DB that re-fails on every later open. A
    failed migration must roll back to a pristine v1 database.
    """
    old_isolation = conn.isolation_level
    conn.isolation_level = None  # manual transaction control: no implicit BEGIN/COMMIT
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            _migrate_v1_to_v2_body(conn)
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.isolation_level = old_isolation


def _migrate_v1_to_v2_body(conn: sqlite3.Connection) -> None:
    conn.execute("ALTER TABLE house_parts RENAME TO house_parts_v1")
    for stmt in _SCHEMA_STATEMENTS:
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
    conn.execute(
        "UPDATE meta SET value=? WHERE key='schema_version'", (str(SCHEMA_VERSION),)
    )


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


def _choice_to_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "housePartId": row["house_part_id"],
        "lcscCode": row["lcsc_code"],
        "mpn": row["mpn"],
        "manufacturer": row["manufacturer"],
        "description": row["description"],
        "rank": row["rank"],
        "state": row["state"],
        "approvedAt": row["approved_at"],
        "design": row["design"],
        "note": row["note"],
        "lastStock": row["last_stock"],
        "lastPrice": row["last_price"],
        "lastVerifiedAt": row["last_verified_at"],
    }


def _audit_to_dict(row: sqlite3.Row) -> dict:
    return {
        "event": row["event"],
        "lcscCode": row["lcsc_code"],
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
    out["choices"] = [_choice_to_dict(r) for r in _active_choices(conn, house["id"])]
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
    conn: sqlite3.Connection, house_part_id: int, lcsc_code: str
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM part_choices WHERE house_part_id=? AND state='active' "
        "AND lcsc_code=?",
        (house_part_id, lcsc_code),
    ).fetchone()


def _require_active_choice(
    conn: sqlite3.Connection, house_part_id: int, lcsc_code: str
) -> sqlite3.Row:
    choice = _find_active_choice(conn, house_part_id, lcsc_code)
    if choice is None:
        raise ValueError(f"{lcsc_code} is not an active choice for this spec")
    return choice


def record(
    conn: sqlite3.Connection,
    kind: str,
    value: str,
    package: str,
    lcsc_code: str,
    qualifier: str = "",
    mpn: str | None = None,
    manufacturer: str | None = None,
    description: str | None = None,
    design: str | None = None,
    note: str | None = None,
    rank: int = 1,
) -> dict:
    """Approve a part as a ranked choice for a spec (creating the House Part).

    Default ``rank=1`` is promotion: the new choice is tried first and every
    existing active choice shifts down one — **nothing is demoted off the
    list** (removal is explicit, via :func:`remove_choice`). A code already
    active on the AVL is *moved* to the requested rank (metadata updated from
    any non-None arguments) rather than duplicated. Out-of-range ranks clamp
    to the end of the list. Spec-key fields and ``lcsc_code`` must be
    non-empty.
    """
    for name, val in (("kind", kind), ("value", value), ("package", package),
                      ("lcsc_code", lcsc_code)):
        if not val or not str(val).strip():
            raise ValueError(f"record() requires a non-empty {name!r}")
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

        existing = _find_active_choice(conn, house_id, lcsc_code)
        n_active = len(_active_choices(conn, house_id))

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
            conn.execute(
                "INSERT INTO part_audit (house_part_id, event, lcsc_code, at, design, "
                "note, detail) VALUES (?, 'promoted', ?, ?, ?, ?, ?)",
                (house_id, lcsc_code, now, design, note,
                 json.dumps({"fromRank": old_rank, "toRank": target})),
            )
            choice_id = existing["id"]
        else:
            target = min(rank, n_active + 1)
            _shift_ranks(conn, house_id, +1, target)
            cur = conn.execute(
                "INSERT INTO part_choices (house_part_id, lcsc_code, mpn, manufacturer, "
                "description, rank, state, approved_at, design, note) "
                "VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)",
                (house_id, lcsc_code, mpn, manufacturer, description, target, now,
                 design, note),
            )
            choice_id = cur.lastrowid
            conn.execute(
                "INSERT INTO part_audit (house_part_id, event, lcsc_code, at, design, "
                "note, detail) VALUES (?, 'recorded', ?, ?, ?, ?, ?)",
                (house_id, lcsc_code, now, design, note,
                 json.dumps({"rank": target})),
            )
    row = conn.execute("SELECT * FROM part_choices WHERE id=?", (choice_id,)).fetchone()
    return _choice_to_dict(row)


def rerank(
    conn: sqlite3.Connection,
    kind: str,
    value: str,
    package: str,
    lcsc_code: str,
    new_rank: int,
    qualifier: str = "",
    note: str | None = None,
) -> dict:
    """Move an active choice to a new rank (a recorded, deliberate decision)."""
    if new_rank < 1:
        raise ValueError(f"rerank() new_rank must be >= 1, got {new_rank}")
    with conn:
        house = _require_house(conn, kind, value, package, qualifier)
        choice = _require_active_choice(conn, house["id"], lcsc_code)
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
        conn.execute(
            "INSERT INTO part_audit (house_part_id, event, lcsc_code, at, design, note, "
            "detail) VALUES (?, 'reranked', ?, ?, NULL, ?, ?)",
            (house["id"], lcsc_code, _now(), note,
             json.dumps({"fromRank": old_rank, "toRank": target})),
        )
    row = conn.execute("SELECT * FROM part_choices WHERE id=?", (choice["id"],)).fetchone()
    return _choice_to_dict(row)


def remove_choice(
    conn: sqlite3.Connection,
    kind: str,
    value: str,
    package: str,
    lcsc_code: str,
    qualifier: str = "",
    note: str | None = None,
) -> dict:
    """Remove a choice from the AVL — a state change to ``removed``, never a delete."""
    with conn:
        house = _require_house(conn, kind, value, package, qualifier)
        choice = _require_active_choice(conn, house["id"], lcsc_code)
        old_rank = choice["rank"]
        conn.execute(
            "UPDATE part_choices SET state='removed', rank=NULL WHERE id=?",
            (choice["id"],),
        )
        _shift_ranks(conn, house["id"], -1, old_rank)
        conn.execute(
            "INSERT INTO part_audit (house_part_id, event, lcsc_code, at, design, note, "
            "detail) VALUES (?, 'removed', ?, ?, NULL, ?, ?)",
            (house["id"], lcsc_code, _now(), note,
             json.dumps({"fromRank": old_rank})),
        )
    row = conn.execute("SELECT * FROM part_choices WHERE id=?", (choice["id"],)).fetchone()
    return _choice_to_dict(row)


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
        d["choices"] = [_choice_to_dict(r) for r in _active_choices(conn, h["id"])]
        out.append(d)
    return out


def update_verified(
    conn: sqlite3.Connection,
    lcsc_code: str,
    stock: int | None,
    price: float | None,
    when: str | None = None,
) -> int:
    """Refresh the advisory stock/price cache on every choice carrying a code."""
    with conn:
        cur = conn.execute(
            "UPDATE part_choices SET last_stock=?, last_price=?, last_verified_at=? "
            "WHERE lcsc_code=?",
            (stock, price, when or _now(), lcsc_code),
        )
    return cur.rowcount
