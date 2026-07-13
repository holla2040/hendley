"""The app's HTTP layer — stdlib http.server, JSON API over library calls.

Bound to 127.0.0.1 only (ADR-0004: same trust model as the CLI on the same
machine). SQLite connections don't cross threads, so every request opens a
short-lived PartsDb — cheap, and migrations are idempotent.

Endpoints (all JSON):

- ``GET  /``                      — the app page
- ``GET  /api/parts[?kind=]``     — House Parts with ranked choices
- ``GET  /api/part?kind&value&package[&qualifier][&verify=1]`` — one part +
  audit history; ``verify=1`` live-verifies every choice first (the panel
  shows NOW; choices flag ``stockUnknown`` when live access is down)
- ``POST /api/record``            — approve a Part Choice (deliberate rank)
- ``POST /api/rerank``            — move a choice on its AVL
- ``POST /api/remove``            — remove a choice (state change)
- ``POST /api/refresh``           — live-verify every JLC-coded choice
- ``POST /api/intake``            — read the open Fusion design → Requirements BOM
- ``GET  /api/intake-cache``      — the last intake, interpretation cache re-applied
- ``POST /api/resolve``           — resolve a Requirements BOM (+ approval queue;
  deterministic auto-discovery only — the engineer's searches are their own act)
- ``GET  /api/categories``        — every catalog table + the columns a term can
  be proven against (the search line's part-type popup; no magic words)
- ``POST /api/search``            — THE search box:
  ``{terms, lineIndex?, category?, net?, sieve?}``. The agent plans the query
  from the engineer's words; Python fires it and proves every result against
  every term (misses come back with the reason), returning the query it sent
  and the terms it proved. A ``category`` overrides the agent's choice (and is
  remembered as this shop's convention for that designator letter); a ``sieve``
  replaces the terms outright — the engineer's query always outranks the
  agent's. No line = a free catalog search from the overview.
- ``POST /api/key``               — the agent names the requirement a pick
  satisfies (the AVL's key), from the design line + the search words + the
  picked part. The engineer never fills in database fields.
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
        try:   # 'value' is optional — an unnamed part genuinely has none
            return SpecKey(kind=params["kind"],
                           value=params.get("value") or "",
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
            # the schematic names an exact part: nothing to judge
            if line.dnp or line.mpn or line.provider_refs:
                continue
            hint = _kind_hint(line.designators[0])
            raw_value = line.comment or ""
            footprint = line.footprint or ""
            cached = store.get_interpretation("part", hint, raw_value, footprint)
            if cached and (cached["result"] or {}).get("spec"):
                # what was RECORDED for this line outranks any spec already on
                # it (a read-time guess, or one cached with the last design):
                # the record is what the approved-parts list is keyed by, so a
                # line carrying a staler spec would look up nothing at all
                line.spec = SpecKey.from_dict(cached["result"]["spec"])
                continue
            if line.spec is not None:
                continue        # the normalizer's own reading, nothing recorded
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
            entry = {
                "lineIndex": i,
                "designators": line.designators,
                "kindHint": hint,
                "value": raw_value,
                "footprint": footprint,
                "guess": (guess or Interpretation()).to_dict(),
            }
            # the card must never seed a raw library footprint name as the
            # package — downstream (seed, package equality, envelope key)
            # trusts spec.package to be the catalog form. The part judgment
            # usually read it already; only ask again when it didn't.
            read_package = bool(
                guess and ((guess.spec and guess.spec.package)
                           or guess.partial.get("package")))
            if footprint and not read_package:
                judged = self._judged_package(footprint,
                                              consult=not interpreter_dead)
                if judged:
                    entry["judgedPackage"] = judged
                    row = store.get_interpretation("footprint",
                                                   footprint=footprint)
                    env = ((row or {}).get("result") or {}).get("envelope")
                    if env:
                        entry["judgedEnvelope"] = env
            out.append(entry)
        return out

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
            # only the deterministic auto-discovery runs here; the engineer's
            # own searches are their own act, on /api/search
            out["queue"] = build_approval_queue(
                store, requirements, result,
                datasource=datasource, strategy=strategy)
        return out

    def api_read(self, body: dict) -> dict:
        """Work out what a part IS — run when the engineer opens it, for EVERY
        part, whatever the schematic says or doesn't say about it.

        This is the step that fills the search box. It hands the agent every
        fact the app holds, and the biggest one it never used before: when the
        design pins a part number, the CATALOG knows the answer. One
        ``verify()`` call returns the exact MPN, the manufacturer, the real
        catalog package (``componentSpecification`` — the only string the index
        will match, and the only place a library footprint like ``C-E-5``
        becomes ``插件,D5xL11mm``) and the full parameter list. The app already
        fetched that record to check stock and threw the specs away.

        ``{lineIndex, requirements, code?}`` → the reading. Judged once per
        part, ever; cached forever."""
        line = self._search_line(body)
        if not line:
            raise ApiError("'lineIndex' must point at a line to read")
        lines = (body.get("requirements") or {}).get("lines") or []
        ln = lines[int(body["lineIndex"])]
        code = str(body.get("code") or
                   (ln.get("providerRefs") or {}).get("jlcpcb") or "").strip()

        store = self._store()
        prefix = _kind_hint(line.get("designator") or "")
        key = {"kind_hint": prefix,
               # the part number belongs in the key: change it in the schematic
               # and this is a different part, which must be read again
               "raw_value": f"{line.get('value') or ''}\x1f{code}",
               "footprint": line.get("footprint") or ""}
        cached = store.get_interpretation("read", **key)
        result = (cached or {}).get("result") or {}
        # A reading carries the spec table its terms are written in ("catalog",
        # even when null). One that doesn't predates that vocabulary, so its plan
        # can't seed anything — re-read the part rather than seed the box from it.
        if result.get("search") and "catalog" in result:
            return {"reading": result, "cached": True}

        dossier = {
            "schematic": {
                "designators": ln.get("designators") or [],
                "prefix": prefix,
                "value": line.get("value") or "",
                "footprint": line.get("footprint") or "",
                "mpn": ln.get("mpn") or "",
                "code": code,
            },
            "catalog": self._catalog_record(code),
            "convention": self._convention(line.get("designator") or ""),
        }
        interpreter = self._interpreter_factory()
        reader = getattr(interpreter, "read_part", None)
        reading = reader(dossier) if reader else None
        if reading is None:
            # the agent is unavailable: say so, and let the box keep the
            # schematic's own words rather than block the panel
            return {"reading": None, "cached": False}
        # the spec table it read the part FROM travels with the reading: it is
        # the vocabulary the terms are written in, and the list of every other
        # thing this part publishes that the engineer could still ask about.
        # Specs don't go stale the way stock does — cache it with the reading.
        reading["catalog"] = dossier["catalog"]
        store.put_interpretation("read", reading, "llm",
                                 confidence=reading.get("confidence"), **key)
        return {"reading": reading, "cached": False}

    def _catalog_record(self, code: str) -> dict | None:
        """The part's own record from the live catalog — the ground truth we
        already fetch (to check stock) and used to throw away."""
        if not code:
            return None
        try:
            fact = self._datasource_factory().verify([code]).get(code)
        except ApiError:
            return None                       # no credentials / offline: fine
        if fact is None or not fact.found:
            return None
        d = fact.raw or {}
        return {
            "code": code,
            "mpn": d.get("componentModel"),
            "manufacturer": fact.manufacturer,
            "package": d.get("componentSpecification"),
            "libraryType": d.get("libraryType"),
            "describe": d.get("describe"),
            "parameters": {p.get("parameterName"): p.get("parameterValue")
                           for p in (d.get("parameters") or [])},
        }

    def api_search(self, body: dict) -> dict:
        """The search box. The engineer types anything; the AGENT turns it into
        a query plan; Python fires it and PROVES every result against every
        term (see resolver/orchestration/search.py — the index silently ignores
        params it doesn't know, so the query alone proves nothing).

        ``{terms, lineIndex?}`` — no line means a free catalog search from the
        design overview. The plan is cached: the same words on the same design
        line never cost a second judgment."""
        from ..resolver.orchestration.search import run_search

        terms = str(body.get("terms") or "").strip()
        if not terms:
            raise ApiError("'terms' is required — type what you want")
        line = self._search_line(body)
        category = str(body.get("category") or "").strip()
        sieve = body.get("sieve")
        if isinstance(sieve, list):
            # The engineer edited the terms themselves: fire exactly that, no
            # judgment call. The terms are now the WHOLE truth — the query is
            # rebuilt from them, so dropping a term really drops it instead of
            # the net quietly re-asserting it.
            from ..resolver.orchestration.search import NET_COLUMNS

            sieve = [p for p in sieve if isinstance(p, dict) and p.get("field")]
            fts = category == "components" or not category
            net = {"search": terms} if fts else {
                param: t["value"]
                for param, column in NET_COLUMNS.items()
                for t in sieve
                if t.get("op") == "eq" and t.get("field") == column
            }
            plan = {"mode": "fts" if fts else "parametric",
                    "category": category or "components",
                    "net": net, "sieve": sieve, "lookingFor": {},
                    "say": str(body.get("say") or terms), "confidence": 1.0}
            judged = False
        else:
            plan, judged = self._plan(terms, line, category or None)
        if category and line.get("designator"):
            self._remember_convention(line["designator"], category, plan)
        found = run_search(self._datasource_factory(), plan)
        return {"terms": terms, "planned": plan, "judged": judged, **found}

    def api_categories(self, params: dict) -> dict:
        """Every table the catalog publishes, and the columns a search term can
        be proven against — so the engineer picks, and never has to guess a
        magic word."""
        from ..datasources.jlc.alternates import (
            CATEGORIES,
            CATEGORY_COLUMNS,
            EMPTY_CATEGORIES,
        )

        return {"categories": [
            {"slug": c, "columns": list(CATEGORY_COLUMNS.get(c, ("package",))),
             "empty": c in EMPTY_CATEGORIES}
            for c in sorted(CATEGORIES)]}

    def _remember_convention(self, designator: str, category: str,
                             plan: dict) -> None:
        """The engineer overrode the category: that is this shop's convention
        for that designator letter, recorded for every design from now on. `X`
        is a connector in one library and a socket in another — only they know
        which, so their word is final (and re-overridable)."""
        prefix = _kind_hint(designator)
        if not prefix:
            return
        kind = ((plan.get("lookingFor") or {}).get("kind") or "").strip()
        self._store().put_interpretation(
            "designator", {"category": category, "kind": kind, "prefix": prefix},
            "user", kind_hint=prefix)

    def _convention(self, designator: str) -> dict:
        prefix = _kind_hint(designator)
        if not prefix:
            return {}
        row = self._store().get_interpretation("designator", kind_hint=prefix)
        return (row or {}).get("result") or {}

    def _search_line(self, body: dict) -> dict:
        """The design context the engineer typed against (empty on overview).
        ``code`` is the part the search is ANCHORED on — the one the schematic
        pins or the app has mounted — and its catalog record is what lets the
        agent write terms in the catalog's own vocabulary."""
        idx = body.get("lineIndex")
        lines = (body.get("requirements") or {}).get("lines") or []
        if idx is None or not isinstance(idx, int) or not (0 <= idx < len(lines)):
            return {}
        ln = lines[idx]
        return {"designator": (ln.get("designators") or [""])[0],
                "value": ln.get("comment") or "",
                "footprint": ln.get("footprint") or "",
                "code": str(body.get("code") or
                            (ln.get("providerRefs") or {}).get("jlcpcb")
                            or "").strip()}

    def _plan(self, terms: str, line: dict,
              category: str | None = None) -> tuple[dict, bool]:
        """The agent's query plan — cached forever per (terms, design line, and
        any category the engineer forced). Falls back to a verbatim keyword
        search when the agent is unavailable, and says so rather than
        pretending the terms were understood."""
        store = self._store()
        code = line.get("code") or ""
        key = {"kind_hint": _kind_hint(line.get("designator") or ""),
               # both belong in the question: a forced category changes the
               # answer, and so does the part the search is anchored on — its
               # catalog record IS the vocabulary the terms are written in
               "raw_value": "\x1f".join([terms, category or "", code]),
               "footprint": line.get("footprint") or ""}
        cached = store.get_interpretation("search", **key)
        if cached and (cached["result"] or {}).get("mode"):
            return cached["result"], True
        interpreter = self._interpreter_factory()
        planner = getattr(interpreter, "plan_search", None)
        ctx = {**line, "terms": terms, "category": category,
               "convention": self._convention(line.get("designator") or ""),
               "catalog": self._catalog_record(code)}
        plan = planner(ctx) if planner else None
        if plan is None:
            return ({"mode": "fts", "category": "components",
                     "net": {"search": terms}, "sieve": [], "lookingFor": {},
                     "say": f"“{terms}” matched against part names only — "
                            "the agent isn't available to read your terms",
                     "confidence": 0.0}, False)
        store.put_interpretation("search", plan, "llm",
                                 confidence=plan.get("confidence"), **key)
        return plan, True

    def _judged_package(self, footprint: str, consult: bool = True) -> str | None:
        """The catalog package for a library footprint name — cache first,
        else one agent judgment, cached forever. '' (nothing standard) is a
        valid cached answer; None means no judgment available. With
        ``consult=False`` only the cache answers (cache loads)."""
        store = self._store()
        cached = store.get_interpretation("footprint", footprint=footprint)
        result = (cached or {}).get("result") or {}
        if "package" in result:
            return result.get("package") or None
        if not consult:
            return None
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

    def api_key(self, body: dict) -> dict:
        """Name the requirement a pick satisfies — the AVL's key for it, in
        every future design. The AGENT decides it, from the design line, the
        engineer's own search words, and the picked part's verified facts; the
        engineer is never asked to fill in database fields (that is how a
        "1000V" once landed in a diode's value). Recorded user-provenance,
        because the pick is the engineer's act — and a later pick re-keys it.

        ``{lineIndex, requirements, terms, part}`` → ``{spec, rationale}``."""
        line = self._search_line(body)
        part = body.get("part") or {}
        if not part.get("code"):
            raise ApiError("'part' (the approved part) is required")
        store = self._store()
        key = {"kind_hint": _kind_hint(line.get("designator") or ""),
               "raw_value": line.get("value") or "",
               "footprint": line.get("footprint") or ""}
        terms = str(body.get("terms") or "").strip()
        remembered = (store.get_interpretation("part", **key) or {}).get("result") or {}
        cached_spec = (remembered.get("spec") or {}) if not terms else {}
        if cached_spec:   # nothing new was searched — the recorded key stands
            return {"spec": cached_spec,
                    "rationale": remembered.get("rationale") or "",
                    "cached": True}
        interpreter = self._interpreter_factory()
        namer = getattr(interpreter, "derive_key", None)
        judged = namer({**line, "terms": terms, "remembered": remembered,
                        "part": part}) if namer else None
        if judged is None:
            raise ApiError(
                "the agent isn't available to name this requirement — the pick "
                "can't be recorded to the approved list right now", status=503)
        result = {"spec": judged["spec"], "rationale": judged.get("rationale") or ""}
        if remembered.get("envelope"):
            result["envelope"] = remembered["envelope"]
        store.put_interpretation("part", result, "user",
                                 confidence=judged.get("confidence"), **key)
        return {**result, "cached": False}

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
    "/api/categories": "api_categories",
}
POST_ROUTES = {
    "/api/record": "api_record",
    "/api/rerank": "api_rerank",
    "/api/remove": "api_remove",
    "/api/refresh": "api_refresh",
    "/api/intake": "api_intake",
    "/api/resolve": "api_resolve",
    "/api/read": "api_read",
    "/api/search": "api_search",
    "/api/key": "api_key",
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
