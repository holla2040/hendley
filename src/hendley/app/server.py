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
READ_PLAN_SCHEMA_VERSION = 17


class PackageListing(list):
    """Catalog package counts plus whether the source listing hit its row cap."""

    truncated = False


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


def _default_interpreter(backend: str | None = None, model: str | None = None):
    import os

    backend = (backend or os.environ.get("HENDLEY_INTERPRETER", "codex")).strip().lower()
    if backend == "codex":
        from ..ai.codex_cli import CodexCLIInterpreter

        return CodexCLIInterpreter(model=model)
    if backend == "claude":
        if model:
            raise ValueError("--model is currently supported only with Codex")
        from ..ai.claude_cli import ClaudeCLIInterpreter

        return ClaudeCLIInterpreter()
    raise ApiError(
        f"unknown HENDLEY_INTERPRETER {backend!r}; expected 'codex' or 'claude'",
        status=503)


def interpreter_description(backend: str | None = None,
                            model: str | None = None) -> str:
    """Human-readable backend/model without launching an agent process."""
    interpreter = _default_interpreter(backend, model)
    name = "Codex" if interpreter.name == "codex-cli" else "Claude"
    model = getattr(interpreter, "model", "") or "CLI default"
    return f"{name}; model: {model}"


CONFIDENCE_THRESHOLD = 0.8


def _kind_hint(designator: str) -> str:
    import re

    m = re.match(r"([A-Za-z]+)", designator or "")
    return (m.group(1) if m else "").upper()


_NON_INTERPRETATION_ATTRIBUTES = {
    "DNP", "LCSC", "JLC", "JLCPCB", "OLDLCSC", "MANUFACTURER", "MP", "MF",
}


