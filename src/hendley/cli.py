"""Command-line interface for Hendley.

Examples::

    hendley detail C2040            # full detail for one or more component codes
    hendley private                 # your private/consigned JLC inventory
    hendley library --limit 50      # browse the assembly component library
    hendley ping                    # verify credentials + signing against the API
"""

from __future__ import annotations

import argparse
import json
import sys

from .client import JLCClient, JLCError


def _print(obj) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False))


def _cmd_ping(client: JLCClient, args) -> int:
    """Verify credentials + signing. Distinguishes auth vs. permission state."""
    try:
        data = client.get_component_library_list(page_size=1)
    except JLCError as exc:
        if exc.code in (403, "403"):
            print(
                "Signing OK — request authenticated, but this app lacks the component "
                "API permission.\nEnable it for your app in the JLC console "
                "(api.jlcpcb.com), then retry."
            )
            return 0  # auth works; permission is an account-side toggle
        if exc.code in (401, "401"):
            print("Signature REJECTED (401). Check the AppID/Accesskey/SecretKey in .keys.")
            return 1
        raise
    rows = (data or {}).get("componentLibraryInfoVOS") or []
    print(f"OK — signed request accepted; library returned {len(rows)} row(s) on page 1.")
    return 0


def _cmd_detail(client: JLCClient, args) -> int:
    data = client.get_component_detail_by_code(args.codes)
    _print(data)
    return 0


def _cmd_private(client: JLCClient, args) -> int:
    data = client.get_private_component_library(current_page=args.page, page_size=args.limit)
    _print(data)
    return 0


def _cmd_library(client: JLCClient, args) -> int:
    out = []
    for i, row in enumerate(client.iter_component_library(page_size=min(args.limit, 100))):
        if i >= args.limit:
            break
        out.append(row)
    _print(out)
    return 0


def _cmd_fusion(client: JLCClient, args) -> int:
    """Ingest a Fusion parts-export JSON and (optionally) enrich against JLC."""
    from .fusion import enrich_with_jlc, load_parts_json

    parts = load_parts_json(args.parts_json)
    if args.no_enrich:
        _print([
            {
                "designator": p.designator,
                "manufacturerPart": p.manufacturer_part,
                "jlcCode": p.jlc_code,
                "value": p.value,
                "package": p.package,
                "quantity": p.quantity,
            }
            for p in parts
        ])
        print(f"\n{len(parts)} part(s) parsed; "
              f"{sum(1 for p in parts if p.jlc_code)} carry a JLC code.", file=sys.stderr)
        return 0
    _print(enrich_with_jlc(parts, client))
    return 0


def _cmd_stock(client: JLCClient, args) -> int:
    """Inventory check: flag out-of-stock / problem parts before a board submission."""
    from .fusion import STOCK_BLOCKERS, check_stock, format_stock_report, load_parts_json

    parts = load_parts_json(args.parts_json)
    rows = check_stock(parts, client, min_stock=args.min_stock)
    if args.json:
        _print(rows)
    else:
        print(format_stock_report(rows, min_stock=args.min_stock))
    # Nonzero exit when any part is out of stock or missing from the catalog, so
    # this can gate a submission step (e.g. `hendley stock bom.json && submit`).
    return 1 if any(r["status"] in STOCK_BLOCKERS for r in rows) else 0


def _cmd_alternates(client: JLCClient, args) -> int:
    """Discover alternate parts (jlcsearch) and verify them against the live JLC API."""
    from .alternates import (
        CATEGORIES,
        discover_and_verify,
        format_alternates_report,
        parse_param_args,
    )

    if args.list_categories:
        print("\n".join(CATEGORIES))
        return 0
    if not args.code:
        print("error: a target component code is required (e.g. C315567)", file=sys.stderr)
        return 1
    if not args.category:
        print("error: --category is required (see --list-categories)", file=sys.stderr)
        return 1

    params = parse_param_args(args.param or [])
    if args.package:
        params.setdefault("package", args.package)

    result = discover_and_verify(args.code, args.category, params, client)
    if args.json:
        _print(result)
    else:
        print(format_alternates_report(result, top=(args.top or None)))
    return 0


