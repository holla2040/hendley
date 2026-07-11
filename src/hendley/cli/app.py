"""The `hendley app` command — start the local web app (the primary interface)."""

from __future__ import annotations


def cmd_app(client, args) -> int:
    from ..app import HendleyApp, run_app

    app = HendleyApp(db_path=args.db, outdir=args.outdir,
                     fusion_host=args.fusion_host)
    run_app(app, port=args.port, open_browser=not args.no_browser)
    return 0
