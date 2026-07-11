"""PCBWay Provider Adapter — the MPN-based upload BOM."""

from __future__ import annotations

import csv
from pathlib import Path

from ...domain.model import Check

# PCBWay's assembly BOM template, per-board quantities.
CSV_COLUMNS = ("Item", "Designator", "Qty", "MPN", "Manufacturer",
               "Description", "Package")


class PCBWayAdapter:
    """Formats approved resolutions into a PCBWay-compatible BOM CSV."""

    provider = "pcbway"

    def validate(self, resolution: dict) -> list[Check]:
        """Blockers: error checks + populated lines with no MPN and no ref."""
        out: list[Check] = []
        for line in resolution.get("lines") or []:
            for c in line.get("checks") or []:
                if c.get("severity") == "error":
                    out.append(Check(check=c["check"], severity="error",
                                     message=c.get("message", "")))
            if not line.get("dnp") and not line.get("mpn") and not line.get("ref"):
                desigs = ",".join(line.get("designators") or [])
                out.append(Check(check="unresolved", severity="error",
                                 message=f"{desigs}: no MPN and no PCBWay ref"))
        return out

    def export(self, resolution: dict, outdir: Path) -> list[Path]:
        outdir = Path(outdir).expanduser()
        outdir.mkdir(parents=True, exist_ok=True)
        path = outdir / "pcbway_bom.csv"
        path.write_text(render_pcbway_csv(resolution))
        return [path]


def render_pcbway_csv(resolution: dict) -> str:
    """Render a resolution's populated lines as the PCBWay BOM template."""
    import io

    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(CSV_COLUMNS)
    item = 0
    for line in resolution.get("lines") or []:
        if line.get("dnp"):
            continue
        item += 1
        designators = line.get("designators") or []
        qty = len(designators) * int(line.get("quantityPer") or 1)
        writer.writerow((
            item,
            ",".join(designators),
            qty,
            line.get("mpn") or "",
            line.get("manufacturer") or "",
            line.get("comment") or "",
            line.get("footprint") or "",
        ))
    return buf.getvalue()
