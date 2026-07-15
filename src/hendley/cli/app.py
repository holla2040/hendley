"""The `hendley app` command — start the local web app (the primary interface)."""

from __future__ import annotations


def cmd_app(client, args) -> int:
    from ..app import HendleyApp, run_app
    from ..app.server import _default_interpreter, interpreter_description

    app = HendleyApp(db_path=args.db, outdir=args.outdir,
                     fusion_host=args.fusion_host,
                     interpreter_factory=(
                         (lambda: _default_interpreter(args.interpreter))
                         if args.interpreter else None))
    run_app(app, port=args.port, open_browser=not args.no_browser,
            interpreter=interpreter_description(args.interpreter))
    return 0
