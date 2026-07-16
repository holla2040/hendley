"""Best-effort schematic and board image capture for lazy interpretation."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path

VISUAL_SCHEMA_VERSION = 2
DEFAULT_WINDOWS_DIR = r"C:\tmp\hendley-visual"
DEFAULT_LOCAL_DIR = "~/tmp/hendley-visual"


def _slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-.") or "design"


def _digest(paths: list[Path], metadata: dict) -> str:
    h = hashlib.sha256(json.dumps(metadata, sort_keys=True).encode())
    for path in paths:
        h.update(path.name.encode())
        with path.open("rb") as src:
            for block in iter(lambda: src.read(1024 * 1024), b""):
                h.update(block)
    return h.hexdigest()


def _fresh_export(path: Path, fire) -> bool:
    """Remove stale evidence, fire Fusion's deferred export, await the new PNG."""
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    fire()
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if path.is_file() and path.stat().st_size:
            return True
        time.sleep(0.05)
    return False


def _settle_eagle(bridge, command: str, seconds: float = 0.75) -> None:
    bridge.run_eagle(command)
    time.sleep(seconds)


def capture_visual_evidence(bridge, design: str, dpi: int = 300,
                            targets: list[dict] | None = None) -> dict | None:
    """Export every existing sheet and the board without invoking a model.

    Fusion writes on Windows. The defaults name the same shared directory as
    ``C:\\tmp\\hendley-visual`` in Fusion and ``~/tmp/hendley-visual`` in WSL.
    Failures are non-fatal
    because images enrich an otherwise valid design read.
    """
    local_dir = Path(os.environ.get("HENDLEY_VISUAL_DIR", DEFAULT_LOCAL_DIR)).expanduser()
    windows_dir = os.environ.get("HENDLEY_FUSION_VISUAL_DIR", DEFAULT_WINDOWS_DIR)
    try:
        local_dir.mkdir(parents=True, exist_ok=True)
        # Sheet entities are context-sensitive and read empty on the board.
        # Sheet 1 necessarily exists in a paired schematic; activate it before
        # enumerating, then never probe beyond the returned rows.
        bridge.run_eagle("EDIT .S1;")
        sheets = sorted(
            ({"number": int(row["number"]), "name": str(row.get("name") or ""),
              "description": str(row.get("description") or "")}
             for row in bridge.read_all("electronics.Sheet")
             if row.get("number") is not None),
            key=lambda row: row["number"],
        )
        if not sheets:
            return None
        stem = _slug(design)
        exported: list[Path] = []
        manifest_sheets: list[dict] = []
        for sheet in sheets:
            number = sheet["number"]
            filename = f"{stem}-sheet-{number}.png"
            _settle_eagle(bridge, f"EDIT .S{number}; WINDOW FIT;")
            path = local_dir / filename
            if _fresh_export(path, lambda: bridge.run_eagle(
                    f"EXPORT IMAGE {windows_dir}\\{filename} {dpi};")):
                exported.append(path)
                manifest_sheets.append({**sheet, "image": str(path.resolve())})
        # Airwires are routing state, not package evidence. They can cross the
        # target and make the model associate a nearby pad or footprint with it.
        board_name = f"{stem}-board.png"
        board_path = local_dir / board_name
        _settle_eagle(bridge, "BOARD; WINDOW FIT; DISPLAY -UNROUTED;")
        _fresh_export(board_path, lambda: bridge.run_eagle(
            f"EXPORT IMAGE {windows_dir}\\{board_name} {dpi};"))
        bridge.run_eagle("DISPLAY UNROUTED;")
        board_crops: list[dict] = []
        for target in targets or []:
            try:
                designator = str(target["designator"])
                x, y = float(target["x"]), float(target["y"])
            except (KeyError, TypeError, ValueError):
                continue
            half = 6.0
            crop_name = f"{stem}-board-{_slug(designator)}.png"
            crop_path = local_dir / crop_name
            _settle_eagle(
                bridge, f"BOARD; DISPLAY -UNROUTED; "
                f"WINDOW ({x - half:g} {y - half:g}) "
                f"({x + half:g} {y + half:g});")
            fresh = _fresh_export(crop_path, lambda: bridge.run_eagle(
                f"EXPORT IMAGE {windows_dir}\\{crop_name} {dpi};"))
            bridge.run_eagle("DISPLAY UNROUTED; WINDOW FIT;")
            if fresh:
                exported.append(crop_path)
                board_crops.append({"designator": designator,
                                    "image": str(crop_path.resolve()),
                                    "widthMm": half * 2, "heightMm": half * 2,
                                    "center": {"x": x, "y": y}})
        board_image = str(board_path.resolve()) if board_path.is_file() else None
        if board_image:
            exported.append(board_path)
        if not exported:
            return None
        metadata = {"schemaVersion": VISUAL_SCHEMA_VERSION, "design": design,
                    "dpi": dpi, "sheets": manifest_sheets,
                    "boardImage": board_image, "boardCrops": board_crops}
        return {**metadata, "images": [str(p.resolve()) for p in exported],
                "digest": _digest(exported, metadata)}
    except (OSError, TypeError, ValueError, KeyError, RuntimeError):
        return None
