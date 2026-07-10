"""Tests for Release Snapshots — the immutable emit record."""

import json

from hendley.cli import main as cli_main
from hendley.snapshot import snapshot_path, write_release_snapshot

RESOLUTION = {
    "design": "comet",
    "productionQuantity": 25,
    "lines": [
        {"designators": ["R1", "R4"], "comment": "22k", "footprint": "0603",
         "lcsc": "C2", "source": "db", "requiredQty": 50,
         "spec": {"kind": "resistor", "value": "22k", "package": "0603",
                  "qualifier": ""},
         "housePartId": 3, "rankUsed": 2, "substitution": True,
         "liveStock": 9000, "unitPrice": 0.001, "offerType": "jlc-mounted",
         "checks": [{"check": "substitution", "severity": "warning",
                     "message": "R1,R4: used rank-2 C2"}]},
        {"designators": ["U1"], "comment": "MT3608", "footprint": "SOT-23-6",
         "lcsc": "C9", "source": "explicit", "quantityPer": 2, "requiredQty": 50,
         "liveStock": 500, "unitPrice": 0.35, "offerType": "jlc-mounted",
         "checks": []},
    ],
}


def test_write_snapshot_embeds_resolution_verbatim(tmp_path):
    csv = tmp_path / "comet_bom.csv"
    path = write_release_snapshot(RESOLUTION, csv, when="2026-07-10T06:30:00+00:00")
    assert path.name == "comet_bom.20260710T063000Z.snapshot.json"
    doc = json.loads(path.read_text())
    assert doc["snapshotVersion"] == 1 and doc["emittedAt"] == "2026-07-10T06:30:00+00:00"
    assert doc["design"] == "comet" and doc["productionQuantity"] == 25
    assert doc["csv"] == "comet_bom.csv"
    # partsPerBoard honors quantityPer: R1,R4 ×1 each + U1 ×2 = 4
    assert doc["summary"] == {"lines": 2, "partsPerBoard": 4, "substitutions": 1}
    # the fact record: every resolver field survives verbatim
    assert doc["resolution"] == RESOLUTION
    assert doc["resolution"]["lines"][0]["rankUsed"] == 2
    assert doc["resolution"]["lines"][0]["liveStock"] == 9000


def test_snapshot_never_overwrites_same_second_gets_suffix(tmp_path):
    csv = tmp_path / "comet_bom.csv"
    when = "2026-07-10T06:30:00+00:00"
    first = write_release_snapshot(RESOLUTION, csv, when=when)
    second = write_release_snapshot(RESOLUTION, csv, when=when)  # same second: no crash
    assert first.exists() and second.exists() and first != second
    assert second.name == "comet_bom.20260710T063000Z-2.snapshot.json"
    assert json.loads(first.read_text()) == json.loads(second.read_text())
    # a later emit is a NEW fact under its own timestamp
    third = write_release_snapshot(RESOLUTION, csv, when="2026-07-10T07:00:00+00:00")
    assert third != snapshot_path(csv, when)


def test_cli_clean_emit_writes_snapshot(tmp_path):
    res = tmp_path / "res.json"
    res.write_text(json.dumps(RESOLUTION))
    csv = tmp_path / "comet_bom.csv"
    assert cli_main(["bom", str(res), "-o", str(csv)]) == 0
    snaps = list(tmp_path.glob("comet_bom.*.snapshot.json"))
    assert len(snaps) == 1
    assert json.loads(snaps[0].read_text())["resolution"] == RESOLUTION


def test_cli_no_snapshot_flag_and_stdout_emit_skip_it(tmp_path):
    res = tmp_path / "res.json"
    res.write_text(json.dumps(RESOLUTION))
    csv = tmp_path / "comet_bom.csv"
    assert cli_main(["bom", str(res), "-o", str(csv), "--no-snapshot"]) == 0
    assert cli_main(["bom", str(res)]) == 0  # stdout: exploratory, no record
    assert list(tmp_path.glob("*.snapshot.json")) == []


def test_cli_blocked_emit_writes_no_snapshot(tmp_path):
    blocked = {
        "design": "comet", "productionQuantity": 25,
        "lines": [{"designators": ["R9"], "comment": "47k",
                   "checks": [{"check": "no-part-choices", "severity": "error",
                               "message": "R9: no House Part recorded"},
                              {"check": "unresolved", "severity": "error",
                               "message": "R9: no part"}]}],
    }
    res = tmp_path / "res.json"
    res.write_text(json.dumps(blocked))
    csv = tmp_path / "comet_bom.csv"
    assert cli_main(["bom", str(res), "-o", str(csv)]) == 1
    assert csv.exists()  # the CSV renders so the gap is visible...
    assert list(tmp_path.glob("*.snapshot.json")) == []  # ...but no fact is recorded
