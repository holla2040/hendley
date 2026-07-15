"""Manufacturing commands — fusion (parts-JSON ingest), stock, pcba."""

from __future__ import annotations

import sys

from .common import print_json


def cmd_fusion(client, args) -> int:
    """Ingest a Fusion parts-export JSON and (optionally) enrich against JLC."""
    from ..ingestion.fusion.parts_json import load_parts_json
    from ..reporting.stock import enrich_with_jlc

    parts = load_parts_json(args.parts_json)
    if args.no_enrich:
        print_json([
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
    print_json(enrich_with_jlc(parts, client))
    return 0


def cmd_stock(client, args) -> int:
    """Inventory check: flag out-of-stock / problem parts before a board submission."""
    from ..ingestion.fusion.parts_json import load_parts_json
    from ..reporting.stock import STOCK_BLOCKERS, check_stock, format_stock_report

    parts = load_parts_json(args.parts_json)
    rows = check_stock(parts, client, min_stock=args.min_stock)
    if args.json:
        print_json(rows)
    else:
        print(format_stock_report(rows, min_stock=args.min_stock))
    # Nonzero exit when any part is out of stock or missing from the catalog, so
    # this can gate a submission step (e.g. `hendley stock bom.json && submit`).
    return 1 if any(r["status"] in STOCK_BLOCKERS for r in rows) else 0


def cmd_bom(client, args) -> int:
    """Render a resolution JSON into the provider's upload BOM CSV."""
    from pathlib import Path

    from ..providers.jlcpcb.bom_csv import (
        blocking_checks,
        format_resolution_report,
        load_resolution_json,
        render_bom_csv,
    )

    if getattr(args, "provider", "jlcpcb") == "pcbway":
        return _cmd_bom_pcbway(args)

    design, production_quantity, lines, raw_doc = load_resolution_json(args.resolution_json)
    csv_text = render_bom_csv(lines)
    if args.output:
        Path(args.output).write_text(csv_text)
        rendered = sum(1 for x in lines if not x.dnp)
        print(f"wrote {rendered} BOM line(s) to {args.output}", file=sys.stderr)
    else:
        print(csv_text, end="")
    if args.report:
        print(format_resolution_report(design, lines, production_quantity),
              file=sys.stderr)
    blockers = blocking_checks(lines)
    if blockers:  # every blocker in one pass — no fix-one-class-rerun loop
        for line, check in blockers:
            print(f"error: {check['check']}: {check.get('message', '')}",
                  file=sys.stderr)
        print(f"error: {len(blockers)} blocker(s) — do not upload this BOM.",
              file=sys.stderr)
        return 1
    # Clean emit to a file → record the immutable fact of what was ordered.
    if args.output and not args.no_snapshot:
        from ..reporting.snapshot import write_release_snapshot

        snap = write_release_snapshot(raw_doc, args.output)
        print(f"release snapshot: {snap}", file=sys.stderr)
    return 0


def _cmd_bom_pcbway(args) -> int:
    """PCBWay render path: MPN-based BOM, same gate/snapshot semantics."""
    import json
    from pathlib import Path

    from ..providers.pcbway.adapter import PCBWayAdapter, render_pcbway_csv

    raw_doc = json.loads(Path(args.resolution_json).read_text())
    if not isinstance(raw_doc, dict):
        raw_doc = {"lines": raw_doc}
    csv_text = render_pcbway_csv(raw_doc)
    if args.output:
        Path(args.output).write_text(csv_text)
        rendered = sum(1 for x in raw_doc.get("lines") or [] if not x.get("dnp"))
        print(f"wrote {rendered} BOM line(s) to {args.output}", file=sys.stderr)
    else:
        print(csv_text, end="")
    blockers = PCBWayAdapter().validate(raw_doc)
    if blockers:
        for check in blockers:
            print(f"error: {check.check}: {check.message}", file=sys.stderr)
        print(f"error: {len(blockers)} blocker(s) — do not upload this BOM.",
              file=sys.stderr)
        return 1
    if args.output and not args.no_snapshot:
        from ..reporting.snapshot import write_release_snapshot

        snap = write_release_snapshot(raw_doc, args.output)
        print(f"release snapshot: {snap}", file=sys.stderr)
    return 0


def cmd_pcba(client, args) -> int:
    """Generate the JLCPCB PCBA order files (bom.csv + cpl.csv) from the live design.

    The pcba fast path: live extraction → Requirements BOM (normalizer) → an
    explicit-ref resolution document → the JLCPCB adapter. No knowledge-store
    resolution here — the design's own LCSC attributes are the picks.
    """
    from pathlib import Path

    from ..ingestion.fusion import bridge as bridge_mod
    from ..ingestion.fusion.live_design import extract_board, extract_schematic, is_dnp
    from ..providers.jlcpcb.adapter import JLCPCBAdapter
    from ..providers.jlcpcb.order_files import find_rotations_file
    from ..reporting.stock import STOCK_BLOCKERS, check_stock, format_stock_report
    from ..requirements import requirements_from_design

    bridge = bridge_mod.FusionBridge(host=args.fusion_host)
    design, parts = extract_schematic(bridge)  # must run before the one-way BOARD; switch
    print(f"design '{design}': {len(parts)} part(s) read from the schematic", file=sys.stderr)
    placements = extract_board(bridge)
    print(f"{len(placements)} placement(s) read from the board "
          "(Fusion's engine is now on the board context)", file=sys.stderr)

    dnp = [p.designator for p in parts if is_dnp(p)]
    if dnp:
        print(f"DNP (excluded from BOM, CPL, and stock check): {', '.join(dnp)}",
              file=sys.stderr)

    placed = {p.designator for p in placements}
    unplaced = [p.designator for p in parts if p.designator not in placed]
    orphans = sorted(placed - {p.designator for p in parts})
    if unplaced:
        print(f"warning: in schematic but not on board: {', '.join(unplaced)}", file=sys.stderr)
    if orphans:
        print(f"warning: on board but not in schematic: {', '.join(orphans)}", file=sys.stderr)

    if find_rotations_file(args.rotations) is None:
        print("warning: no data/cpl-rotations.json found — CPL carries raw Fusion angles",
              file=sys.stderr)

    requirements = requirements_from_design(design, parts, 1, placements)
    unresolved_families = [
        ln for ln in requirements.lines
        if ln.family and not ln.dnp and not ln.provider_ref("jlcpcb")
    ]
    if unresolved_families:
        for line in unresolved_families:
            print(
                "error: " + ",".join(line.designators) +
                f" names family “{line.family}” on {line.footprint or 'an unknown land'}; "
                "no exact approved part has been selected",
                file=sys.stderr,
            )
        print(
            "error: family selection is an engineering decision — use `hendley app` "
            "to search and approve each part before generating order files.",
            file=sys.stderr,
        )
        return 1
    resolution = {
        "design": design,
        "productionQuantity": 1,
        "provider": "jlcpcb",
        "lines": [
            {
                "designators": ln.designators,
                "comment": ln.comment,
                "footprint": ln.footprint,
                "ref": ln.provider_ref("jlcpcb"),
                "mpn": ln.mpn,
                "manufacturer": ln.manufacturer,
                "dnp": ln.dnp,
                "quantityPer": ln.quantity_per,
                "source": "explicit" if ln.provider_ref("jlcpcb") else None,
            }
            for ln in requirements.lines
        ],
        "placements": [
            {"designator": p.designator, "x": p.x, "y": p.y, "angle": p.angle,
             "mirror": p.mirror, "populate": p.populate, "footprint": p.footprint}
            for p in placements
        ],
    }

    outdir = Path(args.outdir).expanduser()
    paths = JLCPCBAdapter().export(
        resolution, outdir, rotations=args.rotations,
        on_note=lambda msg: print(msg, file=sys.stderr))
    counts = [max(0, sum(1 for _ in p.open()) - 1) for p in paths]
    print(f"wrote {paths[0]} ({counts[0]} lines) and "
          f"{paths[1]} ({counts[1]} placements)", file=sys.stderr)

    if args.no_verify:
        return 0
    rows = check_stock([p for p in parts if not is_dnp(p)], client, min_stock=args.min_stock)
    print(format_stock_report(rows, min_stock=args.min_stock))
    # Same gate as `stock`: nonzero exit when a part would block the order.
    return 1 if any(r["status"] in STOCK_BLOCKERS for r in rows) else 0
