"""``hendley mcp`` — Hendley's part search as MCP tools (ADR-0010).

Claude Code launches this over stdio, once per session; nothing runs in the
background. The tool functions below are plain functions over the existing
machinery — ``run_search`` (ADR-0007), ``JLCDataSource``, the house-parts DB —
plus the DigiKey and Mouser sources. ``main()`` imports the ``mcp`` SDK, which
is an optional extra, so the core install stays ``requests`` only.

Read-only in both directions: nothing here writes to Fusion or the parts DB.
"""

from __future__ import annotations

from typing import Any

from .datasources import digikey, mouser
from .datasources.jlc.alternates import CATEGORIES, CATEGORY_COLUMNS, EMPTY_CATEGORIES
from .datasources.jlc.source import JLCDataSource
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
    — a part already approved for a spec should be reused."""
    if store is None:
        from .knowledge.partsdb import PartsDb
        store = PartsDb()
    return {"houseParts": store.list_parts(kind)}


def main() -> None:
    try:
        from mcp.server.mcpserver import MCPServer
    except ImportError as exc:
        raise SystemExit('hendley mcp needs the MCP SDK: pip install -e ".[mcp]"') from exc
    server = MCPServer("hendley", instructions=INSTRUCTIONS)
    for fn in (list_categories, search_parts, part_detail, us_availability, approved_parts):
        server.tool()(_public(fn))
    server.run("stdio")


def _public(fn):
    """The tool as the client sees it: the test seams (``datasource``,
    ``sources``, ``store``) are not parameters an agent should pass."""
    import functools
    import inspect

    sig = inspect.signature(fn)
    hidden = {"datasource", "sources", "store"}

    @functools.wraps(fn)
    def tool(**kwargs):
        return fn(**kwargs)

    tool.__signature__ = sig.replace(
        parameters=[p for p in sig.parameters.values() if p.name not in hidden])
    return tool
