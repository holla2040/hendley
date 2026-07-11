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
from .knowledge import (
    cmd_db_list,
    cmd_db_lookup,
    cmd_db_record,
    cmd_db_refresh,
    cmd_db_remove,
    cmd_db_rerank,
    cmd_resolve,
)
from .manufacturing import cmd_bom, cmd_fusion, cmd_pcba, cmd_stock
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

    sp = sub.add_parser("db", help="House-parts database: Hendley's spec → chosen-part memory.")
    dbsub = sp.add_subparsers(dest="db_action", required=True)

    def _spec_args(parser) -> None:
        parser.add_argument("--db", help="Path to the house-parts DB "
                            "(default: $HENDLEY_DB or ~/.hendley/parts.db).")
        parser.add_argument("--kind", required=True,
                            help="Canonical part kind, e.g. resistor, capacitor.")
        parser.add_argument("--value", required=True,
                            help="Canonical value string, e.g. 22k, 100n.")
        parser.add_argument("--package", required=True, help="Package, e.g. 0603.")
        parser.add_argument("--qualifier", default="",
                            help="Beyond-house-default spec, e.g. '100V', '1%%' "
                                 "(default: none = the house default).")

    d = dbsub.add_parser("lookup", help="House Part with ranked choices (the AVL) "
                                        "+ audit history for one spec.")
    _spec_args(d)
    d.set_defaults(func=cmd_db_lookup)

    d = dbsub.add_parser("record", help="Approve a part as a ranked choice for a spec "
                                        "(default rank 1 = promotion; existing choices "
                                        "shift down, staying approved).")
    _spec_args(d)
    d.add_argument("--lcsc", help="Chosen part's LCSC code, e.g. C31850.")
    d.add_argument("--mpn", help="Manufacturer part number (the neutral identity).")
    d.add_argument("--rank", type=int, default=1,
                   help="Rank on the AVL (1 = tried first; out-of-range appends; "
                        "default 1).")
    d.add_argument("--manufacturer", help="Manufacturer display name.")
    d.add_argument("--description", help="Part description.")
    d.add_argument("--design", help="Design that triggered this pick.")
    d.add_argument("--note", help="Why this pick, e.g. 'C31850 out of stock 2026-07-09'.")
    d.set_defaults(func=cmd_db_record)

    d = dbsub.add_parser("rerank", help="Move an active choice to a new rank on its AVL.")
    _spec_args(d)
    d.add_argument("--lcsc", "--ref", dest="ref", required=True,
                   help="The choice's LCSC code (or MPN).")
    d.add_argument("--rank", type=int, required=True, help="New rank (1 = tried first).")
    d.add_argument("--note", help="Why the re-rank.")
    d.set_defaults(func=cmd_db_rerank)

    d = dbsub.add_parser("remove", help="Remove a choice from its AVL "
                                        "(state change, audited; the row is kept).")
    _spec_args(d)
    d.add_argument("--lcsc", "--ref", dest="ref", required=True,
                   help="The choice's LCSC code (or MPN).")
    d.add_argument("--note", help="Why the removal, e.g. 'EOL' or 'failed in rev B'.")
    d.set_defaults(func=cmd_db_remove)

    d = dbsub.add_parser("list", help="All House Parts with their ranked choices.")
    d.add_argument("--db", help="Path to the house-parts DB.")
    d.add_argument("--kind", help="Filter by kind, e.g. resistor.")
    d.set_defaults(func=cmd_db_list)

    d = dbsub.add_parser("refresh", help="Batch live-verify all active part choices "
                                         "(the only db action that hits the API).")
    d.add_argument("--db", help="Path to the house-parts DB.")
    d.set_defaults(func=cmd_db_refresh)

    sp = sub.add_parser(
        "resolve",
        help="Resolve a Requirements BOM against the house AVLs + live stock "
             "(rank-walk; silent substitution; escalations to stderr, exit 1).")
    sp.add_argument("request_json", help="Requirements BOM / resolve request JSON "
                                         "(contract in hendley.domain.model).")
    sp.add_argument("-o", "--output", help="Write the resolution JSON here "
                                           "(default: stdout).")
    sp.add_argument("--db", help="Path to the house-parts DB "
                                 "(default: $HENDLEY_DB or ~/.hendley/parts.db).")
    sp.add_argument("--queue", help="On escalations, also write the batched approval "
                                    "queue (discovered + verified + ranked candidates "
                                    "per escalated line) to this JSON file.")
    sp.add_argument("--provider", choices=("jlcpcb", "pcbway"), default="jlcpcb",
                    help="Provider strategy (default jlcpcb). pcbway resolves to "
                         "MPN identities, honestly unverified (no live stock source).")
    sp.set_defaults(func=cmd_resolve)

    sp = sub.add_parser("bom", help="Render a resolution JSON into the JLCPCB upload BOM CSV.")
    sp.add_argument("resolution_json", help="Path to the resolution JSON.")
    sp.add_argument("-o", "--output", help="Write the CSV here (default: stdout).")
    sp.add_argument("--report", action="store_true",
                    help="Also print the human-readable resolution report (to stderr).")
    sp.add_argument("--no-snapshot", action="store_true",
                    help="Skip the release snapshot a clean -o emit writes beside "
                         "the CSV (the immutable what-was-ordered record).")
    sp.add_argument("--provider", choices=("jlcpcb", "pcbway"), default="jlcpcb",
                    help="Upload format (default jlcpcb: LCSC-coded CSV; pcbway: "
                         "MPN-based template).")
    sp.set_defaults(func=cmd_bom)

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

    # Offline modes need no credentials: `scr`/`bom` are pure generation; `fusion
    # --no-enrich` only parses; `db` is local SQLite except `db refresh` (live verify).
    offline = (
        args.command == "scr"
        or args.command == "bom"
        or (args.command == "db" and getattr(args, "db_action", None) != "refresh")
        or (args.command == "fusion" and getattr(args, "no_enrich", False))
        or (args.command == "alternates" and getattr(args, "list_categories", False))
        or (args.command in ("pcba", "jlc") and getattr(args, "no_verify", False))
        # pcbway has no live stock source — resolution never calls the JLC API
        or (args.command == "resolve" and getattr(args, "provider", "") == "pcbway")
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
