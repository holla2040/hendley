"""Golden end-to-end test for `hendley pcba` — the zero-behavior-change gate.

Drives the real CLI (`hendley.cli.main`) against a fake in-memory bridge and
asserts the emitted bom.csv / cpl.csv byte-for-byte. Written BEFORE the
package restructure; the golden bytes must survive it unchanged.
"""

import json

from hendley.cli import main

# The design the fake bridge serves. Exercises: BOM grouping (R1+R2 share a
# line), MPN comment fallback (D1 has no value), DNP-attribute exclusion (TP1),
# populate-flag exclusion (J2), GND pseudo-part, title-block pseudo-part,
# no-LCSC part kept (J1), bottom-side mirror (C1), rotation correction (D1).
SCHEMATICS = [{"object_id": 1, "name": r"C:\Temp\golden sch.sch"}]

PARTS = [
    {"object_id": 10, "name": "R1", "value": "22k", "device_object_id": 100},
    {"object_id": 11, "name": "R2", "value": "22k", "device_object_id": 100},
    {"object_id": 12, "name": "C1", "value": "1u", "device_object_id": 101},
    {"object_id": 13, "name": "D1", "value": "", "device_object_id": 102},
    {"object_id": 14, "name": "TP1", "value": "", "device_object_id": 103},
    {"object_id": 15, "name": "J1", "value": "CONN-4", "device_object_id": 104},
    {"object_id": 16, "name": "J2", "value": "CONN-2", "device_object_id": 104},
    {"object_id": 17, "name": "GND1", "value": "", "device_object_id": 105},
    {"object_id": 18, "name": "U$1", "value": "", "device_object_id": 106},
]

# The library devices: footprint presence (package_object_id) is what
# separates real parts from supply symbols. Device 100 deliberately has NO
# 3D model — 3D is irrelevant to this tool. Rows repeat (the live endpoint
# does that); extraction must dedupe.
DEVICES = [
    {"object_id": 100, "name": "-0603", "package_object_id": 412},
    {"object_id": 100, "name": "-0603", "package_object_id": 412},
    {"object_id": 101, "name": "-0603", "package_object_id": 413},
    {"object_id": 102, "name": "", "package_object_id": 414},
    {"object_id": 103, "name": "", "package_object_id": 415},
    {"object_id": 104, "name": "", "package_object_id": 416},
    {"object_id": 105, "name": "", "package_object_id": 0},  # SUPPLY SYMBOL
    {"object_id": 106, "name": "", "package_object_id": 417},  # title block
]

ATTRS = {
    10: {"LCSC": "C31850", "MPN": "0603WAF2202T5E"},
    11: {"LCSC": "C31850", "MPN": "0603WAF2202T5E"},
    12: {"LCSC": "C15849", "MPN": "CL10A105KB8NNNC"},
    13: {"LCSC": "C19077482", "MPN": "1SMA4744A"},
    14: {"DNP": "1"},
    15: {},
    16: {},
    17: {},
    18: {},
}

ELEMENTS = [
    {"object_id": 30, "name": "R1", "x": 1.0, "y": 2.0, "angle": 0,
     "mirror": 0, "populate": 1, "package_object_id": 50},
    {"object_id": 31, "name": "R2", "x": 3.0, "y": 2.0, "angle": 90,
     "mirror": 0, "populate": 1, "package_object_id": 50},
    {"object_id": 32, "name": "C1", "x": -4.5, "y": 6.25, "angle": 180,
     "mirror": 1, "populate": 1, "package_object_id": 51},
    {"object_id": 33, "name": "D1", "x": 8.0, "y": -1.0, "angle": 300,
     "mirror": 0, "populate": 1, "package_object_id": 52},
    {"object_id": 34, "name": "TP1", "x": 0.0, "y": 0.0, "angle": 0,
     "mirror": 0, "populate": 1, "package_object_id": 53},
    {"object_id": 35, "name": "J1", "x": 10.0, "y": 10.0, "angle": 270,
     "mirror": 0, "populate": 1, "package_object_id": 54},
    {"object_id": 36, "name": "J2", "x": 12.0, "y": 10.0, "angle": 0,
     "mirror": 0, "populate": 0, "package_object_id": 54},
]

PACKAGES = [
    {"object_id": 50, "name": "R-0603"},
    {"object_id": 51, "name": "C-0603"},
    {"object_id": 52, "name": "DO-214AC(SMA)"},
    {"object_id": 53, "name": "TP-1MM"},
    {"object_id": 54, "name": "HDR-2.54"},
]

ROTATIONS = {"corrections": [
    {"lcsc": "C19077482", "footprint": "DO-214AC(SMA)", "rotationOffsetDeg": 90,
     "note": "golden fixture"},
]}

GOLDEN_BOM = (
    "Comment,Designator,Footprint,JLCPCB Part #\r\n"
    "1u,C1,C-0603,C15849\r\n"
    "1SMA4744A,D1,DO-214AC(SMA),C19077482\r\n"
    "CONN-4,J1,HDR-2.54,\r\n"
    "22k,\"R1,R2\",R-0603,C31850\r\n"
)

