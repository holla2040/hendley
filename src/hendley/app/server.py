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
- ``GET  /api/intake-cache``      — the last intake, interpretation cache re-applied
- ``POST /api/resolve``           — resolve a Requirements BOM (+ approval queue;
  ``searches={lineIndex: terms}`` fires the engineer's searches verbatim)
- ``POST /api/explore``           — free search for a pinned part's alternates,
  live-verified, plus the agent-judged package for its footprint
- ``POST /api/approve``           — record queue answers to the knowledge store
- ``POST /api/emit``              — gate + export order files (+ snapshot when clean)
- ``GET  /api/snapshots``         — release snapshots in the output dir
- ``GET  /api/snapshot?name=``    — one snapshot document
- ``GET  /api/rotations``         — CPL rotation corrections (data/cpl-rotations.json)
- ``POST /api/rotation``          — upsert/remove one correction (footprint/LCSC key)
- ``GET  /api/draft?design=``     — the in-progress order draft for a design
- ``POST /api/draft``             — save/clear a design's draft (survives reloads)
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
DEFAULT_DRAFT_PATH = "~/.hendley/draft.json"
DEFAULT_CACHE_PATH = "~/.hendley/design-cache.json"


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


def _default_interpreter():
    from ..ai.claude_cli import ClaudeCLIInterpreter

    return ClaudeCLIInterpreter()


CONFIDENCE_THRESHOLD = 0.8


def _kind_hint(designator: str) -> str:
    import re

    m = re.match(r"([A-Za-z]+)", designator or "")
    return (m.group(1) if m else "").upper()


class HendleyApp:
    """The API surface — every method is a thin wrapper over the library."""

    def __init__(self, db_path=None, outdir: str | Path = DEFAULT_OUTDIR,
                 fusion_host: str | None = None,
                 datasource_factory=None, bridge_factory=None,
                 interpreter_factory=None,
                 rotations_path: str | Path | None = None,
                 draft_path: str | Path = DEFAULT_DRAFT_PATH,
                 cache_path: str | Path = DEFAULT_CACHE_PATH):
        self.db_path = db_path
        self.outdir = Path(outdir).expanduser()
        self.fusion_host = fusion_host
        self.rotations_path = rotations_path
        self.draft_path = Path(draft_path).expanduser()
        self.cache_path = Path(cache_path).expanduser()
        self._datasource_factory = datasource_factory or _default_datasource
        self._bridge_factory = bridge_factory or _default_bridge
        self._interpreter_factory = interpreter_factory or _default_interpreter

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
        """One part + audit history. ``verify=1`` live-verifies every choice
        first (one batched call) — the panel shows current stock, not the
        advisory cache; degrades to the cache when live access is down."""
        spec = self._spec(params)
        store = self._store()
        house = store.lookup(spec)
        if house and params.get("verify"):
            from ..resolver.orchestration.resolve import _tier_price_at

            codes = sorted({c["providerRefs"].get("jlcpcb")
                            for c in house["choices"]
                            if c["providerRefs"].get("jlcpcb")})
            if codes:
                try:
                    facts = self._datasource_factory().verify(codes)
                except ApiError:
                    # live access is down: cached numbers would masquerade
                    # as current — the honest answer is "unknown"
                    house = dict(house)
                    house["choices"] = [
                        {**c, "lastStock": None, "lastPrice": None,
                         "stockUnknown": True} for c in house["choices"]]
                else:
                    for code in codes:
                        fact = facts.get(code)
                        if fact is not None and fact.found:
                            store.update_verified(
                                code, fact.stock, _tier_price_at(fact, 1),
                                mpn=fact.mpn, manufacturer=fact.manufacturer)
                    house = store.lookup(spec)
        return {"housePart": house, "history": store.history(spec)}

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
        uninterpreted = self._interpret_lines(requirements)
        out = {
            "requirements": requirements.to_dict(),
            "uninterpreted": uninterpreted,
            "placements": [
                {"designator": p.designator, "x": p.x, "y": p.y, "angle": p.angle,
                 "mirror": p.mirror, "populate": p.populate, "footprint": p.footprint}
                for p in placements],
        }
        self._write_cache(requirements.design, out)
        return out

    def _write_cache(self, design: str | None, out: dict) -> None:
        """Persist the intake so the page repopulates without a Fusion read."""
        from datetime import datetime, timezone

        doc = dict(out)
        doc["design"] = design
        doc["savedAt"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(json.dumps(doc, ensure_ascii=False))
        except OSError:
            pass  # the cache is a convenience — never break intake

    def api_intake_cache(self, params: dict) -> dict:
        """The last intake, with the interpretation cache re-applied: spec
        answers given since the read stick, and the LLM is never consulted on
        a cache load."""
        try:
            doc = json.loads(self.cache_path.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return {"cached": None}
        try:
            requirements = RequirementsBom.from_dict(doc.get("requirements") or {})
        except ValueError:
            return {"cached": None}
        old = {u.get("lineIndex"): u for u in doc.get("uninterpreted") or []}
        fresh = self._interpret_lines(requirements, consult_interpreter=False)
        for u in fresh:  # keep the read-time LLM guess as the prefill
            guess = (old.get(u["lineIndex"]) or {}).get("guess") or {}
            if guess.get("spec"):
                u["guess"] = guess
        doc["uninterpreted"] = fresh
        doc["requirements"] = requirements.to_dict()
        return {"cached": doc}

    def _interpret_lines(self, requirements,
                         consult_interpreter: bool = True) -> list[dict]:
        """Judge every mode-less line: cache first, then the LLM, else the
        engineer (returned as confirm-card material). Each unique string is
        judged once, ever; user answers are authoritative. With
        ``consult_interpreter=False`` only the cache answers (cache loads)."""
        from ..ai.interpreter import Interpretation
        from ..domain.model import SpecKey

        store = self._store()
        interpreter = None
        interpreter_dead = not consult_interpreter
        out: list[dict] = []
        for i, line in enumerate(requirements.lines):
            if line.dnp or line.mode is not None:
                continue
            hint = _kind_hint(line.designators[0])
            raw_value = line.comment or ""
            footprint = line.footprint or ""
            cached = store.get_interpretation("part", hint, raw_value, footprint)
            if cached and (cached["result"] or {}).get("spec"):
                line.spec = SpecKey.from_dict(cached["result"]["spec"])
                continue
            guess = None
            if not interpreter_dead:
                if interpreter is None:
                    interpreter = self._interpreter_factory()
                ctx = {"designator": line.designators[0], "value": raw_value,
                       "footprint": footprint}
                interp = interpreter.interpret_part(ctx)
                if interp is None:
                    interpreter_dead = True  # binary missing/broken: stop retrying
                elif interp.spec and interp.confidence >= CONFIDENCE_THRESHOLD:
                    line.spec = interp.spec
                    store.put_interpretation(
                        "part", interp.to_dict(), "llm", kind_hint=hint,
                        raw_value=raw_value, footprint=footprint,
                        confidence=interp.confidence)
                    if interp.envelope:
                        store.put_interpretation(
                            "footprint", {"envelope": interp.envelope}, "llm",
                            footprint=interp.spec.package,
                            confidence=interp.confidence)
                    continue
                else:
                    guess = interp
            out.append({
                "lineIndex": i,
                "designators": line.designators,
                "kindHint": hint,
                "value": raw_value,
                "footprint": footprint,
                "guess": (guess or Interpretation()).to_dict(),
            })
        return out

    def api_confirm_spec(self, body: dict) -> dict:
        """The engineer's one-time answer for an ad-hoc string — authoritative,
        cached forever, never asked again."""
        spec = self._spec(body.get("spec") or {})
        result = {"spec": spec.to_dict()}
        envelope = body.get("envelope") or {}
        if envelope:
            result["envelope"] = envelope
        store = self._store()
        store.put_interpretation(
            "part", result, "user",
            kind_hint=str(body.get("kindHint") or ""),
            raw_value=str(body.get("value") or ""),
            footprint=str(body.get("footprint") or ""))
        if envelope:
            store.put_interpretation("footprint", {"envelope": envelope}, "user",
                                     footprint=spec.package)
        return result

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
            searches = {}
            for k, v in (body.get("searches") or {}).items():
                try:
                    searches[int(k)] = str(v)
                except (TypeError, ValueError):
                    continue
            out["queue"] = build_approval_queue(
                store, requirements, result,
                datasource=datasource, strategy=strategy, searches=searches)
        return out

    def api_explore(self, body: dict) -> dict:
        """Engineer-fired free search, live-verified — alternates for a
        schematic-pinned part. The terms come from the user verbatim; when a
        footprint is supplied, results are filtered to the package the AGENT
        judged it to be (cached forever) — Python only compares."""
        from ..resolver.orchestration.queue import explore

        search = str(body.get("search") or "").strip()
        if not search:
            raise ApiError("'search' is required")
        # an explicit package (a spec's agent-normalized one) wins; otherwise
        # judge the footprint (pinned parts)
        package = str(body.get("package") or "").strip() or None
        footprint = str(body.get("footprint") or "").strip()
        if package is None and footprint:
            package = self._judged_package(footprint)
        # everything verified returns; the page splits by package/coverage so
        # nothing filtered is ever unreachable
        return {"search": search,
                "candidates": explore(self._datasource_factory(), search),
                "package": package}

    def _judged_package(self, footprint: str) -> str | None:
        """The catalog package for a library footprint name — cache first,
        else one agent judgment, cached forever. '' (nothing standard) is a
        valid cached answer; None means no judgment available."""
        store = self._store()
        cached = store.get_interpretation("footprint", footprint=footprint)
        result = (cached or {}).get("result") or {}
        if "package" in result:
            return result.get("package") or None
        interpreter = self._interpreter_factory()
        judge = getattr(interpreter, "interpret_footprint", None)
        if judge is None:
            return None
        j = judge(footprint)
        if j is None or j["confidence"] < CONFIDENCE_THRESHOLD:
            return None
        merged = dict(result)
        merged["package"] = j["package"]
        if j.get("envelope") and not merged.get("envelope"):
            merged["envelope"] = j["envelope"]
        store.put_interpretation("footprint", merged, "llm",
                                 footprint=footprint,
                                 confidence=j["confidence"])
        return j["package"] or None

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
            paths = adapter.export(resolution, self.outdir,
                                   rotations=self.rotations_path,
                                   on_note=notes.append)
        blockers = [c.to_dict() for c in adapter.validate(resolution)]
        snapshot = None
        if not blockers:
            from ..reporting.snapshot import write_release_snapshot

            snapshot = str(write_release_snapshot(resolution, paths[0]))
            self._clear_draft(resolution.get("design"))
        contents = {}
        for p in paths:  # lets the page save copies via the browser's picker
            try:
                contents[Path(p).name] = Path(p).read_text()
            except OSError:
                pass
        return {
            "provider": provider,
            "files": [str(p) for p in paths],
            "fileContents": contents,
            "blockers": blockers,
            "readyToUpload": not blockers,
            "snapshot": snapshot,
            "notes": notes,
        }

    # -- rotations -----------------------------------------------------------

    def _rotations_file(self) -> Path:
        from ..providers.jlcpcb.order_files import find_rotations_file

        path = find_rotations_file(self.rotations_path)
        if path is None or not path.exists():
            raise ApiError(
                "cpl-rotations.json not found — start the app from the repo",
                status=503)
        return path

    def api_rotations(self, params: dict) -> dict:
        path = self._rotations_file()
        doc = json.loads(path.read_text())
        return {"corrections": doc.get("corrections", []), "path": str(path)}

    def api_rotation(self, body: dict) -> dict:
        """Upsert one correction, keyed by footprint (or LCSC when no
        footprint); an offset of 0 removes the entry. The flaw belongs to the
        library model, so the fix follows the part into every design."""
        footprint = str(body.get("footprint") or "").strip()
        lcsc = str(body.get("lcsc") or "").strip()
        if not footprint and not lcsc:
            raise ApiError("'footprint' or 'lcsc' is required")
        try:
            offset = int(body["rotationOffsetDeg"]) % 360
        except (KeyError, TypeError, ValueError):
            raise ApiError("'rotationOffsetDeg' must be an integer")
        path = self._rotations_file()
        doc = json.loads(path.read_text())
        corrections = doc.setdefault("corrections", [])
        entry = next(
            (c for c in corrections
             if (footprint and c.get("footprint") == footprint)
             or (not footprint and lcsc and c.get("lcsc") == lcsc)), None)
        if offset == 0:
            if entry is not None:
                corrections.remove(entry)
        else:
            if entry is None:
                entry = {}
                corrections.append(entry)
            if lcsc:
                entry["lcsc"] = lcsc
            if body.get("mpn"):
                entry["mpn"] = str(body["mpn"])
            if footprint:
                entry["footprint"] = footprint
            entry["rotationOffsetDeg"] = offset
            from datetime import date

            entry["verified"] = (str(body["note"]) if body.get("note")
                                 else f"{date.today().isoformat()} set via the app")
        path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
        return {"corrections": corrections}

    # -- draft (in-progress order state; survives page reloads) ---------------

    def _read_drafts(self) -> dict:
        try:
            doc = json.loads(self.draft_path.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return {"drafts": {}}
        if not isinstance(doc.get("drafts"), dict):
            return {"drafts": {}}
        return doc

    def _write_drafts(self, doc: dict) -> None:
        self.draft_path.parent.mkdir(parents=True, exist_ok=True)
        self.draft_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n")

    def api_draft_get(self, params: dict) -> dict:
        design = params.get("design") or ""
        return {"draft": self._read_drafts()["drafts"].get(design)}

    def api_draft_put(self, body: dict) -> dict:
        design = str(body.get("design") or "")
        if not design:
            raise ApiError("'design' is required")
        doc = self._read_drafts()
        if body.get("draft") is None:
            doc["drafts"].pop(design, None)
        else:
            doc["drafts"][design] = body["draft"]
        self._write_drafts(doc)
        return {"draft": doc["drafts"].get(design)}

    def _clear_draft(self, design: str | None) -> None:
        if not design:
            return
        doc = self._read_drafts()
        if design in doc["drafts"]:
            doc["drafts"].pop(design)
            self._write_drafts(doc)

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
    "/api/rotations": "api_rotations",
    "/api/draft": "api_draft_get",
    "/api/intake-cache": "api_intake_cache",
}
POST_ROUTES = {
    "/api/record": "api_record",
    "/api/rerank": "api_rerank",
    "/api/remove": "api_remove",
    "/api/refresh": "api_refresh",
    "/api/intake": "api_intake",
    "/api/confirm-spec": "api_confirm_spec",
    "/api/resolve": "api_resolve",
    "/api/explore": "api_explore",
    "/api/approve": "api_approve",
    "/api/emit": "api_emit",
    "/api/rotation": "api_rotation",
    "/api/draft": "api_draft_put",
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


def _open_browser_quietly(url: str) -> bool:
    """webbrowser.open with the launcher's noise suppressed.

    On WSL/headless boxes xdg-open walks its whole browser list printing
    'not found' for each to OUR stderr (children inherit the fds at spawn) —
    point fd 1/2 at devnull for the duration so the terminal stays clean.
    """
    import os

    devnull = os.open(os.devnull, os.O_WRONLY)
    saved_out, saved_err = os.dup(1), os.dup(2)
    try:
        os.dup2(devnull, 1)
        os.dup2(devnull, 2)
        return webbrowser.open(url)
    except Exception:
        return False
    finally:
        os.dup2(saved_out, 1)
        os.dup2(saved_err, 2)
        for fd in (saved_out, saved_err, devnull):
            os.close(fd)


def run_app(app: HendleyApp, port: int = 8341, open_browser: bool = True) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(app))
    url = f"http://127.0.0.1:{server.server_port}/"
    print(f"Hendley app: {url}  (Ctrl-C to stop)")
    if open_browser and not _open_browser_quietly(url):
        print(f"(no local browser found — open {url} yourself)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
