"""Knowledge commands — the house-parts db surface and the resolver."""

from __future__ import annotations

import json
import sys

from .common import print_json


def cmd_db_lookup(client, args) -> int:
    """Look up the House Part (ranked choices) and audit history for one spec key."""
    from ..knowledge.partsdb import history, lookup, open_db

    conn = open_db(args.db)
    print_json({
        "housePart": lookup(conn, args.kind, args.value, args.package, args.qualifier),
        "history": history(conn, args.kind, args.value, args.package, args.qualifier),
    })
    return 0


def cmd_db_record(client, args) -> int:
    """Approve a part as a ranked choice for a spec (default rank 1 = promotion)."""
    from ..knowledge.partsdb import open_db, record

    conn = open_db(args.db)
    row = record(
        conn, args.kind, args.value, args.package, qualifier=args.qualifier,
        lcsc=args.lcsc, mpn=args.mpn, manufacturer=args.manufacturer,
        description=args.description, design=args.design, note=args.note,
        rank=args.rank,
    )
    print_json(row)
    return 0


def cmd_db_rerank(client, args) -> int:
    """Move an active choice to a new rank on its spec's AVL."""
    from ..knowledge.partsdb import open_db, rerank

    conn = open_db(args.db)
    print_json(rerank(conn, args.kind, args.value, args.package, args.ref, args.rank,
                      qualifier=args.qualifier, note=args.note))
    return 0


def cmd_db_remove(client, args) -> int:
    """Remove a choice from its spec's AVL (state change; the row is kept)."""
    from ..knowledge.partsdb import open_db, remove_choice

    conn = open_db(args.db)
    print_json(remove_choice(conn, args.kind, args.value, args.package, args.ref,
                             qualifier=args.qualifier, note=args.note))
    return 0


def cmd_db_list(client, args) -> int:
    from ..knowledge.partsdb import list_parts, open_db

    print_json(list_parts(open_db(args.db), kind=args.kind))
    return 0


def cmd_db_refresh(client, args) -> int:
    """Batch live-verify every active part choice; update the advisory cache."""
    from ..datasources.jlc.source import JLCDataSource
    from ..knowledge.partsdb import list_parts, open_db, update_verified
    from ..resolver.orchestration.resolve import _tier_price_at

    conn = open_db(args.db)
    codes = sorted({c["providerRefs"].get("jlcpcb")
                    for p in list_parts(conn) for c in p["choices"]
                    if c["providerRefs"].get("jlcpcb")})
    if not codes:
        print("house-parts DB has no JLC-coded choices — nothing to refresh.")
        return 0
    facts = JLCDataSource(client).verify(codes)
    found = 0
    out, missing = [], []
    for code in codes:
        fact = facts.get(code)
        if fact is not None and fact.found:
            found += 1
            update_verified(conn, code, fact.stock, _tier_price_at(fact, 1),
                            mpn=fact.mpn, manufacturer=fact.manufacturer)
            if (fact.stock or 0) <= 0:
                out.append(code)
        else:
            missing.append(code)
    print(f"Refreshed {found}/{len(codes)} house part(s).")
    if out:
        print(f"OUT OF STOCK: {', '.join(out)}")
    if missing:
        print(f"NOT FOUND in JLC catalog: {', '.join(missing)}")
    return 0


def cmd_resolve(client, args) -> int:
    """Rank-walk a Requirements BOM's lines against the AVLs + live stock."""
    from pathlib import Path

    from ..datasources.jlc.source import JLCDataSource
    from ..knowledge.partsdb import PartsDb
    from ..providers.jlcpcb.strategy import JLCPCBStrategy
    from ..resolver.orchestration.resolve import (
        format_escalation_report,
        load_request_json,
        resolve,
    )

    requirements = load_request_json(args.request_json)
    store = PartsDb(args.db)
    datasource, strategy = JLCDataSource(client), JLCPCBStrategy()
    result = resolve(store, requirements, datasource=datasource, strategy=strategy)
    text = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(text + "\n")
    else:
        print(text)
    print(format_escalation_report(result), file=sys.stderr)
    if result["escalations"] and args.queue:
        from ..resolver.orchestration.queue import build_approval_queue

        queue = build_approval_queue(store, requirements, result,
                                     datasource=datasource, strategy=strategy)
        Path(args.queue).write_text(
            json.dumps(queue, indent=2, ensure_ascii=False) + "\n")
        print(f"approval queue ({len(queue['entries'])} entr(y/ies)): {args.queue}",
              file=sys.stderr)
    return 1 if result["escalations"] else 0
