from pathlib import Path

from hendley.ingestion.fusion.bridge import FusionBridge
from hendley.ingestion.fusion.visual import (
    _recompress_png,
    _schematic_detail,
    add_board_crops,
    capture_visual_evidence,
)


class ExportBridge:
    def __init__(self, local_dir: Path, sheets=None):
        self.local_dir = local_dir
        self.commands = []
        self.board = False
        self.sheets = sheets or [{"number": 2, "name": "Power"},
                                 {"number": 1, "name": "Input"}]

    def read(self, entity_type, obj=None):
        if entity_type == "electronics.Board":
            return {"items": [{"object_id": 1}] if self.board else []}
        return {"items": self.read_all(entity_type)[:1]}

    def read_all(self, entity_type):
        if entity_type == "electronics.Sheet" and not self.board:
            return list(self.sheets)
        return []

    def run_eagle(self, command):
        self.commands.append(command)
        if command == "EDIT .brd;":
            self.board = True
        if "EXPORT IMAGE" in command:
            export = command.split("EXPORT IMAGE", 1)[1]
            filename = export.split("\\")[-1].split()[0]
            (self.local_dir / filename).write_bytes(command.encode())


def test_capture_enumerates_existing_sheets_and_exports_board(tmp_path, monkeypatch):
    monkeypatch.setenv("HENDLEY_VISUAL_DIR", str(tmp_path))
    monkeypatch.setenv("HENDLEY_FUSION_VISUAL_DIR", r"C:\hendley")
    bridge = ExportBridge(tmp_path)

    got = capture_visual_evidence(
        bridge, "hendley test",
        targets=[{"designator": "C3", "x": 16, "y": 67}])

    # The schematic is already current: no EDIT .S1 up front, and sheet 1 is
    # captured last so every EDIT is a real switch (a no-op EDIT latches).
    assert bridge.commands[0] == "EDIT .S2; WINDOW FIT;"
    assert bridge.commands[1].startswith("EXPORT IMAGE")
    assert bridge.commands[2] == "EDIT .S1; WINDOW FIT;"
    assert "EDIT .brd;" in bridge.commands
    assert not any("BOARD;" in c for c in bridge.commands)
    assert any("WINDOW (10 61) (22 73);" in c for c in bridge.commands)
    assert [s["number"] for s in got["sheets"]] == [1, 2]
    assert len(got["images"]) == 4 and len(got["digest"]) == 64
    assert got["schemaVersion"] == 4
    assert got["boardCrops"][0]["widthMm"] == 12


def test_one_sheet_design_fires_no_edit(tmp_path, monkeypatch):
    monkeypatch.setenv("HENDLEY_VISUAL_DIR", str(tmp_path))
    bridge = ExportBridge(tmp_path, sheets=[{"number": 1, "name": ""}])

    got = capture_visual_evidence(bridge, "comet")

    assert not any(c.startswith("EDIT .S") for c in bridge.commands)
    assert bridge.commands[0] == "WINDOW FIT;"
    assert [s["number"] for s in got["sheets"]] == [1]


def test_capture_without_sheet_rows_is_a_nonfatal_noop(tmp_path, monkeypatch):
    monkeypatch.setenv("HENDLEY_VISUAL_DIR", str(tmp_path))
    monkeypatch.setattr("hendley.ingestion.fusion.live_design.time.sleep",
                        lambda seconds: None)

    class NoSheets:
        def run_eagle(self, command):
            assert command == "EDIT .S1;"

        def read(self, entity_type, obj=None):
            return {"items": []}

        def read_all(self, entity_type):
            return []

    assert capture_visual_evidence(NoSheets(), "empty") is None


