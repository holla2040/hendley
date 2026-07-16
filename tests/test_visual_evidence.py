from pathlib import Path

from hendley.ingestion.fusion.bridge import FusionBridge
from hendley.ingestion.fusion.visual import capture_visual_evidence


class ExportBridge:
    def __init__(self, local_dir: Path):
        self.local_dir = local_dir
        self.commands = []

    def read_all(self, entity_type):
        if entity_type == "electronics.Sheet":
            return [{"number": 2, "name": "Power"},
                    {"number": 1, "name": "Input"}]
        return []

    def run_eagle(self, command):
        self.commands.append(command)
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

    assert bridge.commands[0] == "EDIT .S1;"
    assert bridge.commands[1] == "EDIT .S1; WINDOW FIT;"
    assert bridge.commands[2].startswith("EXPORT IMAGE")
    assert any("WINDOW (10 61) (22 73);" in c for c in bridge.commands)
    assert [s["number"] for s in got["sheets"]] == [1, 2]
    assert len(got["images"]) == 4 and len(got["digest"]) == 64
    assert got["schemaVersion"] == 2
    assert got["boardCrops"][0]["widthMm"] == 12


def test_capture_without_sheet_rows_is_a_nonfatal_noop(tmp_path, monkeypatch):
    monkeypatch.setenv("HENDLEY_VISUAL_DIR", str(tmp_path))

    class NoSheets:
        def run_eagle(self, command):
            assert command == "EDIT .S1;"

        def read_all(self, entity_type):
            return []

    assert capture_visual_evidence(NoSheets(), "empty") is None


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
