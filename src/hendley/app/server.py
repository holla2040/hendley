"""The app's HTTP layer — stdlib http.server, JSON API over library calls.

Bound to 127.0.0.1 only (ADR-0004: same trust model as the CLI on the same
machine). SQLite connections don't cross threads, so every request opens a
short-lived PartsDb — cheap, and migrations are idempotent.

Endpoints (all JSON):

- ``GET  /``                      — the app page
- ``GET  /api/parts[?kind=]``     — House Parts with ranked choices
- ``GET  /api/part?kind&value&package[&qualifier]`` — one part + audit history
- ``POST /api/record``            — approve a Part Choice (deliberate rank)
- ``POST /api/rerank``            — move a choice on its AVL
- ``POST /api/remove``            — remove a choice (state change)
- ``POST /api/refresh``           — live-verify every JLC-coded choice
- ``POST /api/intake``            — read the open Fusion design → Requirements BOM
- ``POST /api/resolve``           — resolve a Requirements BOM (+ approval queue)
- ``POST /api/approve``           — record queue answers to the knowledge store
- ``POST /api/emit``              — gate + export order files (+ snapshot when clean)
- ``GET  /api/snapshots``         — release snapshots in the output dir
- ``GET  /api/snapshot?name=``    — one snapshot document
"""

from __future__ import annotations

import json
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from ..domain.model import RequirementsBom, SpecKey
from ..knowledge.partsdb import PartsDb
from .ui import PAGE_HTML

DEFAULT_OUTDIR = "~/tmp/hendley_output"


class ApiError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _default_datasource():
    from ..config import load_settings
    from ..datasources.jlc.client import JLCClient
    from ..datasources.jlc.source import JLCDataSource

    try:
        return JLCDataSource(JLCClient(load_settings(None)))
    except FileNotFoundError as exc:
        raise ApiError(f"live JLC access needs credentials: {exc}", status=503)


def _default_bridge(host: str | None):
    from ..ingestion.fusion.bridge import FusionBridge

    return FusionBridge(host=host)