def _cmd_scr(client, args) -> int:
    """Generate a Fusion ``.scr`` migration script from one or more swap files."""
    from pathlib import Path

    from .scr import load_swaps_json, render_script

    swaps = []
    design = args.design
    for path in args.swaps_json:
        swaps.extend(load_swaps_json(path))
        if design is None:  # pick up "design" from the first file that names one
            doc = json.loads(Path(path).read_text())
            if isinstance(doc, dict) and doc.get("design"):
                design = str(doc["design"])

    script = render_script(swaps, design=design)
    if args.output:
        Path(args.output).write_text(script)
        print(f"wrote {len(swaps)} swap(s) to {args.output}", file=sys.stderr)
        print("run it in Fusion: File > Execute Script  (Electronics workspace active),\n"
              "or in the text command line (Py): "
              f'import neu_dev; neu_dev.run_text_command("SCRIPT {args.output}")',
              file=sys.stderr)
    else:
        print(script, end="")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="hendley", description="JLCPCB parts inventory client.")
    p.add_argument("--keys", help="Path to the .keys credentials file (overrides discovery).")
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("ping", help="Verify credentials and request signing.")
    sp.set_defaults(func=_cmd_ping)

    sp = sub.add_parser("detail", help="Component detail by code (price tiers, stock, parameters).")
    sp.add_argument("codes", nargs="+", help="One or more JLC component codes, e.g. C2040.")
    sp.set_defaults(func=_cmd_detail)

    sp = sub.add_parser("private", help="Your private/consigned inventory at JLCPCB.")
    sp.add_argument("--page", type=int, default=1)
    sp.add_argument("--limit", type=int, default=30)
    sp.set_defaults(func=_cmd_private)

    sp = sub.add_parser("library", help="Browse the assembly component library.")
    sp.add_argument("--limit", type=int, default=30, help="Max rows to fetch.")
    sp.set_defaults(func=_cmd_library)

    sp = sub.add_parser("fusion", help="Ingest a Fusion parts-export JSON and enrich via JLC.")
    sp.add_argument("parts_json", help="Path to the Fusion parts-export JSON file.")
    sp.add_argument("--no-enrich", action="store_true",
                    help="Parse and validate only; do not call the JLC API.")
    sp.set_defaults(func=_cmd_fusion)

    sp = sub.add_parser("stock", help="Inventory check: flag out-of-stock/problem parts in a BOM.")
    sp.add_argument("parts_json", help="Path to a Fusion parts-export JSON file.")
    sp.add_argument("--min-stock", type=int, default=1,
                    help="Flag parts below this stock as LOW (default 1: only flag out-of-stock).")
    sp.add_argument("--json", action="store_true", help="Emit structured JSON instead of a report.")
    sp.set_defaults(func=_cmd_stock)

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
    sp.set_defaults(func=_cmd_alternates)

    sp = sub.add_parser("scr", help="Generate a Fusion .scr migration script from swap files.")
    sp.add_argument("swaps_json", nargs="+",
                    help="One or more swap JSON files; merged into one combo script.")
    sp.add_argument("-o", "--output", help="Write the .scr here (default: stdout).")
    sp.add_argument("--design", help="Design name for the script header (else read from JSON).")
    sp.set_defaults(func=_cmd_scr)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    from .config import load_settings

    # Offline modes need no credentials: `scr` is pure generation; `fusion --no-enrich`
    # only parses.
    offline = (
        args.command == "scr"
        or (args.command == "fusion" and getattr(args, "no_enrich", False))
        or (args.command == "alternates" and getattr(args, "list_categories", False))
    )
    needs_client = not offline
    try:
        client = JLCClient(load_settings(args.keys)) if needs_client else None
        return args.func(client, args)
    except (JLCError, FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
