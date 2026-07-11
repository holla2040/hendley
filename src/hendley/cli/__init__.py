"""Command-line interface for Hendley.

Examples::

    hendley detail C2040            # full detail for one or more component codes
    hendley private                 # your private/consigned JLC inventory
    hendley library --limit 50      # browse the assembly component library
    hendley ping                    # verify credentials + signing against the API

The command implementations live beside this module, grouped by concern:
:mod:`.catalog` (JLC catalog queries), :mod:`.manufacturing` (order files,
stock gate), :mod:`.migration` (Fusion ``.scr`` generation).
"""

from __future__ import annotations

import argparse
import sys
import urllib.error

from ..datasources.jlc.client import JLCClient, JLCError
from ..ingestion.fusion.bridge import BridgeError
from .catalog import cmd_alternates, cmd_detail, cmd_library, cmd_ping, cmd_private
from .manufacturing import cmd_fusion, cmd_pcba, cmd_stock
from .migration import cmd_scr


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="hendley", description="JLCPCB parts inventory client.")
    p.add_argument("--keys", help="Path to the .keys credentials file (overrides discovery).")
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("ping", help="Verify credentials and request signing.")
    sp.set_defaults(func=cmd_ping)

    sp = sub.add_parser("detail", help="Component detail by code (price tiers, stock, parameters).")
    sp.add_argument("codes", nargs="+", help="One or more JLC component codes, e.g. C2040.")
    sp.set_defaults(func=cmd_detail)

    sp = sub.add_parser("private", help="Your private/consigned inventory at JLCPCB.")
    sp.add_argument("--page", type=int, default=1)
    sp.add_argument("--limit", type=int, default=30)
    sp.set_defaults(func=cmd_private)

    sp = sub.add_parser("library", help="Browse the assembly component library.")
    sp.add_argument("--limit", type=int, default=30, help="Max rows to fetch.")
    sp.set_defaults(func=cmd_library)

    sp = sub.add_parser("fusion", help="Ingest a Fusion parts-export JSON and enrich via JLC.")
    sp.add_argument("parts_json", help="Path to the Fusion parts-export JSON file.")
    sp.add_argument("--no-enrich", action="store_true",
                    help="Parse and validate only; do not call the JLC API.")
    sp.set_defaults(func=cmd_fusion)

    sp = sub.add_parser("stock", help="Inventory check: flag out-of-stock/problem parts in a BOM.")
    sp.add_argument("parts_json", help="Path to a Fusion parts-export JSON file.")
    sp.add_argument("--min-stock", type=int, default=1,
                    help="Flag parts below this stock as LOW (default 1: only flag out-of-stock).")
    sp.add_argument("--json", action="store_true", help="Emit structured JSON instead of a report.")
    sp.set_defaults(func=cmd_stock)

    sp = sub.add_parser(
        "alternates",
        help="Discover alternate parts (jlcsearch) and verify them against the live JLC API.",
    )
    sp.add_argument("code", nargs="?", help="Target JLC component code to replace, e.g. C315567.")
    sp.add_argument("--category",
                    help="jlcsearch category slug (see --list-categories), e.g. mosfets.")
    sp.add_argument("--package",
                    help="Package filter (must match jlcsearch's exact string, e.g. 'DFN-8(3x3)').")
    sp.add_argument("-p", "--param", action="append", metavar="KEY=VALUE",
                    help="Extra jlcsearch query param (repeatable), e.g. -p resistance=220. "
                         "Numeric _min/_max params are unreliable (sparse columns) — prefer "
                         "filtering on the verified parameters yourself.")
    sp.add_argument("--top", type=int, default=20,
                    help="Max candidates to show in the report, in index order (0 = all).")
    sp.add_argument("--json", action="store_true", help="Emit the full structured result as JSON.")
    sp.add_argument("--list-categories", action="store_true",
                    help="List jlcsearch category slugs and exit.")
    sp.set_defaults(func=cmd_alternates)

    sp = sub.add_parser(
        "pcba",
        aliases=["jlc"],
        help="Generate JLCPCB PCBA order files (bom.csv + cpl.csv) from the live Fusion design.",
    )
    sp.add_argument("-o", "--outdir", default="~/tmp/hendley_output",
                    help="Directory for bom.csv + cpl.csv (default: ~/tmp/hendley_output).")
    sp.add_argument("--min-stock", type=int, default=1,
                    help="Flag parts below this stock as LOW (default 1: only flag out-of-stock).")
    sp.add_argument("--no-verify", action="store_true",
                    help="Skip the live JLC stock check (no credentials needed).")
    sp.add_argument("--fusion-host",
                    help="Fusion bridge host (default: HENDLEY_FUSION_HOST, else the WSL gateway).")
    sp.add_argument("--rotations",
                    help="Path to cpl-rotations.json (default: data/cpl-rotations.json, "
                         "found by walking up from the cwd).")
    sp.set_defaults(func=cmd_pcba)

    sp = sub.add_parser("scr", help="Generate a Fusion .scr migration script from swap files.")
    sp.add_argument("swaps_json", nargs="+",
                    help="One or more swap JSON files; merged into one combo script.")
    sp.add_argument("-o", "--output", help="Write the .scr here (default: stdout).")
    sp.add_argument("--design", help="Design name for the script header (else read from JSON).")
    sp.set_defaults(func=cmd_scr)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    from ..config import load_settings

    # Offline modes need no credentials: `scr` is pure generation; `fusion --no-enrich`
    # only parses.
    offline = (
        args.command == "scr"
        or (args.command == "fusion" and getattr(args, "no_enrich", False))
        or (args.command == "alternates" and getattr(args, "list_categories", False))
        or (args.command in ("pcba", "jlc") and getattr(args, "no_verify", False))
    )
    needs_client = not offline
    try:
        client = JLCClient(load_settings(args.keys)) if needs_client else None
        return args.func(client, args)
    except urllib.error.URLError as exc:
        print(f"error: cannot reach the Fusion bridge ({exc.reason}). Is Fusion running with "
              "the MCP Server enabled and the port-forward in place? See README "
              "\"Reading from Fusion Electronics\".", file=sys.stderr)
        return 1
    except (JLCError, BridgeError, FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
