"""Provider adapter tests — JLCPCB unification and the PCBWay coupling proof."""

import json
import subprocess
import sys
from pathlib import Path

from hendley.domain.model import RequirementLine, RequirementsBom, SpecKey
from hendley.knowledge.partsdb import PartsDb, record
from hendley.providers.jlcpcb.adapter import JLCPCBAdapter
from hendley.providers.pcbway.adapter import PCBWayAdapter, render_pcbway_csv
from hendley.providers.pcbway.strategy import PCBWayStrategy
from hendley.resolver.orchestration.resolve import resolve

RESOLUTION = {
    "design": "comet",
    "productionQuantity": 1,
    "lines": [
        {"designators": ["R1", "R2"], "comment": "22k", "footprint": "R-0603",
         "ref": "C31850", "mpn": "0603WAF2202T5E", "manufacturer": "UNI-ROYAL",
         "quantityPer": 1},
        {"designators": ["TP1"], "comment": "testpoint", "dnp": True},
        {"designators": ["D1"], "comment": "1SMA4744A", "footprint": "DO-214AC(SMA)",
         "ref": "C19077482", "mpn": "1SMA4744A", "quantityPer": 1},
    ],
    "placements": [
        {"designator": "R1", "x": 1.0, "y": 2.0, "angle": 0,
         "mirror": False, "populate": True, "footprint": "R-0603"},
        {"designator": "R2", "x": 3.0, "y": 2.0, "angle": 90,
         "mirror": False, "populate": True, "footprint": "R-0603"},
        {"designator": "TP1", "x": 0.0, "y": 0.0, "angle": 0,
         "mirror": False, "populate": True, "footprint": "TP-1MM"},
        {"designator": "D1", "x": 8.0, "y": -1.0, "angle": 300,
         "mirror": False, "populate": True, "footprint": "DO-214AC(SMA)"},
    ],
}


class NullSource:
    name = "null"

    def verify(self, refs):
        raise AssertionError("pcbway resolution must never live-verify")

    def discover(self, query):
        return []


# ---------------------------------------------------------------------------
# JLCPCB adapter
# ---------------------------------------------------------------------------

def test_jlcpcb_adapter_exports_bom_and_cpl_with_rotations(tmp_path):
    rotations = tmp_path / "rot.json"
    rotations.write_text(json.dumps({"corrections": [
        {"lcsc": "C19077482", "rotationOffsetDeg": 90}]}))
    notes = []
    paths = JLCPCBAdapter().export(RESOLUTION, tmp_path / "out",
                                   rotations=rotations, on_note=notes.append)
    assert [p.name for p in paths] == ["bom.csv", "cpl.csv"]
    bom = paths[0].read_text().splitlines()
    assert bom[0] == "Comment,Designator,Footprint,JLCPCB Part #"
    assert '22k,"R1,R2",R-0603,C31850' in bom
    assert all("TP1" not in row for row in bom)  # DNP excluded
    cpl = paths[1].read_text().splitlines()
    assert "D1,8.0mm,-1.0mm,Top,30" in cpl  # (300 + 90) % 360
    assert all("TP1" not in row for row in cpl)
    assert notes and "rotation corrected: D1" in notes[0]


def test_jlcpcb_adapter_skips_cpl_without_placements(tmp_path):
    doc = {k: v for k, v in RESOLUTION.items() if k != "placements"}
    paths = JLCPCBAdapter().export(doc, tmp_path / "out")
    assert [p.name for p in paths] == ["bom.csv"]


def test_jlcpcb_adapter_validate_is_the_blocking_gate():
    assert JLCPCBAdapter().validate(RESOLUTION) == []
    blocked = {"lines": [{"designators": ["R9"], "comment": "47k"}]}
    checks = JLCPCBAdapter().validate(blocked)
    assert [c.check for c in checks] == ["unresolved"]
    assert all(c.severity == "error" for c in checks)


# ---------------------------------------------------------------------------
# PCBWay — the anti-coupling proof
# ---------------------------------------------------------------------------

def _pcbway_setup(tmp_path):
    store = PartsDb(tmp_path / "parts.db")
    # a choice with an MPN identity + a JLC-only choice (unusable for pcbway)
    record(store.conn, "resistor", "22k", "0603", lcsc="C31850",
           mpn="0603WAF2202T5E", manufacturer="UNI-ROYAL")
    record(store.conn, "capacitor", "100n", "0603", lcsc="C14663")
    requirements = RequirementsBom(
        production_quantity=10, design="comet",
        lines=[
            RequirementLine(designators=["R1", "R2"], comment="22k",
                            footprint="0603", spec=SpecKey("resistor", "22k", "0603")),
            RequirementLine(designators=["U1"], comment="LDO",
                            mpn="AMS1117-3.3", manufacturer="AMS"),
            RequirementLine(designators=["TP1"], dnp=True),
        ])
    return store, requirements