def test_capture_from_board_switches_to_schematic_before_reading_sheets(
        tmp_path, monkeypatch):
    monkeypatch.setenv("HENDLEY_VISUAL_DIR", str(tmp_path))
    events = []

    class FromBoard:
        schematic = False

        def run_eagle(self, command):
            events.append(("command", command))
            self.schematic = command == "EDIT .S1;" or self.schematic

        def read(self, entity_type, obj=None):
            events.append(("probe", entity_type))
            return {"items": [{"number": 1}] if self.schematic else []}

        def read_all(self, entity_type):
            events.append(("read", entity_type))
            return []

    capture_visual_evidence(FromBoard(), "deferred")

    assert events[:4] == [
        ("probe", "electronics.Sheet"),
        ("command", "EDIT .S1;"),
        ("probe", "electronics.Sheet"),
        ("read", "electronics.Sheet"),
    ]


def test_eagle_command_preserves_windows_path_in_generated_python():
    class RecordingBridge(FusionBridge):
        def __init__(self):
            self.source = ""

        def execute_script(self, source):
            self.source = source
            compile(source, "<fusion-script>", "exec")
            return {"success": True}

    bridge = RecordingBridge()
    bridge.run_eagle(r"EXPORT IMAGE C:\tmp\hendley-visual\sheet-1.png 300;")

    assert r"C:\\tmp\\hendley-visual\\sheet-1.png" in bridge.source


def test_fusion_png_is_losslessly_recompressed(tmp_path):
    import struct
    import zlib

    path = tmp_path / "sheet.png"
    raw = b"\x00" + b"\xff\xff\xff" * 1000
    chunks = []
    for kind, payload in (
        (b"IHDR", struct.pack(">IIBBBBB", 1000, 1, 8, 2, 0, 0, 0)),
        (b"IDAT", zlib.compress(raw, level=0)),
        (b"IEND", b""),
    ):
        chunks.append(struct.pack(">I", len(payload)) + kind + payload
                      + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF))
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"".join(chunks))
    before = path.read_bytes()

    _recompress_png(path)

    after = path.read_bytes()
    assert len(after) < len(before) / 10
    assert after.startswith(b"\x89PNG\r\n\x1a\n")


def test_sparse_schematic_gets_a_zoomed_detail_image(tmp_path):
    import struct
    import zlib

    width, height = 100, 80
    pixels = bytearray(b"\xff\xff\xff" * width * height)
    for y in range(35, 45):
        for x in range(42, 58):
            pixels[(y * width + x) * 3:(y * width + x + 1) * 3] = b"\xff\x00\x00"
    raw = b"".join(b"\x00" + pixels[y * width * 3:(y + 1) * width * 3]
                   for y in range(height))
    path = tmp_path / "sheet.png"
    chunks = []
    for kind, payload in (
        (b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)),
        (b"IDAT", zlib.compress(raw)), (b"IEND", b"")):
        chunks.append(struct.pack(">I", len(payload)) + kind + payload
                      + struct.pack(">I", zlib.crc32(kind + payload) & 0xffffffff))
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"".join(chunks))

    detail = _schematic_detail(path)

    assert detail and detail.is_file()
    header = detail.read_bytes()
    got_width, got_height = struct.unpack(">II", header[16:24])
    assert got_width < width and got_height < height


def test_board_crop_phase_never_returns_to_schematic(tmp_path, monkeypatch):
    monkeypatch.setenv("HENDLEY_VISUAL_DIR", str(tmp_path))
    monkeypatch.setenv("HENDLEY_FUSION_VISUAL_DIR", r"C:\hendley")
    bridge = ExportBridge(tmp_path)
    bridge.board = True  # extract_board already made the board current
    sheet = tmp_path / "sheet.png"
    sheet.write_bytes(b"sheet")
    manifest = {"schemaVersion": 3, "design": "test", "dpi": 300,
                "sheets": [{"number": 1, "image": str(sheet)}],
                "boardImage": None, "boardCrops": [], "images": [str(sheet)],
                "digest": "old"}

    got = add_board_crops(
        bridge, manifest, [{"designator": "Q2", "x": 10, "y": 20}])

    assert got["boardCrops"][0]["designator"] == "Q2"
    assert not any(command.startswith("EDIT") for command in bridge.commands)