GOLDEN_CPL = (
    "Designator,Mid X,Mid Y,Layer,Rotation\r\n"
    "C1,-4.5mm,6.25mm,Bottom,180\r\n"
    "D1,8.0mm,-1.0mm,Top,30\r\n"
    "J1,10.0mm,10.0mm,Top,270\r\n"
    "R1,1.0mm,2.0mm,Top,0\r\n"
    "R2,3.0mm,2.0mm,Top,90\r\n"
)


class FakeBridge:
    """Stands in for FusionBridge: serves the canned design, no HTTP."""

    def __init__(self, host=None, port=27182, timeout=60):
        self.board_switched = False

    def read(self, entity_type, obj=None):
        if entity_type == "electronics.Element" and not self.board_switched:
            return {"items": []}  # board not current yet → triggers BOARD;
        return {"items": self._rows(entity_type, obj)}

    def read_all(self, entity_type, obj=None, page=1000):
        return self._rows(entity_type, obj)

    def run_eagle(self, command):
        assert command == "BOARD;"
        self.board_switched = True
        return {}

    def _rows(self, entity_type, obj):
        if entity_type == "electronics.Schematic":
            return list(SCHEMATICS)
        if entity_type == "electronics.Part":
            return list(PARTS)
        if entity_type == "electronics.Attribute":
            [flt] = (obj or {}).get("filters", [{}])
            assert flt.get("property") == "part_object_id"  # scoped reads only
            attrs = ATTRS.get(flt.get("value"), {})
            return [{"name": k, "value": v} for k, v in attrs.items()]
        if entity_type == "electronics.Element":
            return list(ELEMENTS) if self.board_switched else []
        if entity_type == "electronics.Package":
            return list(PACKAGES)
        if entity_type == "electronics.Device":
            return list(DEVICES)
        raise AssertionError(f"unexpected entity type {entity_type!r}")


def test_pcba_golden_csvs(tmp_path, monkeypatch, capsys):
    import hendley.ingestion.fusion.bridge as bridge_mod

    monkeypatch.setattr(bridge_mod, "FusionBridge", FakeBridge)
    rotations = tmp_path / "rotations.json"
    rotations.write_text(json.dumps(ROTATIONS))
    outdir = tmp_path / "out"

    rc = main(["pcba", "--no-verify", "-o", str(outdir), "--rotations", str(rotations)])

    assert rc == 0
    assert (outdir / "bom.csv").read_bytes() == GOLDEN_BOM.encode()
    assert (outdir / "cpl.csv").read_bytes() == GOLDEN_CPL.encode()
    err = capsys.readouterr().err
    assert "design 'golden': 7 part(s) read from the schematic" in err
    assert "DNP (excluded from BOM, CPL, and stock check): TP1" in err
    assert "rotation corrected: D1 300° → 30°" in err


def test_jlc_alias_is_pcba(tmp_path, monkeypatch):
    import hendley.ingestion.fusion.bridge as bridge_mod

    monkeypatch.setattr(bridge_mod, "FusionBridge", FakeBridge)
    monkeypatch.chdir(tmp_path)  # no rotations file to walk up to
    outdir = tmp_path / "out"
    rc = main(["jlc", "--no-verify", "-o", str(outdir)])
    assert rc == 0 and (outdir / "bom.csv").exists() and (outdir / "cpl.csv").exists()


def test_pcba_refuses_to_emit_an_unapproved_family_even_without_verify(
        tmp_path, monkeypatch, capsys):
    import sys

    import hendley.ingestion.fusion.bridge as bridge_mod

    monkeypatch.setattr(bridge_mod, "FusionBridge", FakeBridge)
    module = sys.modules[__name__]
    monkeypatch.setattr(module, "PARTS", PARTS + [
        {"object_id": 19, "name": "U7", "value": "RS485", "device_object_id": 107},
    ])
    monkeypatch.setattr(module, "DEVICES", DEVICES + [
        {"object_id": 107, "name": "-SO8", "package_object_id": 418},
    ])
    monkeypatch.setattr(module, "ATTRS", {**ATTRS, 19: {}})
    monkeypatch.setattr(module, "ELEMENTS", ELEMENTS + [
        {"object_id": 37, "name": "U7", "x": 0, "y": 0, "angle": 0,
         "mirror": 0, "populate": 1, "package_object_id": 55},
    ])
    monkeypatch.setattr(module, "PACKAGES", PACKAGES + [
        {"object_id": 55, "name": "IC-SO8"},
    ])
    outdir = tmp_path / "out"

    rc = main(["pcba", "--no-verify", "-o", str(outdir)])

    assert rc == 1
    assert not outdir.exists()
    err = capsys.readouterr().err
    assert "U7 names family “RS485”" in err
    assert "use `hendley app`" in err