def test_pcbway_resolves_by_mpn_unverified_no_api(tmp_path):
    store, requirements = _pcbway_setup(tmp_path)
    result = resolve(store, requirements, datasource=NullSource(),
                     strategy=PCBWayStrategy())
    spec_row, mpn_row, dnp_row = result["lines"]
    # spec line: rank-1 choice by MPN identity, honestly unverified
    assert spec_row["source"] == "db" and spec_row["rankUsed"] == 1
    assert spec_row["mpn"] == "0603WAF2202T5E"
    assert [c["check"] for c in spec_row["checks"]] == ["unverified"]
    assert spec_row["liveStock"] is None  # never invented
    assert spec_row["offerType"] == "pcbway-sourced"
    # explicit MPN line rides through
    assert mpn_row["source"] == "explicit" and mpn_row["mpn"] == "AMS1117-3.3"
    assert [c["check"] for c in mpn_row["checks"]] == ["unverified"]
    assert dnp_row["dnp"] and result["escalations"] == []


def test_pcbway_escalates_identityless_avl(tmp_path):
    store, _ = _pcbway_setup(tmp_path)
    # the capacitor's only choice is LCSC-coded with no MPN → unusable
    requirements = RequirementsBom(
        production_quantity=10,
        lines=[RequirementLine(designators=["C5"],
                               spec=SpecKey("capacitor", "100n", "0603"))])
    result = resolve(store, requirements, datasource=NullSource(),
                     strategy=PCBWayStrategy())
    assert [c["check"] for c in result["lines"][0]["checks"]] == ["avl-exhausted"]
    assert result["escalations"][0]["reason"] == "avl-exhausted"


def test_pcbway_adapter_renders_mpn_bom_and_gates(tmp_path):
    store, requirements = _pcbway_setup(tmp_path)
    result = resolve(store, requirements, datasource=NullSource(),
                     strategy=PCBWayStrategy())
    assert PCBWayAdapter().validate(result) == []  # unverified warns, not blocks
    csv_text = render_pcbway_csv(result)
    rows = csv_text.splitlines()
    assert rows[0] == "Item,Designator,Qty,MPN,Manufacturer,Description,Package"
    assert '1,"R1,R2",2,0603WAF2202T5E,UNI-ROYAL,22k,0603' in rows
    assert "2,U1,1,AMS1117-3.3,AMS,LDO," in rows
    assert all("TP1" not in r for r in rows)  # DNP excluded

    paths = PCBWayAdapter().export(result, tmp_path / "out")
    assert paths[0].name == "pcbway_bom.csv" and paths[0].exists()

    blocked = {"lines": [{"designators": ["J1"], "comment": "no identity"}]}
    checks = PCBWayAdapter().validate(blocked)
    assert [c.check for c in checks] == ["unresolved"]


def test_pcbway_path_never_imports_jlc_modules(tmp_path):
    """THE decoupling proof: a full PCBWay resolution + export runs without
    hendley.datasources.jlc or hendley.providers.jlcpcb ever being imported."""
    script = f"""
import sys
sys.path.insert(0, {str(Path.cwd() / 'src')!r})
from hendley.domain.model import RequirementLine, RequirementsBom, SpecKey
from hendley.knowledge.partsdb import PartsDb, record
from hendley.providers.pcbway.adapter import PCBWayAdapter
from hendley.providers.pcbway.strategy import PCBWayStrategy
from hendley.resolver.orchestration.resolve import resolve

class NullSource:
    name = "null"
    def verify(self, refs): raise AssertionError("no live verify")
    def discover(self, query): return []

store = PartsDb({str(tmp_path / 'parts.db')!r})
record(store.conn, "resistor", "22k", "0603", mpn="0603WAF2202T5E")
requirements = RequirementsBom(production_quantity=5, lines=[
    RequirementLine(designators=["R1"], spec=SpecKey("resistor", "22k", "0603"))])
result = resolve(store, requirements, datasource=NullSource(),
                 strategy=PCBWayStrategy())
assert result["lines"][0]["mpn"] == "0603WAF2202T5E"
PCBWayAdapter().export(result, {str(tmp_path / 'out')!r})
banned = [m for m in sys.modules
          if m.startswith("hendley.datasources.jlc")
          or m.startswith("hendley.providers.jlcpcb")]
assert not banned, f"provider coupling leaked: {{banned}}"
print("ISOLATED")
"""
    proc = subprocess.run([sys.executable, "-c", script],
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert "ISOLATED" in proc.stdout