class HendleyApp:
    """The API surface — every method is a thin wrapper over the library."""

    def __init__(self, db_path=None, outdir: str | Path = DEFAULT_OUTDIR,
                 fusion_host: str | None = None,
                 datasource_factory=None, bridge_factory=None):
        self.db_path = db_path
        self.outdir = Path(outdir).expanduser()
        self.fusion_host = fusion_host
        self._datasource_factory = datasource_factory or _default_datasource
        self._bridge_factory = bridge_factory or _default_bridge

    def _store(self) -> PartsDb:
        return PartsDb(self.db_path)

    def _strategy(self, provider: str):
        if provider == "pcbway":
            from ..providers.pcbway.strategy import PCBWayStrategy

            return PCBWayStrategy()
        if provider == "jlcpcb":
            from ..providers.jlcpcb.strategy import JLCPCBStrategy

            return JLCPCBStrategy()
        raise ApiError(f"unknown provider {provider!r}")

    @staticmethod
    def _spec(params: dict) -> SpecKey:
        try:
            return SpecKey(kind=params["kind"], value=params["value"],
                           package=params["package"],
                           qualifier=params.get("qualifier") or "")
        except (KeyError, ValueError) as exc:
            raise ApiError(f"bad spec: {exc}")

    # -- knowledge -----------------------------------------------------------

    def api_parts(self, params: dict) -> dict:
        return {"parts": self._store().list_parts(kind=params.get("kind") or None)}

    def api_part(self, params: dict) -> dict:
        spec = self._spec(params)
        store = self._store()
        return {"housePart": store.lookup(spec), "history": store.history(spec)}

    def api_record(self, body: dict) -> dict:
        spec = self._spec(body.get("spec") or body)
        provider_refs = dict(body.get("providerRefs") or {})
        if body.get("lcsc"):
            provider_refs.setdefault("jlcpcb", body["lcsc"])
        try:
            return {"choice": self._store().record(
                spec, mpn=body.get("mpn") or None,
                manufacturer=body.get("manufacturer") or None,
                provider_refs=provider_refs or None,
                rank=int(body.get("rank") or 1),
                description=body.get("description") or None,
                design=body.get("design") or None,
                note=body.get("note") or None)}
        except ValueError as exc:
            raise ApiError(str(exc))

    def api_rerank(self, body: dict) -> dict:
        spec = self._spec(body.get("spec") or body)
        try:
            return {"choice": self._store().rerank(
                spec, body["ref"], int(body["rank"]), note=body.get("note") or None)}
        except (KeyError, ValueError) as exc:
            raise ApiError(str(exc))

    def api_remove(self, body: dict) -> dict:
        spec = self._spec(body.get("spec") or body)
        try:
            return {"choice": self._store().remove_choice(
                spec, body["ref"], note=body.get("note") or None)}
        except (KeyError, ValueError) as exc:
            raise ApiError(str(exc))

    def api_refresh(self, body: dict) -> dict:
        from ..resolver.orchestration.resolve import _tier_price_at

        store = self._store()
        codes = sorted({c["providerRefs"].get("jlcpcb")
                        for p in store.list_parts() for c in p["choices"]
                        if c["providerRefs"].get("jlcpcb")})
        if not codes:
            return {"refreshed": 0, "outOfStock": [], "missing": []}
        facts = self._datasource_factory().verify(codes)
        out, missing, refreshed = [], [], 0
        for code in codes:
            fact = facts.get(code)
            if fact is not None and fact.found:
                refreshed += 1
                store.update_verified(code, fact.stock, _tier_price_at(fact, 1),
                                      mpn=fact.mpn, manufacturer=fact.manufacturer)
                if (fact.stock or 0) <= 0:
                    out.append(code)
            else:
                missing.append(code)
        return {"refreshed": refreshed, "outOfStock": out, "missing": missing}

    # -- resolution ----------------------------------------------------------

    def api_intake(self, body: dict) -> dict:
        from ..ingestion.fusion.live_design import extract_board, extract_schematic
        from ..requirements import requirements_from_design

        n = body.get("productionQuantity")
        if not isinstance(n, int) or n < 1:
            raise ApiError("'productionQuantity' must be a positive integer")
        try:
            bridge = self._bridge_factory(body.get("fusionHost") or self.fusion_host)
            design, parts = extract_schematic(bridge)
            placements = extract_board(bridge)
        except Exception as exc:  # bridge errors are operational, not bugs
            raise ApiError(f"Fusion read failed: {exc}", status=502)
        requirements = requirements_from_design(design, parts, n, placements)
        return {
            "requirements": requirements.to_dict(),
            "placements": [
                {"designator": p.designator, "x": p.x, "y": p.y, "angle": p.angle,
                 "mirror": p.mirror, "populate": p.populate, "footprint": p.footprint}
                for p in placements],
        }

    def api_resolve(self, body: dict) -> dict:
        from ..resolver.orchestration.queue import build_approval_queue
        from ..resolver.orchestration.resolve import resolve

        try:
            requirements = RequirementsBom.from_dict(body["requirements"])
        except (KeyError, ValueError) as exc:
            raise ApiError(f"bad requirements: {exc}")
        strategy = self._strategy(body.get("provider") or "jlcpcb")
        store = self._store()
        datasource = (self._datasource_factory()
                      if getattr(strategy, "requires_live_stock", True) else None)
        result = resolve(store, requirements,
                         datasource=datasource or _NullSource(), strategy=strategy)
        if body.get("placements"):
            result["placements"] = body["placements"]
        out = {"resolution": result}
        if result["escalations"] and datasource is not None:
            out["queue"] = build_approval_queue(
                store, requirements, result,
                datasource=datasource, strategy=strategy)
        return out

    def api_approve(self, body: dict) -> dict:
        from ..resolver.orchestration.queue import apply_approvals

        approvals = body.get("approvals")
        if not isinstance(approvals, list) or not approvals:
            raise ApiError("'approvals' must be a non-empty list")
        try:
            return {"recorded": apply_approvals(self._store(), approvals)}
        except (KeyError, ValueError) as exc:
            raise ApiError(str(exc))

    # -- manufacturing -------------------------------------------------------

    def api_emit(self, body: dict) -> dict:
        resolution = body.get("resolution")
        if not isinstance(resolution, dict):
            raise ApiError("'resolution' must be a resolution document")
        provider = body.get("provider") or resolution.get("provider") or "jlcpcb"
        notes: list[str] = []
        if provider == "pcbway":
            from ..providers.pcbway.adapter import PCBWayAdapter

            adapter = PCBWayAdapter()
            paths = adapter.export(resolution, self.outdir)
        else:
            from ..providers.jlcpcb.adapter import JLCPCBAdapter

            adapter = JLCPCBAdapter()
            paths = adapter.export(resolution, self.outdir, on_note=notes.append)
        blockers = [c.to_dict() for c in adapter.validate(resolution)]
        snapshot = None
        if not blockers:
            from ..reporting.snapshot import write_release_snapshot

            snapshot = str(write_release_snapshot(resolution, paths[0]))
        return {
            "provider": provider,
            "files": [str(p) for p in paths],
            "blockers": blockers,
            "readyToUpload": not blockers,
            "snapshot": snapshot,
            "notes": notes,
        }

    def api_snapshots(self, params: dict) -> dict:
        snaps = sorted(self.outdir.glob("*.snapshot.json"), reverse=True)
        return {"snapshots": [
            {"name": p.name, "size": p.stat().st_size} for p in snaps]}

    def api_snapshot(self, params: dict) -> dict:
        name = params.get("name") or ""
        if not name.endswith(".snapshot.json") or "/" in name or "\\" in name:
            raise ApiError("bad snapshot name")
        path = self.outdir / name
        if not path.exists():
            raise ApiError("no such snapshot", status=404)
        return json.loads(path.read_text())


