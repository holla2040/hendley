"""``hendley mcp`` — Hendley's part search as MCP tools (ADR-0010).

Claude Code launches this over stdio, once per session; nothing runs in the
background. The tool functions below are plain functions over the existing
machinery — ``run_search`` (ADR-0007), ``JLCDataSource``, the house-parts DB —
plus the DigiKey and Mouser sources. ``main()`` imports the ``mcp`` SDK, which
is an optional extra, so the core install stays ``requests`` only.

Nothing here writes to Fusion. ``approve_part`` is the one write: it records
a part chosen while drawing in the parts DB, through the app's own key and
approval path, so the next Refresh / ``hendley pcba`` resolves it (Craig,
2026-10-19).
"""

from __future__ import annotations

from typing import Any

from .datasources import digikey, mouser
from .datasources.jlc.alternates import CATEGORIES, CATEGORY_COLUMNS, EMPTY_CATEGORIES
from .datasources.jlc.source import JLCDataSource
from .domain.model import SpecKey
from .resolver.orchestration.search import run_search

LIBRARY = {"base": "Basic", "expand": "Extended"}

INSTRUCTIONS = """\
Hendley finds JLCPCB-assemblable parts and checks US availability.

Workflow for "find me a <part>":
1. list_categories → pick the jlcsearch table and see which columns can prove a term.
2. search_parts with a plan. The index HONOURS ONLY package plus one value param
   (resistance / capacitance) and silently ignores the rest, so put every
   constraint in the sieve; Python proves each candidate against live JLC data.
3. part_detail on the few you like (full parameters, datasheet, price tiers).
4. us_availability on their MPNs for DigiKey / Mouser stock and lifecycle.
5. After the engineer places the part in Fusion and says it is approved,
   approve_part(designator, code, alternates) records it in the parts DB so
   later BOM pulls resolve it. Only on the engineer's say-so, never on your own.

Recommend, never pick silently. The engineer's bias: same package first, then
high stock (popular = supply-chain-safe, worth paying a little more), then
price. Basic parts carry no JLC setup fee; each Extended part adds about $3 per
order. Show traps (same land, different part) — never substitute silently.
Hendley never edits the Fusion design: name the part, the engineer places it.
"""


def list_categories() -> dict:
    """Every jlcsearch table and the typed columns a sieve term can be proven
    against. ``components`` is the keyword table (mode "fts")."""
    return {"categories": [
        {"slug": c, "columns": list(CATEGORY_COLUMNS.get(c, ("package",)))}
        for c in sorted(CATEGORIES) if c not in EMPTY_CATEGORIES]}


def _compact(c: dict) -> dict:
    out = {
        "code": c.get("code"),
        "mpn": c.get("model"),
        "manufacturer": c.get("manufacturer"),
        "package": c.get("package"),
        "library": LIBRARY.get(c.get("libraryType") or "", c.get("libraryType")),
        "stock": c.get("liveStock"),
        "unitPrice1": c.get("unitPrice1"),
        "class": c.get("secondTypeName"),
        "description": c.get("description"),
        "keyParams": c.get("keyParams") or {},
    }
    if c.get("proof"):
        out["proved"] = {p["field"]: p.get("shown") for p in c["proof"] if p.get("ok")}
    if c.get("failed"):
        out["failed"] = c["failed"]
    return out


