"""The JLCPCB Provider Adapter — one gate, one exporter for JLC order files.

Unifies the two emit paths that grew separately: the resolution-driven BOM
(``hendley bom``, columns ``…, LCSC Part #``) and the live-design order files
(``hendley pcba``: ``bom.csv`` with ``JLCPCB Part #`` + ``cpl.csv`` with
rotation corrections). The adapter formats and gates; it never selects parts
(architecture invariant 5).

- :meth:`JLCPCBAdapter.validate` — the blocking-check gate over a resolution
  document (error-severity checks + synthesized ``unresolved``).
- :meth:`JLCPCBAdapter.export` — writes ``bom.csv`` (and ``cpl.csv`` when the
  document carries ``placements``) in the exact pcba byte format, applying
  ``data/cpl-rotations.json`` corrections.

The resolution document's optional top-level ``placements`` list carries the
board side of a live extraction::

    {"designator": "R1", "x": 1.0, "y": 2.0, "angle": 90,
     "mirror": false, "populate": true, "footprint": "R-0603"}
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from ...domain.model import Check
from ...ingestion.fusion.live_design import Placement
from ...ingestion.fusion.parts_json import DesignPart
from .bom_csv import BomLine, blocking_checks
from .order_files import (
    BOM_FIELDS,
    CPL_FIELDS,
    build_cpl_rows,
    load_rotations,
    natural_key,
    write_csv,
)


def _bom_lines(resolution: dict) -> list[BomLine]:
    return [BomLine.from_dict(x) for x in resolution.get("lines") or []]


class JLCPCBAdapter:
    """Formats approved resolutions into JLCPCB upload files."""

    provider = "jlcpcb"

    def validate(self, resolution: dict) -> list[Check]:
        """Every reason this order must not be uploaded (empty = clean)."""
        return [Check(check=c["check"], severity=c["severity"],
                      message=c.get("message", ""))
                for _, c in blocking_checks(_bom_lines(resolution))]

    def export(self, resolution: dict, outdir: Path, *,
               rotations: str | Path | None = None,
               on_note: Callable[[str], None] | None = None) -> list[Path]:
        """Write bom.csv (+ cpl.csv when placements are present); returns paths.

        Emits in the pcba byte format (``JLCPCB Part #`` header, CRLF rows).
        ``on_note`` receives human-readable notes (rotation corrections
        applied) as they happen.
        """
        outdir = Path(outdir).expanduser()
        outdir.mkdir(parents=True, exist_ok=True)
        note = on_note or (lambda _msg: None)

        bom_rows = self._bom_rows(resolution)
        paths = [outdir / "bom.csv"]
        write_csv(bom_rows, BOM_FIELDS, paths[0])

        placements = resolution.get("placements")
        if placements:
            cpl_rows, applied = self._cpl_rows(resolution, placements, rotations)
            for a in applied:
                note(f"rotation corrected: {a['designator']} {a['rawAngle']}° → "
                     f"{a['rotation']}° (matched {a['matched']})")
            cpl_path = outdir / "cpl.csv"
            write_csv(cpl_rows, CPL_FIELDS, cpl_path)
            paths.append(cpl_path)
        return paths

    def _bom_rows(self, resolution: dict) -> list[dict]:
        """Group populated lines into JLC BOM rows (comment, footprint, ref)."""
        groups: dict[tuple[str, str, str], list[str]] = {}
        for line in _bom_lines(resolution):
            if line.dnp:
                continue
            key = (line.comment or "", line.footprint or "", line.ref or "")
            groups.setdefault(key, []).extend(line.designators)
        rows = [
            {
                "Comment": comment,
                "Designator": ",".join(sorted(desigs, key=natural_key)),
                "Footprint": footprint,
                "JLCPCB Part #": ref,
            }
            for (comment, footprint, ref), desigs in groups.items()
        ]
        rows.sort(key=lambda r: natural_key(r["Designator"].split(",")[0]))
        return rows

    def _cpl_rows(self, resolution: dict, placements: list[dict],
                  rotations: str | Path | None) -> tuple[list[dict], list[dict]]:
        """CPL rows via the proven builder, reconstructed from the document."""
        parts = []
        for line in _bom_lines(resolution):
            for desig in line.designators:
                parts.append(DesignPart(
                    designator=desig,
                    jlc_code=line.ref,
                    attributes={"DNP": "1"} if line.dnp else {},
                ))
        placement_objs = [
            Placement(
                designator=p["designator"],
                x=p["x"], y=p["y"], angle=p["angle"],
                mirror=bool(p.get("mirror", False)),
                populate=bool(p.get("populate", True)),
                footprint=p.get("footprint"),
            )
            for p in placements
        ]
        return build_cpl_rows(parts, placement_objs, load_rotations(rotations))
