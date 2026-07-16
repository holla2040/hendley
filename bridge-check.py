#!/usr/bin/env python3
"""Check that Hendley can communicate with Fusion's Electronics bridge."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path


# Allow this script to run from a source checkout without installing Hendley.
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from hendley.ingestion.fusion.bridge import DEFAULT_PORT, FusionBridge  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--host",
        help="Fusion host (default: HENDLEY_FUSION_HOST or the WSL gateway)",
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--timeout", type=int, default=10)
    parser.add_argument(
        "--settle",
        type=float,
        default=1.0,
        help="seconds to wait after changing Fusion context (default: 1.0)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    bridge = FusionBridge(host=args.host, port=args.port, timeout=args.timeout)
    started_on_board = False

    try:
        print(f"Checking {bridge.url} ...")

        # These reads also perform and validate the initialize handshake.
        parts = bridge.read_all("electronics.Part")
        elements = bridge.read_all("electronics.Element")
        started_on_board = bool(elements) and not parts

        print("PASS  MCP session established")
        print(f"INFO  active context: {'board' if started_on_board else 'schematic'}")

        if started_on_board:
            print(f"PASS  board read returned {len(elements)} elements")

            command = bridge.run_eagle("EDIT .S1;")
            if not command.get("success"):
                raise RuntimeError(f"EDIT .S1 command failed: {command!r}")
            time.sleep(args.settle)

            sheets = bridge.read_all("electronics.Sheet")
            parts = bridge.read_all("electronics.Part")
            if not sheets or not parts:
                raise RuntimeError(
                    f"schematic read was empty ({len(sheets)} sheets, {len(parts)} parts)"
                )
            print(f"PASS  schematic read returned {len(sheets)} sheets and {len(parts)} parts")
        else:
            sheets = bridge.read_all("electronics.Sheet")
            if not sheets or not parts:
                raise RuntimeError(
                    f"schematic read was empty ({len(sheets)} sheets, {len(parts)} parts)"
                )
            print(f"PASS  schematic read returned {len(sheets)} sheets and {len(parts)} parts")

        print("PASS  Fusion bridge is running correctly")
        return 0
    except Exception as exc:
        print(f"FAIL  {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    finally:
        if started_on_board:
            try:
                restored = bridge.run_eagle("BOARD;")
                time.sleep(args.settle)
                if not restored.get("success"):
                    print("WARN  could not restore the board view", file=sys.stderr)
                else:
                    print("INFO  restored board view")
            except Exception as exc:
                print(f"WARN  could not restore the board view: {exc}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