def search_parts(plan: dict, exclude: list[str] | None = None, limit: int = 25,
                 datasource: Any = None) -> dict:
    """Run an ADR-0007 search plan: fire the net at jlcsearch, live-verify every
    hit against the JLC API, prove each against every sieve term.

    plan:
      mode      "category" (a jlcsearch table) | "fts" (keyword over part
                names, category "components") | "code" (one C-code)
      category  table slug from list_categories (mode "category")
      net       the coarse query: {"package": "SOT-23"} or a list of package
                spellings for one land; at most one value param
                (resistance / capacitance); {"search": "AP2112"} for "fts";
                {"code": "C51118"} for "code"
      sieve     EVERY constraint, as [{"field", "op", "value", "unit"?}].
                op: eq ne in contains gte lte gt lt isTrue isFalse.
                field: a table column, or a catalog parameter name
                ("Output Voltage", "Voltage Rating"). Strings with units
                compare numerically only when "unit" is declared ("V", "mA").

    Returns proven ``candidates`` (index order, unranked), ``misses`` with the
    failed term and why, the ``query`` actually sent, and ``scanned``.
    """
    result = run_search(datasource or JLCDataSource(), plan, tuple(exclude or ()))
    candidates = result["candidates"]
    return {
        "query": result["queries"],
        "scanned": result["scanned"],
        "truncated": result["truncated"],
        "candidateCount": len(candidates),
        "missCount": len(result["misses"]),
        "candidates": [_compact(c) for c in candidates[:limit]],
        "misses": [_compact(m) for m in result["misses"][:limit]],
    }


def part_detail(codes: list[str], datasource: Any = None) -> dict:
    """Live JLC catalog facts for C-codes: MPN, package, Basic/Extended, stock,
    price tiers, every published parameter, datasheet."""
    facts = (datasource or JLCDataSource()).verify(codes)
    out = {}
    for code, f in facts.items():
        if not f.found:
            out[code] = {"found": False}
            continue
        d = f.raw
        out[code] = {
            "found": True,
            "mpn": f.mpn,
            "manufacturer": f.manufacturer,
            "package": d.get("componentSpecification"),
            "library": LIBRARY.get(f.offer_class or "", f.offer_class),
            "stock": f.stock,
            "class": d.get("secondTypeName"),
            "description": f.description,
            "priceTiers": f.price_tiers,
            "parameters": {p.get("parameterName"): p.get("parameterValue")
                           for p in d.get("parameters") or []},
            "datasheetUrl": d.get("dataManualUrl"),
        }
    return out


def us_availability(mpns: list[str], sources: list[Any] | None = None) -> dict:
    """DigiKey and Mouser stock, lifecycle, price breaks, lead time and links
    for exact MPNs. A source without keys reports ``not configured``."""
    if sources is None:
        sources = [(digikey.DigiKeyDataSource(), digikey.offer),
                   (mouser.MouserDataSource(), mouser.offer)]
    out: dict[str, dict] = {m: {} for m in mpns}
    for source, offer in sources:
        if not source.configured:
            for m in mpns:
                out[m][source.name] = {"error": "not configured"}
            continue
        try:
            facts = source.verify(mpns)
        except Exception as exc:  # noqa: BLE001 — one source down must not hide the other
            for m in mpns:
                out[m][source.name] = {"error": str(exc)}
            continue
        for m in mpns:
            f = facts.get(m.strip())
            if f is None or not f.found:
                out[m][source.name] = {"found": False}
                continue
            out[m][source.name] = {
                "found": True, "manufacturer": f.manufacturer, "stock": f.stock,
                "lifecycle": f.lifecycle, "priceBreaks": f.price_tiers,
                **offer(f)}
    return out


def approved_parts(kind: str | None = None, store: Any = None) -> dict:
    """The house-parts database: every approved part list (ranked choices per
    spec), optionally one kind ("R", "C", "U", …). Check here before searching
    — a part already approved for a spec should be reused. Read only; use
    approve_part to add to it."""
    if store is None:
        from .knowledge.partsdb import PartsDb
        store = PartsDb()
    return {"houseParts": store.list_parts(kind)}


