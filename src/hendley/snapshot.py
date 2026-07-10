"""Release Snapshots — the immutable "what did we actually order" record.

The house-parts DB holds *policy* (which parts are approved, in what order);
it mutates as stock dies and picks change. A Release Snapshot holds *fact*:
what each BOM line resolved to at emit time — chosen code, rank used,
substitution flag, live stock, unit price, offer type, checks — written once
beside the CSV and never updated. It is the only artifact that can answer
"what exactly did we build in rev C?" after the DB has moved on.

The snapshot embeds the resolution document **verbatim** (all resolver
fields survive) plus emit metadata. Filenames are timestamped
(``<csv-stem>.<UTC>.snapshot.json``) so every emit is its own fact —
re-emitting after a fix adds a second snapshot rather than touching the
first — and the writer refuses to overwrite regardless.

``hendley bom -o board.csv`` writes one automatically for a clean emit (no
unresolved lines, no error-severity checks); ``--no-snapshot`` opts out.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

SNAPSHOT_VERSION = 1


def snapshot_path(csv_path: str | Path, when: str) -> Path:
    """The timestamped sibling path for a CSV's snapshot."""
    csv_path = Path(csv_path)
    stamp = when.replace("-", "").replace(":", "").replace("+0000", "Z")
    return csv_path.with_name(f"{csv_path.stem}.{stamp}.snapshot.json")


def write_release_snapshot(
    resolution_doc: dict,
    csv_path: str | Path,
    when: str | None = None,
) -> Path:
    """Write the immutable emit record beside the CSV; returns its path.

    ``resolution_doc`` is the raw resolution JSON (the ``hendley resolve``
    output or agent-composed equivalent), embedded verbatim. Raises
    ``FileExistsError`` rather than ever overwriting an existing snapshot.
    """
    when = when or datetime.now(timezone.utc).isoformat(timespec="seconds")
    path = snapshot_path(csv_path, when)
    if path.exists():
        raise FileExistsError(f"snapshot already exists (snapshots are immutable): {path}")
    lines = resolution_doc.get("lines") or []
    doc = {
        "snapshotVersion": SNAPSHOT_VERSION,
        "emittedAt": when,
        "design": resolution_doc.get("design"),
        "productionQuantity": resolution_doc.get("productionQuantity"),
        "csv": Path(csv_path).name,
        "summary": {
            "lines": len(lines),
            "partsPerBoard": sum(len(x.get("designators") or []) for x in lines),
            "substitutions": sum(1 for x in lines if x.get("substitution")),
        },
        "resolution": resolution_doc,
    }
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
    return path
