"""The house-parts database — Hendley's memory of spec → chosen-part decisions.

The user designs in *specifications* ("22k, 0603"), not part numbers. This
module persists, across designs, which concrete orderable part (LCSC code,
MPN, manufacturer) was chosen for each spec — the industry "house parts list".
At BOM-generation time the agent looks specs up here before searching anew;
every new pick is recorded here so it never has to be made twice.

A spec key is four exact strings, **supplied canonical by the agent** — this
module does no value normalization or spec parsing on purpose (that judgment
belongs to the agent, not Python):

- ``kind``      — 'resistor', 'capacitor', ... (derived from designator prefix)
- ``value``     — canonical value string, e.g. '22k', '100n'
- ``package``   — e.g. '0603'
- ``qualifier`` — '' for the house default; a part needing more than the house
  standard (e.g. '100V', '1%') gets its own spec key via this field

Exactly one row per spec is ``current`` (the active house part). Recording a
new pick for an existing spec *promotes* it: the old row is demoted to history,
never deleted — so past choices and their age stay queryable.

``last_stock`` / ``last_price`` / ``last_verified_at`` are an advisory cache
only, refreshed after live verifies. **Never order against them** — stock is
always re-verified live at BOM time.

DB location: ``--db`` flag / explicit arg → ``HENDLEY_DB`` env var →
``~/.hendley/parts.db`` (user-level: the house-parts list spans designs).
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS house_parts (
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
CREATE UNIQUE INDEX IF NOT EXISTS ux_house_current
  ON house_parts(kind, value, package, qualifier) WHERE current = 1;
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""

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
    """Open (creating dir + schema if needed) the house-parts database."""
    db_path = resolve_db_path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    conn.execute(
        "INSERT OR IGNORE INTO meta (key, value) VALUES ('schema_version', ?)",
        (str(SCHEMA_VERSION),),
    )
    conn.commit()
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _row_to_dict(row: sqlite3.Row) -> dict:
    """SQLite row → the camelCase dict shape the rest of Hendley's JSON uses."""
    return {
        "id": row["id"],
        "kind": row["kind"],
        "value": row["value"],
        "package": row["package"],
        "qualifier": row["qualifier"],
        "lcscCode": row["lcsc_code"],
        "mpn": row["mpn"],
        "manufacturer": row["manufacturer"],
        "description": row["description"],
        "current": bool(row["current"]),
        "pickedAt": row["picked_at"],
        "design": row["design"],
        "note": row["note"],
        "lastStock": row["last_stock"],
        "lastPrice": row["last_price"],
        "lastVerifiedAt": row["last_verified_at"],
    }


def lookup(
    conn: sqlite3.Connection, kind: str, value: str, package: str, qualifier: str = ""
) -> dict | None:
    """Return the current house part for a spec, or None if never picked."""
    row = conn.execute(
        "SELECT * FROM house_parts WHERE kind=? AND value=? AND package=? AND qualifier=? "
        "AND current=1",
        (kind, value, package, qualifier),
    ).fetchone()
    return _row_to_dict(row) if row else None


def history(
    conn: sqlite3.Connection, kind: str, value: str, package: str, qualifier: str = ""
) -> list[dict]:
    """Past (demoted) picks for a spec, newest first — the substitution trail."""
    rows = conn.execute(
        "SELECT * FROM house_parts WHERE kind=? AND value=? AND package=? AND qualifier=? "
        "AND current=0 ORDER BY id DESC",
        (kind, value, package, qualifier),
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


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
) -> dict:
    """Record a pick as the current house part for a spec (promotion semantics).

    Any existing current row for the spec is demoted to history; the new pick
    becomes current. The spec-key fields and ``lcsc_code`` must be non-empty.
    """
    for name, val in (("kind", kind), ("value", value), ("package", package),
                      ("lcsc_code", lcsc_code)):
        if not val or not str(val).strip():
            raise ValueError(f"record() requires a non-empty {name!r}")
    with conn:  # one transaction: demote + insert
        conn.execute(
            "UPDATE house_parts SET current=0 "
            "WHERE kind=? AND value=? AND package=? AND qualifier=? AND current=1",
            (kind, value, package, qualifier),
        )
        cur = conn.execute(
            "INSERT INTO house_parts (kind, value, package, qualifier, lcsc_code, mpn, "
            "manufacturer, description, current, picked_at, design, note) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)",
            (kind, value, package, qualifier, lcsc_code, mpn, manufacturer,
             description, _now(), design, note),
        )
    row = conn.execute("SELECT * FROM house_parts WHERE id=?", (cur.lastrowid,)).fetchone()
    return _row_to_dict(row)


def list_parts(conn: sqlite3.Connection, kind: str | None = None) -> list[dict]:
    """All current house parts, optionally filtered by kind."""
    if kind:
        rows = conn.execute(
            "SELECT * FROM house_parts WHERE current=1 AND kind=? "
            "ORDER BY kind, value, package, qualifier",
            (kind,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM house_parts WHERE current=1 ORDER BY kind, value, package, qualifier"
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def update_verified(
    conn: sqlite3.Connection,
    lcsc_code: str,
    stock: int | None,
    price: float | None,
    when: str | None = None,
) -> int:
    """Refresh the advisory stock/price cache for every row carrying a code."""
    with conn:
        cur = conn.execute(
            "UPDATE house_parts SET last_stock=?, last_price=?, last_verified_at=? "
            "WHERE lcsc_code=?",
            (stock, price, when or _now(), lcsc_code),
        )
    return cur.rowcount