def approve_part(designator: str, code: str, alternates: list[str] | None = None,
                 app: Any = None, datasource: Any = None) -> dict:
    """Record a part the engineer approved while drawing, so the next Refresh /
    ``hendley pcba`` resolves it. Call only on the engineer's say-so. The part
    must already be placed: the requirement is named from the live schematic
    line exactly as Refresh names it, so the recorded key is the one later BOM
    pulls look up.

    designator  the placed part, e.g. "U3" (any designator of a grouped line)
    code        the JLC C-code approved for it
    alternates  further C-codes approved as backups, in order

    ``code`` becomes the chosen part when the requirement has no approved list
    yet; otherwise it joins the list as an alternate. Every code is verified
    live, and alternates must share ``code``'s catalog package (one land
    spelled two ways, e.g. SOIC-8 / SOP-8, is refused here: add it in the app).
    ``resolvesOnRefresh`` re-runs Refresh's own lookup on the same parts and
    says whether the list will be found. Never changes the Fusion design.
    """
    try:
        return _approve_part(designator, code, alternates, app, datasource)
    except Exception as exc:  # noqa: BLE001 — an MCP tool answers, never crashes
        return {"error": f"{type(exc).__name__}: {exc}"}


def _named_line(app, design, parts, designator):
    """The requirements as Refresh names them, and the index of this part."""
    from .requirements import requirements_from_design

    requirements = requirements_from_design(design, parts, 1)
    app._interpret_lines(requirements, consult_interpreter=False,
                         visual_available=True)
    app._apply_exact_search_seeds(requirements)
    index = next((i for i, ln in enumerate(requirements.lines)
                  if designator in ln.designators), None)
    return requirements, index