def _part_cache_value(raw_value: str, attributes: dict | None = None) -> str:
    """Cache identity for a schematic meaning, including meaningful attributes.

    Empty/administrative attributes retain the historical raw-value key, so old
    cache entries remain useful. Electrical hints such as TYPE=Zener create a
    distinct key and changing them necessarily causes a fresh reading.
    """
    meaningful = {
        str(k).strip().upper(): str(v).strip()
        for k, v in (attributes or {}).items()
        if str(k).strip().upper() not in _NON_INTERPRETATION_ATTRIBUTES
        and str(v).strip()
    }
    if not meaningful:
        return raw_value
    return raw_value + "\x1e" + json.dumps(
        meaningful, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _library_type(fact) -> str | None:
    """Basic or Extended, off a live-verified fact. It is an ORDER-level fee
    attribute, not part policy, so it is never stored — only reported."""
    if fact is None or not fact.found:
        return None
    return (fact.raw or {}).get("libraryType")


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
                    # Basic/Extended is an ORDER-level fee attribute, not part
                    # policy, so it is deliberately not in the DB — but we just
                    # verified every choice and the answer is in the fact. Carry
                    # it on the response rather than leave the column blank on
                    # exactly the parts the engineer approved.
                    if house:
                        house = dict(house)
                        house["choices"] = [
                            {**c, "libraryType": _library_type(
                                facts.get(c["providerRefs"].get("jlcpcb") or ""))}
                            for c in house["choices"]]
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
            # Capture every schematic sheet before BOARD. Some Fusion MCP
            # builds cannot execute EDIT after entering board context.
            try:
                from ..ingestion.fusion.visual import capture_visual_evidence
                visual = capture_visual_evidence(bridge, design)
            except Exception:
                visual = None
            placements = extract_board(bridge)
        except Exception as exc:  # bridge errors are operational, not bugs
            raise ApiError(f"Fusion read failed: {exc}", status=502)
        requirements = requirements_from_design(design, parts, n, placements)
        # Refresh is a design read, never an agent sweep. Deterministic specs
        # and cached judgments apply immediately; an uncached yellow/red line is
        # read only when the engineer opens that part.
        uninterpreted = self._interpret_lines(
            requirements, consult_interpreter=False,
            visual_available=bool(visual))
        out = {
            "requirements": requirements.to_dict(),
            "uninterpreted": uninterpreted,
            "placements": [
                {"designator": p.designator, "x": p.x, "y": p.y, "angle": p.angle,
                 "mirror": p.mirror, "populate": p.populate, "footprint": p.footprint}
                for p in placements],
        }
        # Local image export contains no model call. It is best-effort evidence
        # consumed only when an unresolved part is opened through /api/read.
        try:
            from ..ingestion.fusion.visual import add_board_crops
            unresolved = {d for row in uninterpreted
                          for d in row.get("designators", [])}
            targets = [p for p in out["placements"]
                       if p["designator"] in unresolved]
            visual = add_board_crops(bridge, visual, targets)
        except Exception:
            pass
        if visual:
            visual["placements"] = out["placements"]
            out["visualEvidence"] = visual
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
        fresh = self._interpret_lines(
            requirements, consult_interpreter=False,
            visual_available=bool(doc.get("visualEvidence")))
        for u in fresh:  # keep the read-time LLM guess as the prefill
            guess = (old.get(u["lineIndex"]) or {}).get("guess") or {}
            if guess.get("spec"):
                u["guess"] = guess
        doc["uninterpreted"] = fresh
        doc["requirements"] = requirements.to_dict()
        return {"cached": doc}

    def _interpret_lines(self, requirements,
                         consult_interpreter: bool = True,
                         visual_available: bool = False) -> list[dict]:
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
            if line.dnp:
                continue
            # Families have their own bounded judgment and search pipeline.
            # Feeding them through the generic part interpreter as well can
            # replay an old SpecKey onto the line, leaving two competing truths
            # (and making the resolver silently choose the spec). A family stays
            # mode-less until the engineer selects and approves an actual part.
            if line.family and _kind_hint(line.designators[0]) == "U":
                line.spec = None
                continue
            hint = _kind_hint(line.designators[0])
            target_hint = f"{hint}\x1f{line.designators[0]}"
            raw_value = line.comment or ""
            footprint = line.footprint or ""
            cache_value = _part_cache_value(raw_value, line.attributes)
            specific = store.get_interpretation(
                "part", target_hint, cache_value, footprint)
            generic = store.get_interpretation("part", hint, cache_value, footprint)
            # Model readings that did not inspect this exact symbol must never
            # cross designators. A user-recorded correction is authoritative
            # and intentionally remains reusable for equivalent written specs.
            generic_allowed = ((generic or {}).get("source") == "user"
                               or not visual_available)
            cached = specific or (generic if generic_allowed else None)
            pinned = bool(line.mpn or line.provider_refs)
            if pinned:
                # The schematic names an exact part, and that is normally the end
                # of it — nothing to judge. But if the engineer has NAMED a
                # requirement for this line and approved a list against it, the
                # pin is their DEFAULT, not a lock: honour the recorded key so the
                # line resolves against its approved list and a short pinned part
                # substitutes down it. Without this the house part they just built
                # is orphaned the moment they hit Refresh.
                recorded = cached if (cached or {}).get("source") == "user" else None
                if not (recorded and (recorded["result"] or {}).get("spec")):
                    continue
                line.spec = SpecKey.from_dict(recorded["result"]["spec"])
                line.mpn = None
                line.manufacturer = None
                line.provider_refs = {}
                continue
            # A visual LLM answer is more than its compact SpecKey: its full
            # cached reading carries the executable live-catalog proof plan.
            # Reapplying only the SpecKey here would make the row look resolved
            # enough to skip ``/api/read`` on open, after which the UI falls
            # back to a fresh words-only search and silently loses class,
            # polarity, ratings, and package proof.  Keep it lazy on visual
            # designs; opening the row reuses the cached reading without a
            # model call.  Engineer-recorded corrections remain authoritative.
            cached_can_resolve = ((cached or {}).get("source") == "user"
                                  or not visual_available)
            if cached and not cached_can_resolve:
                # The serialized design cache may itself carry the compact
                # spec written by an earlier lazy read.  It has the same loss
                # of proof-plan context as reapplying the DB entry, so remove
                # it before the normal unresolved-row path below.
                line.spec = None
            if (cached and cached_can_resolve
                    and (cached["result"] or {}).get("spec")):
                # what was RECORDED for this line outranks any spec already on
                # it (a read-time guess, or one cached with the last design):
                # the record is what the approved-parts list is keyed by, so a
                # line carrying a staler spec would look up nothing at all
                line.spec = SpecKey.from_dict(cached["result"]["spec"])
                line.family = None
                continue
            if line.spec is not None:
                continue        # the normalizer's own reading, nothing recorded
            guess = None
            if not interpreter_dead:
                if interpreter is None:
                    interpreter = self._interpreter_factory()
                ctx = {"designator": line.designators[0], "value": raw_value,
                       "footprint": footprint, "attributes": line.attributes}
                interp = interpreter.interpret_part(ctx)
                if interp is None:
                    interpreter_dead = True  # binary missing/broken: stop retrying
                elif interp.spec and interp.confidence >= CONFIDENCE_THRESHOLD:
                    line.spec = interp.spec
                    line.family = None
                    store.put_interpretation(
                        "part", interp.to_dict(), "llm", kind_hint=hint,
                        raw_value=cache_value, footprint=footprint,
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
                                              consult=not interpreter_dead,
                                              headline=line.footprint_headline or "")
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
        # ``resolve`` has just live-verified every active choice in one batch and
        # refreshed its stock/price cache. Return those same approved lists to
        # the page: asking /api/part?verify=1 immediately afterward would verify
        # the identical choices a second time and make a checkbox look stalled.
        approved_lists = []
        seen_specs: set[tuple[str, str, str, str]] = set()
        for line in requirements.lines:
            if line.dnp or line.spec is None:
                continue
            key = (line.spec.kind, line.spec.value,
                   line.spec.package, line.spec.qualifier)
            if key in seen_specs:
                continue
            seen_specs.add(key)
            approved_lists.append({"spec": line.spec.to_dict(),
                                   "housePart": store.lookup(line.spec)})
        out = {"resolution": result, "approvedLists": approved_lists}
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
        visual = body.get("visualEvidence") or {}
        target = line.get("designator") or ""
        interpretation_hint = (f"{prefix}\x1f{target}" if visual else prefix)
        visual_token = f"\x1fread-plan:{READ_PLAN_SCHEMA_VERSION}"
        if visual.get("digest"):
            visual_token += (f"\x1fvisual:{visual.get('schemaVersion') or 1}:"
                             f"{visual['digest']}")
        key = {"kind_hint": interpretation_hint,
               # the part number belongs in the key: change it in the schematic
               # and this is a different part, which must be read again
               "raw_value": (f"{_part_cache_value(line.get('value') or '', line.get('attributes'))}"
                             f"\x1f{code}{visual_token}"),
               "footprint": line.get("footprint") or ""}
        cached = store.get_interpretation("read", **key)
        result = (cached or {}).get("result") or {}
        # A reading carries the spec table its terms are written in ("catalog",
        # even when null). One that doesn't predates that vocabulary, so its plan
        # can't seed anything — re-read the part rather than seed the box from it.
        # And a reading whose plan sieves on a column we have since MEASURED to be
        # a lie is worse than none: it would reject every good part, for ever.
        if (result.get("search") and "catalog" in result
                and not self._stale_plan(result.get("plan"))):
            accepted_spec = (result.get("spec")
                             if self._reading_can_auto_accept(result) else None)
            if accepted_spec:
                store.put_interpretation(
                    "part", {"spec": accepted_spec,
                             "rationale": result.get("rationale") or ""},
                    "llm", kind_hint=interpretation_hint,
                    raw_value=_part_cache_value(line.get("value") or "",
                                                line.get("attributes")),
                    footprint=line.get("footprint") or "",
                    confidence=result.get("confidence"))
            return {"reading": result, "requirementSpec": accepted_spec,
                    "cached": True}

        dossier = {
            "schematic": {
                "designators": ln.get("designators") or [],
                "prefix": prefix,
                "value": line.get("value") or "",
                "footprint": line.get("footprint") or "",
                "mpn": ln.get("mpn") or "",
                "code": code,
                "attributes": dict(ln.get("attributes") or {}),
            },
            "catalog": self._catalog_record(code),
            "convention": self._convention(line.get("designator") or ""),
        }
        if visual:
            dossier["visualEvidence"] = {
                "schemaVersion": visual.get("schemaVersion") or 1,
                "digest": visual.get("digest") or "",
                "designator": line.get("designator") or "",
                "sheets": visual.get("sheets") or [],
                "boardImage": visual.get("boardImage"),
                "boardCrops": visual.get("boardCrops") or [],
                "images": visual.get("images") or [],
                "placements": visual.get("placements") or [],
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
        # This same lazy read has already named the canonical requirement. Feed
        # it to the cache-only intake path; do not wake a second agent next
        # Refresh merely to obtain the same SpecKey in another JSON envelope.
        accepted_spec = (reading.get("spec")
                         if self._reading_can_auto_accept(reading) else None)
        if accepted_spec:
            store.put_interpretation(
                "part", {"spec": accepted_spec,
                         "rationale": reading.get("rationale") or ""},
                "llm", kind_hint=interpretation_hint,
                raw_value=_part_cache_value(line.get("value") or "",
                                            line.get("attributes")),
                footprint=line.get("footprint") or "",
                confidence=reading.get("confidence"))
        return {"reading": reading, "requirementSpec": accepted_spec,
                "cached": False}

    @staticmethod
    def _reading_can_auto_accept(reading: dict) -> bool:
        """Reject automatic naming when a stated rating has no fixed meaning."""
        intent = reading.get("intent") or {}
        return (float(reading.get("confidence") or 0) >= CONFIDENCE_THRESHOLD
                and intent.get("ratingAmbiguous") is not True)

    def _stale_plan(self, plan: dict | None) -> bool:
        """Was this plan written against a column we now know is a lie?

        Judgments are cached forever, and that is right — but a cached plan that
        sieves on ``is_polarized`` was cached BEFORE we measured that the column
        is ``false`` on every aluminium electrolytic. Replaying it would keep
        rejecting all 36 good parts long after the bug was fixed, and the
        engineer would have no way to know why. So a plan naming a column that
        cannot prove anything is not a plan: throw it away and read the part
        again. Costs one judgment, once, and the DB heals itself.

        ⚠️ SCOPED TO THE PLAN'S OWN CATEGORY. It used to test against a flat union
        of every category's dead columns, and a column is only dead IN A CATEGORY:
        ``color`` proves nothing on a 7-segment display and proves plenty on an
        LED; ``has_i2c`` is a lie on an accelerometer and is the whole point of an
        io_expander. The union condemned 16 categories' honest columns, so every
        LED, LDO, MCU, ADC and I/O-expander plan was discarded on sight and the
        agent re-asked from scratch, for ever. A cache that never hits is not a
        cache, and this one was paying for a judgment on every single search.
        """
        from ..datasources.jlc.alternates import UNPROVABLE_COLUMNS

        plan = plan or {}
        dead = set(UNPROVABLE_COLUMNS.get(str(plan.get("category") or ""), ()))
        return any(str(t.get("field")) in dead for t in (plan.get("sieve") or []))

    def _reading_spec(self, line: dict) -> dict | None:
        """The SpecKey the READ already produced for this line, if it can stand
        as the requirement's name.

        It usually can. The read is the same agent, and it ran with the catalog
        record in front of it — it knows more about this part than a second
        judgment would. The one case it cannot answer is a line the schematic
        never named at all (no value, no part number): there, the engineer's
        search words are the only thing that knows what the part IS ("zener 10V"
        for a diode the design left blank), and only the agent can weigh them.
        """
        if not (line.get("value") or line.get("code")):
            return None                 # the schematic said nothing — must ask
        read = (self._store().get_interpretation(
            "read",
            kind_hint=_kind_hint(line.get("designator") or ""),
            raw_value=(f"{_part_cache_value(line.get('value') or '', line.get('attributes'))}"
                       f"\x1f{line.get('code') or ''}"),
            footprint=line.get("footprint") or "",
        ) or {}).get("result") or {}
        spec = read.get("spec")
        if not spec:
            return None
        return {"spec": spec,
                "rationale": read.get("rationale")
                or "named from the catalog record when the part was opened"}

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
            # the part's CLASS, from the catalog itself. The index has no honest
            # column for it (its is_polarized is false on every electrolytic,
            # its is_schottky false on every schottky) — this is the only place
            # that knows a TVS from a zener, and it is what a part-class note
            # keys on.
            "firstType": d.get("firstTypeName"),
            "secondType": d.get("secondTypeName"),
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
        line = self._search_line(body)
        category = str(body.get("category") or "").strip()
        sieve = body.get("sieve")
        if not terms and not isinstance(sieve, list):
            # A FAMILY line searches itself. The designer already typed the words
            # ("ULN2003") and the board already states the land — there is nothing
            # for the engineer to type, and making them retype it would be asking
            # them to repeat the schematic back to us.
            family_key = {"footprint": str(line.get("footprint") or "").strip(),
                          "raw_value": str(line.get("family") or "").strip()}
            cached_before = self._store().get_interpretation("family", **family_key)
            planned = self._family_plan(line)
            if planned is None:
                raise ApiError("'terms' is required — type what you want")
            plans, fam = planned
            found = self._merge(run_search(self._datasource_factory(), p)
                                for p in plans)
            # A cached family judgment that no longer produces even one row was
            # made against catalog state we can no longer reproduce. Re-read it
            # once instead of replaying a permanent, convincing empty answer.
            # User-confirmed knowledge is never removed by this automatic path.
            if (found["scanned"] == 0 and cached_before
                    and cached_before.get("source") == "llm"
                    and self._store().delete_interpretation(
                        "family", source="llm", **family_key)):
                plans, fam = self._family_plan(line) or ([], {})
                found = self._merge(run_search(self._datasource_factory(), p)
                                    for p in plans)
            return {"terms": line["family"], "planned": plans[0],
                    "queries": [f["query"] for f in found["parts"]],
                    "judged": False, "family": fam,
                    **{k: v for k, v in found.items() if k != "parts"}}
        if not terms:
            raise ApiError("'terms' is required — type what you want")
        if isinstance(sieve, list):
            # The engineer edited the terms themselves: fire exactly that, no
            # judgment call. The terms are now the WHOLE truth — the query is
            # rebuilt from them, so dropping a term really drops it instead of
            # the net quietly re-asserting it.
            from ..resolver.orchestration.search import NET_COLUMNS

            sieve = [p for p in sieve if isinstance(p, dict) and p.get("field")]
            fts = category == "components" or not category
            net = {
                param: t["value"]
                for param, column in NET_COLUMNS.items()
                for t in sieve
                if (t.get("op") == "eq"
                    or (param == "package" and t.get("op") == "in"
                        and isinstance(t.get("value"), list)))
                if t.get("field") == column
            }
            if fts:
                # the keyword net is the words PLUS whatever net params survived
                # the engineer's edit — `components` honours `package`, and a
                # family search that quietly lost it would fetch every package
                # the family ships in. Terms they dropped stay dropped: the net
                # is rebuilt FROM the sieve, never re-asserted behind their back.
                net = {k: v for k, v in net.items() if k == "package"}
                net["search"] = terms or str(line.get("family") or "")
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
                "attributes": dict(ln.get("attributes") or {}),
                # the family the designer typed ("ULN2003") and the footprint's
                # own geometry — the two things that decide which part may mount
                "family": ln.get("family") or "",
                "headline": ln.get("footprintHeadline") or "",
                "code": str(body.get("code") or
                            (ln.get("providerRefs") or {}).get("jlcpcb")
                            or "").strip()}

    @staticmethod
    def _merge(results) -> dict:
        """Union several searches over ONE land into one table.

        The catalog spells a land several ways and the index takes one spelling
        per request, so a land can need more than one request. The engineer is
        picking a part for a board, not reading a query log: they get one table.
        Deduped by code — a part reached by two spellings is still one part.
        """
        parts, candidates, misses, seen = [], [], [], set()
        scanned = 0
        truncated = False
        for found in results:
            parts.append(found)
            scanned += found["scanned"]
            truncated = truncated or found["truncated"]
            for row in found["candidates"]:
                if row["code"] not in seen:
                    seen.add(row["code"])
                    candidates.append(row)
            for row in found["misses"]:
                if row["code"] not in seen:
                    seen.add(row["code"])
                    misses.append(row)
        return {"parts": parts, "candidates": candidates, "misses": misses,
                "proved": parts[0]["proved"] if parts else [],
                "query": parts[0]["query"] if parts else None,
                "scanned": scanned, "truncated": truncated}

    def _catalog_packages(self, family: str) -> list[tuple[str, int]]:
        """The packages the CATALOG stocks this family in, commonest first.

        The catalog's own vocabulary, which is the only spelling that matches
        anything. Fetched by asking for the family and nothing else — one cheap
        query — because a package judged from the library's footprint name is a
        guess AT the catalog's word rather than a reading OF it, and the two
        disagree exactly where it hurts: the library says ``SOIC-4`` and the
        catalog says ``MBS``; the library says ``SOP04`` and the catalog says
        ``SOP-4-2.54mm``. Both guesses return ZERO rows while looking right.
        """
        rows = self._datasource_factory().discover(
            {"category": "components", "params": {"search": family}})
        counts: dict[str, int] = {}
        for r in rows:
            pkg = str(r.get("package") or "").strip()
            if pkg:
                counts[pkg] = counts.get(pkg, 0) + 1
        listing = PackageListing(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))
        listing.truncated = len(rows) >= 100
        return listing

    def _family_read(self, line: dict,
                     packages: list[tuple[str, int]] | None = None) -> dict:
        """What the WEB knows about this family — cached forever, per family and
        footprint. ``{}`` when there is no family or no judgment to be had.

        The only judgment that costs a web search, so it is asked once per
        (family, footprint) and never again: what a suffix MEANS does not change.
        It answers what the catalog cannot — which complete part number belongs in
        THIS land, which of the catalog's packages that land IS, and which
        lookalikes share the land but not the part (a PCF8574A is a different I2C
        address in an identical body).
        """
        family = str(line.get("family") or "").strip()
        footprint = str(line.get("footprint") or "").strip()
        if not family:
            return {}
        store = self._store()
        cached = store.get_interpretation("family", footprint=footprint,
                                          raw_value=family)
        if cached:
            return (cached.get("result") or {})
        interpreter = self._interpreter_factory()
        read = getattr(interpreter, "read_family", None)
        if read is None:
            return {}
        got = read(family, footprint, str(line.get("headline") or ""),
                   packages if packages is not None
                   else self._catalog_packages(family))
        if got is None:
            return {}                       # interpreter down — the sweep still works
        store.put_interpretation("family", got, "llm", footprint=footprint,
                                 raw_value=family,
                                 confidence=got.get("confidence"))
        return got

    def _family_plan(self, line: dict) -> tuple[dict, dict] | None:
        """The query for a family line: ``family + package``. Nothing else.
        Returns ``(plan, familyRead)``.

        ⚠️ PYTHON COMPOSES THIS QUERY — the one authorized exception to ADR-0006
        (Craig, 2026-07-13; see ADR-0008). It is not judgment: the words are the
        DESIGNER'S OWN, passed through verbatim, and the package is a judgment the
        agent already made. Asking an agent to "plan" a query whose every term is
        already known would be theatre.

        The package comes from the CATALOG'S OWN LIST for this family, with the
        footprint judgment as the fallback. Never the other way round: a package
        the catalog does not spell that way matches nothing, however plausible.

        The class is deliberately NOT in here. JLC's class labels are inconsistent
        WITHIN one family — C2886577 (an MB10S, the part already on our board) is
        filed under "Diodes - General Purpose" while its siblings are "Bridge
        Rectifiers" — so a class term would reject good parts while looking like it
        filtered. The class is a label, never a filter.
        """
        family = str(line.get("family") or "").strip()
        footprint = str(line.get("footprint") or "").strip()
        if not family or not footprint:
            return None
        cached = self._store().get_interpretation("family", footprint=footprint,
                                                  raw_value=family)
        fam = (cached or {}).get("result") or {}
        packages = list(fam.get("packages") or [])
        if not packages:
            # First time for this (family, footprint). Ask the catalog which
            # packages it stocks the family in — its OWN vocabulary — and let the
            # judgment choose from that. Once answered it is cached, and this
            # probe never runs again.
            offered = self._catalog_packages(family)
            known = {p for p, _ in offered}
            fam = self._family_read(line, offered)
            # A package the catalog does not spell that way matches NOTHING, so it
            # is dropped rather than fired — a search returning zero because the
            # word was wrong looks exactly like a family JLC does not stock.
            chosen = list(fam.get("packages") or [])
            if getattr(offered, "truncated", False):
                # The bare-family listing is only a sample. A package absent
                # from it is unknown, not false: prove each proposed spelling
                # with a narrow catalog request before allowing it into a plan.
                for package in chosen:
                    if package not in known:
                        rows = self._datasource_factory().discover({
                            "category": "components",
                            "params": {"search": family, "package": package},
                        })
                        if rows:
                            known.add(package)
            packages = [p for p in chosen if p in known]
            if not packages:
                judged = self._judged_package(
                    footprint, headline=str(line.get("headline") or "")) or ""
                packages = [judged] if judged in known else []
            if not packages:
                raise ApiError(
                    f"can't tell which package “{footprint}” is. The catalog "
                    f"stocks {family} in: "
                    + ", ".join(p for p, _ in offered[:8])
                    + " — search with the package you want.")
        confidence = fam.get("confidence")
        if (confidence is not None
                and float(confidence) < CONFIDENCE_THRESHOLD):
            why = str(fam.get("rationale") or "").strip()
            raise ApiError(
                f"“{family}” is not specific enough to choose an orderable part"
                + (f": {why}" if why else "")
                + " — describe the required voltage, function, or exact family.")
        # ONE land, but the catalog may spell it several ways — SOIC-8 and SOP-8
        # are the same 3.9mm body and hold DIFFERENT parts. The index takes only
        # one `package` per request, so we fire ONE REQUEST PER SPELLING and union
        # them, rather than widening the net to the family alone: the index caps a
        # listing at 100 rows and will not go higher (measured — `1N4148`, `LM358`
        # and `AMS1117` all return exactly 100, and `limit=500` changes nothing),
        # so a bare-family net would quietly truncate a popular family. Each
        # package-filtered request is far under the cap.
        #
        # Every request still carries the WHOLE set as one sieve term, so each part
        # is proven against the land, not against the one spelling that fetched it.
        shown = " or ".join(packages)
        sieve = [{"field": "package", "op": "in", "value": packages}]
        plans = [{"mode": "fts", "category": "components",
                  "net": {"search": family, "package": p},
                  "sieve": sieve, "lookingFor": {"package": shown},
                  "say": f"{family} that fit {footprint} ({shown})",
                  "confidence": 1.0} for p in packages]
        return (plans, fam)

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
        if (cached and (cached["result"] or {}).get("mode")
                and not self._stale_plan(cached["result"])):
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

    def _judged_package(self, footprint: str, consult: bool = True,
                        headline: str = "") -> str | None:
        """The catalog package for a library footprint name — cache first,
        else one agent judgment, cached forever. '' (nothing standard) is a
        valid cached answer; None means no judgment available. With
        ``consult=False`` only the cache answers (cache loads).

        ``headline`` is the library's own description of the footprint, and it
        is what makes the judgment honest: "SO16" cannot say whether the body is
        3.9mm or 7.5mm — "Small Outline package 150 mil" can, and those are two
        different catalog packages. Cached by footprint, since the geometry is a
        property OF the footprint, not of the part wearing it.
        """
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
        try:
            j = judge(footprint, headline)
        except TypeError:            # an interpreter that predates the geometry
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
            store = self._store()
            recorded = apply_approvals(store, approvals)
            approved_lists = []
            seen: set[tuple[str, str, str, str]] = set()
            for approval in approvals:
                spec = SpecKey.from_dict(approval["spec"])
                key = (spec.kind, spec.value, spec.package, spec.qualifier)
                if key not in seen:
                    seen.add(key)
                    approved_lists.append({"spec": spec.to_dict(),
                                           "housePart": store.lookup(spec)})
            return {"recorded": recorded, "approvedLists": approved_lists}
        except (KeyError, ValueError) as exc:
            raise ApiError(str(exc))

    def api_key(self, body: dict) -> dict:
        """Name the requirement a pick satisfies — the AVL's key for it, in
        every future design. The AGENT decides it; the engineer is never asked
        to fill in database fields (that is how a "1000V" once landed in a
        diode's value). Recorded user-provenance, because the pick is the
        engineer's act — and a later pick re-keys it.

        It is answered WITHOUT waking the agent wherever the answer is already
        known, because this sits behind a checkbox and a checkbox must not stall:

        1. a key already recorded for this line — it stands;
        2. the READING the panel made when the part was opened. That is the same
           agent, with MORE to go on (it had the catalog record in front of it),
           and it already produced a SpecKey. Asking a second time spends a
           second judgment to reach the same answer in different words;
        3. only when the schematic never named the part — no value, no part
           number — are the engineer's own search words the only thing that
           knows what it is. THEN ask, because nothing else can say.

        ``{lineIndex, requirements, terms, part}`` → ``{spec, rationale}``."""
        line = self._search_line(body)
        part = body.get("part") or {}
        if not part.get("code"):
            raise ApiError("'part' (the approved part) is required")
        store = self._store()
        key = {"kind_hint": _kind_hint(line.get("designator") or ""),
               "raw_value": _part_cache_value(line.get("value") or "",
                                               line.get("attributes")),
               "footprint": line.get("footprint") or ""}
        terms = str(body.get("terms") or "").strip()
        remembered = (store.get_interpretation("part", **key) or {}).get("result") or {}
        cached_spec = (remembered.get("spec") or {}) if not terms else {}
        if cached_spec:   # nothing new was searched — the recorded key stands
            return {"spec": cached_spec,
                    "rationale": remembered.get("rationale") or "",
                    "cached": True}
        named = self._reading_spec(line)
        if named:
            store.put_interpretation("part", named, "user", **key)
            return {**named, "cached": True}
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


def run_app(app: HendleyApp, port: int = 8341, open_browser: bool = True,
            interpreter: str | None = None) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(app))
    url = f"http://127.0.0.1:{server.server_port}/"
    print(f"Hendley app: {url}  (Ctrl-C to stop)")
    if interpreter:
        print(f"Interpreter: {interpreter}")
    if open_browser and not _open_browser_quietly(url):
        print(f"(no local browser found — open {url} yourself)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