class _NullSource:
    name = "null"

    def verify(self, refs):
        return {}

    def discover(self, query):
        return []


GET_ROUTES = {
    "/api/parts": "api_parts",
    "/api/part": "api_part",
    "/api/snapshots": "api_snapshots",
    "/api/snapshot": "api_snapshot",
}
POST_ROUTES = {
    "/api/record": "api_record",
    "/api/rerank": "api_rerank",
    "/api/remove": "api_remove",
    "/api/refresh": "api_refresh",
    "/api/intake": "api_intake",
    "/api/resolve": "api_resolve",
    "/api/approve": "api_approve",
    "/api/emit": "api_emit",
}


def make_handler(app: HendleyApp):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # quiet by default
            pass

        def _send(self, status: int, payload, content_type="application/json"):
            body = (payload if isinstance(payload, bytes)
                    else json.dumps(payload, ensure_ascii=False).encode())
            self.send_response(status)
            self.send_header("Content-Type", f"{content_type}; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _dispatch(self, method_name: str, arg: dict):
            try:
                self._send(200, getattr(app, method_name)(arg))
            except ApiError as exc:
                self._send(exc.status, {"error": str(exc)})
            except Exception as exc:  # surfaced, never swallowed
                traceback.print_exc()
                self._send(500, {"error": f"{type(exc).__name__}: {exc}"})

        def do_GET(self):
            url = urlparse(self.path)
            if url.path in ("/", "/index.html"):
                self._send(200, PAGE_HTML.encode(), content_type="text/html")
                return
            route = GET_ROUTES.get(url.path)
            if route is None:
                self._send(404, {"error": "not found"})
                return
            params = {k: v[0] for k, v in parse_qs(url.query).items()}
            self._dispatch(route, params)

        def do_POST(self):
            url = urlparse(self.path)
            route = POST_ROUTES.get(url.path)
            if route is None:
                self._send(404, {"error": "not found"})
                return
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                body = json.loads(raw or b"{}")
            except json.JSONDecodeError:
                self._send(400, {"error": "request body must be JSON"})
                return
            self._dispatch(route, body)

    return Handler


def run_app(app: HendleyApp, port: int = 8341, open_browser: bool = True) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(app))
    url = f"http://127.0.0.1:{server.server_port}/"
    print(f"Hendley app: {url}  (Ctrl-C to stop)")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