def _approve_part(designator, code, alternates, app, datasource) -> dict:
    from .app.server import HendleyApp, _kind_hint, _part_cache_value
    from .ingestion.fusion.live_design import extract_schematic

    app = app or HendleyApp()
    codes = list(dict.fromkeys(c.strip() for c in [code, *(alternates or [])]
                               if c and c.strip()))
    if not codes:
        return {"error": "no C-code given"}

    # 1. The schematic line, read and named exactly as Refresh does it.
    design, parts = extract_schematic(app._bridge_factory(app.fusion_host))
    requirements, index = _named_line(app, design, parts, designator)
    if index is None:
        return {"error": f"{designator} is not on the open schematic — place it first"}
    line = requirements.lines[index]
    if line.dnp:
        return {"error": f"{designator} is marked DNP; nothing to approve"}
    doc = requirements.to_dict()

    # 2. Every code live, all on one package, before anything is written.
    facts = (datasource or app._datasource_factory()).verify(codes)
    missing = [c for c in codes if not (facts.get(c) and facts[c].found)]
    if missing:
        return {"error": f"not found at JLC: {', '.join(missing)}"}
    package = facts[codes[0]].raw.get("componentSpecification")
    other = [f"{c} is {facts[c].raw.get('componentSpecification')}" for c in codes[1:]
             if facts[c].raw.get("componentSpecification") != package]
    if other:
        return {"error": f"{codes[0]} is {package}; " + "; ".join(other)}

    # 3. The requirement's name: the line's recorded spec, else the app's key.
    if line.spec:
        spec = line.spec.to_dict()
    else:
        primary = facts[codes[0]]
        spec = app.api_key({"lineIndex": index, "requirements": doc,
                            "part": {"code": codes[0], "mpn": primary.mpn,
                                     "manufacturer": primary.manufacturer,
                                     "package": package,
                                     "description": primary.description}})["spec"]
    if spec.get("package") != package:
        return {"error": f"{designator} is named with package {spec.get('package')!r}, "
                         f"but {codes[0]} is {package}", "spec": spec}

    # 4. Record through the app's approval path, and make the name the
    #    engineer's: Refresh honours a key on a pinned line (or a design with
    #    images) only when it is user-recorded.
    store = app._store()
    house = store.lookup(SpecKey.from_dict(spec)) or {}
    listed = {(c.get("providerRefs") or {}).get("jlcpcb") for c in house.get("choices") or []}
    first_pick = not house.get("choices")
    approvals = [{"spec": spec, "lcsc": c, "mpn": facts[c].mpn,
                  "manufacturer": facts[c].manufacturer,
                  "rank": 1 if (first_pick and n == 0) else 999,
                  "liveStock": facts[c].stock, "design": design,
                  "note": "approved while drawing (hendley mcp)"}
                 for n, c in enumerate(codes) if c not in listed]
    if approvals:
        app.api_approve({"approvals": approvals})
    if not line.family:
        store.put_interpretation(
            "part", {"spec": spec, "rationale": "approved while drawing"}, "user",
            kind_hint=_kind_hint(designator), footprint=line.footprint or "",
            raw_value=_part_cache_value(line.comment or "", line.attributes))

    # 5. Search history, which is how a family line (a value like "MT3608")
    #    finds its approved list. The app validates only a pick its own live
    #    search showed, so run that search for the line.
    history = None
    if line.family:
        history = []
        try:
            found = app.api_search({"lineIndex": index, "requirements": doc})
            receipt = found["searchReceipt"]["id"]
            eligible = {c.get("code") for c in found.get("candidates") or []}
            for n, c in enumerate(codes):
                if c not in eligible:
                    history.append({"code": c, "validated": False,
                                    "why": "not in the family search for this land"})
                    continue
                app.api_search_seed_validate({
                    "receipt": receipt, "selectedRef": c,
                    "action": "mounted" if (first_pick and n == 0) else "alternate",
                    "canonicalSpec": spec, "lineIndex": index, "requirements": doc})
                history.append({"code": c, "validated": True})
        except Exception as exc:  # noqa: BLE001 — reported through resolvesOnRefresh
            history.append({"validated": False, "why": f"{type(exc).__name__}: {exc}"})

    # 6. Prove it: Refresh's own naming, on the same parts, must find the list.
    again, i = _named_line(app, design, parts, designator)
    named = again.lines[i].spec if i is not None else None
    resolves = bool(named and named.to_dict() == SpecKey.from_dict(spec).to_dict()
                    and (store.lookup(named) or {}).get("choices"))

    pinned = (line.provider_refs or {}).get("jlcpcb")
    notes = []
    if not resolves:
        notes.append("recorded, but the next Refresh will not find this list for "
                     f"{designator}; open it in the Hendley app to finish")
    if pinned and pinned != codes[0]:
        notes.append(f"the schematic's LCSC attribute says {pinned}; set it to "
                     f"{codes[0]} in Fusion if that is the part to mount")
    return {
        "design": design,
        "line": {"designators": line.designators, "value": line.comment,
                 "footprint": line.footprint, "schematicLCSC": pinned},
        "spec": spec,
        "recorded": [a["lcsc"] for a in approvals],
        "alreadyApproved": [c for c in codes if c in listed],
        "approvedList": [{"code": (c.get("providerRefs") or {}).get("jlcpcb"),
                          "mpn": c.get("mpn"), "rank": c.get("rank")}
                         for c in (store.lookup(SpecKey.from_dict(spec)) or {})
                         .get("choices") or []],
        "searchHistory": history,
        "resolvesOnRefresh": resolves,
        "notes": notes,
    }


def main() -> None:
    try:
        from mcp.server.mcpserver import MCPServer
    except ImportError as exc:
        raise SystemExit('hendley mcp needs the MCP SDK: pip install -e ".[mcp]"') from exc
    server = MCPServer("hendley", instructions=INSTRUCTIONS)
    for fn in (list_categories, search_parts, part_detail, us_availability,
               approved_parts, approve_part):
        server.tool()(_public(fn))
    server.run("stdio")


def _public(fn):
    """The tool as the client sees it: the test seams (``datasource``,
    ``sources``, ``store``) are not parameters an agent should pass."""
    import functools
    import inspect

    sig = inspect.signature(fn)
    hidden = {"datasource", "sources", "store", "app"}

    @functools.wraps(fn)
    def tool(**kwargs):
        return fn(**kwargs)

    tool.__signature__ = sig.replace(
        parameters=[p for p in sig.parameters.values() if p.name not in hidden])
    return tool
