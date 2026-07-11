"""The Hendley app — the primary interface (ADR-0003/0004).

A local, stdlib-only web app: `hendley app` serves a single page on
127.0.0.1 whose every action is a JSON API call mapping 1:1 onto a library
function. No business logic lives here — the app renders the versioned
documents (Requirements BOM, resolution, approval queue, snapshots) and
writes decisions through the knowledge store.
"""

from .server import HendleyApp, run_app

__all__ = ["HendleyApp", "run_app"]
