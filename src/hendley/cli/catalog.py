"""Catalog commands — ping, detail, private, library, alternates."""

from __future__ import annotations

import sys

from ..datasources.jlc.client import JLCClient, JLCError
from .common import print_json


def cmd_ping(client: JLCClient, args) -> int:
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


def cmd_detail(client: JLCClient, args) -> int:
    data = client.get_component_detail_by_code(args.codes)
    print_json(data)
    return 0


def cmd_private(client: JLCClient, args) -> int:
    data = client.get_private_component_library(current_page=args.page, page_size=args.limit)
    print_json(data)
    return 0


def cmd_library(client: JLCClient, args) -> int:
    out = []
    for i, row in enumerate(client.iter_component_library(page_size=min(args.limit, 100))):
        if i >= args.limit:
            break
        out.append(row)
    print_json(out)
    return 0


def cmd_alternates(client: JLCClient, args) -> int:
    """Discover alternate parts (jlcsearch) and verify them against the live JLC API."""
    from ..datasources.jlc.alternates import (
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
        print_json(result)
    else:
        print(format_alternates_report(result, top=(args.top or None)))
    return 0
