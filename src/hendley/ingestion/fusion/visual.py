"""Best-effort schematic and board image capture for lazy interpretation."""

from __future__ import annotations

import hashlib
import json
import os
import re
import struct
import time
import zlib
from pathlib import Path

VISUAL_SCHEMA_VERSION = 3
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
            _recompress_png(path)
            return True
        time.sleep(0.05)
    return False


def _recompress_png(path: Path) -> None:
    """Losslessly recompress Fusion's unusually large PNG exports in place.

    Fusion emits normal PNG scanlines but uses little effective DEFLATE
    compression: one schematic sheet can exceed 25 MB and a multi-sheet Codex
    request can be rejected before inference. Recompress the existing IDAT
    stream without decoding or changing a pixel. Unknown/malformed PNGs stay
    untouched so visual capture remains best-effort.
    """
    try:
        data = path.read_bytes()
        if not data.startswith(b"\x89PNG\r\n\x1a\n"):
            return
        pos = 8
        chunks: list[tuple[bytes, bytes]] = []
        idat = bytearray()
        first_idat: int | None = None
        while pos + 12 <= len(data):
            size = struct.unpack(">I", data[pos:pos + 4])[0]
            kind = data[pos + 4:pos + 8]
            end = pos + 12 + size
            if end > len(data):
                return
            payload = data[pos + 8:pos + 8 + size]
            if kind == b"IDAT":
                if first_idat is None:
                    first_idat = len(chunks)
                idat.extend(payload)
            else:
                chunks.append((kind, payload))
            pos = end
            if kind == b"IEND":
                break
        if first_idat is None or not idat:
            return
        packed = zlib.compress(zlib.decompress(bytes(idat)), level=9)
        chunks.insert(first_idat, (b"IDAT", packed))
        out = bytearray(data[:8])
        for kind, payload in chunks:
            out.extend(struct.pack(">I", len(payload)))
            out.extend(kind)
            out.extend(payload)
            out.extend(struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF))
        if len(out) < len(data):
            path.write_bytes(out)
    except (OSError, ValueError, zlib.error, struct.error):
        return


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
        _settle_eagle(bridge, "EDIT .S1;")
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


def add_board_crops(bridge, manifest: dict | None,
                    targets: list[dict]) -> dict | None:
    """Add dimensioned crops while Fusion is already in board context.

    Refresh captures sheets before its one-way BOARD transition, then learns
    placement coordinates from the board. This second phase deliberately never
    calls EDIT: some Fusion MCP builds wedge their script proxy when asked to
    return from board to schematic.
    """
    if not manifest:
        return None
    local_dir = Path(os.environ.get("HENDLEY_VISUAL_DIR", DEFAULT_LOCAL_DIR)).expanduser()
    windows_dir = os.environ.get("HENDLEY_FUSION_VISUAL_DIR", DEFAULT_WINDOWS_DIR)
    stem = _slug(str(manifest.get("design") or "design"))
    dpi = int(manifest.get("dpi") or 300)
    crops: list[dict] = []
    try:
        for target in targets:
            try:
                designator = str(target["designator"])
                x, y = float(target["x"]), float(target["y"])
            except (KeyError, TypeError, ValueError):
                continue
            half = 6.0
            filename = f"{stem}-board-{_slug(designator)}.png"
            path = local_dir / filename
            _settle_eagle(
                bridge, f"BOARD; DISPLAY -UNROUTED; "
                f"WINDOW ({x - half:g} {y - half:g}) "
                f"({x + half:g} {y + half:g});")
            fresh = _fresh_export(path, lambda: bridge.run_eagle(
                f"EXPORT IMAGE {windows_dir}\\{filename} {dpi};"))
            bridge.run_eagle("DISPLAY UNROUTED; WINDOW FIT;")
            if fresh:
                crops.append({"designator": designator,
                              "image": str(path.resolve()),
                              "widthMm": half * 2, "heightMm": half * 2,
                              "center": {"x": x, "y": y}})
        metadata = {k: v for k, v in manifest.items()
                    if k not in ("images", "digest", "boardCrops")}
        metadata["boardCrops"] = crops
        paths = [Path(str(s["image"])) for s in metadata.get("sheets", [])
                 if s.get("image")]
        if metadata.get("boardImage"):
            paths.append(Path(str(metadata["boardImage"])))
        paths.extend(Path(c["image"]) for c in crops)
        paths = [p for p in paths if p.is_file()]
        return {**metadata, "images": [str(p.resolve()) for p in paths],
                "digest": _digest(paths, metadata)}
    except (OSError, TypeError, ValueError, KeyError, RuntimeError):
        return manifest
