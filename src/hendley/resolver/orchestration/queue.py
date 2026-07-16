"""The approval queue — ONE batched decision point per order.

The resolution loop's contract with the human: everything the resolver can
settle, it settles; everything it can't becomes one reviewable document —
the **approval queue** — with verified, constraint-filtered, ranked
candidates and their explanations. The engineer clears the queue (approve /
override / defer per entry), the picks are recorded to the knowledge store,
and re-resolution runs clean. One interruption per order, not one per part
(the AGREED sourcing design's target).

The queue is a versioned JSON document (``approvalQueueVersion``): the app's
review screen renders it, the agent can consume the same file, and a future
web UI needs nothing new.

Candidate discovery needs a jlcsearch category. For common kinds the mapping
below drives automatic discovery; for anything else the entry ships with an
empty candidate list and a note — picking a category (or a fuzzy ``search``)
is judgment, and the reviewer supplies it.
"""

from __future__ import annotations

from ...datasources.base import DataSource
from ...domain.model import RequirementsBom, SpecKey
from ...knowledge.partsdb import PartsDb
from ...providers.base import ProviderStrategy
from ..constraints import filter_candidates
from ..ranking import rank_candidates

APPROVAL_QUEUE_VERSION = 1

# kind (spec vocabulary) → jlcsearch category slug, for automatic discovery.
# Deliberately conservative: only unambiguous mappings; everything else is
# the reviewer's call (--category / search in the alternates flow).
KIND_CATEGORIES = {
    "resistor": "resistors",
    "resistor_array": "resistor_arrays",
    "capacitor": "capacitors",
    "led": "leds",
    "diode": "diodes",
    "mosfet": "mosfets",
    "fuse": "fuses",
    "ldo": "ldos",
    "potentiometer": "potentiometers",
    "relay": "relays",
    "switch": "switches",
}


# jlcsearch's dense per-category value params (verified live): resistance in
# ohms, capacitance in farads. Kinds without one discover by package only.
def _value_params(spec: SpecKey) -> dict:
    from ...requirements.specs import base_value

    base = base_value(spec.kind, spec.value)
    if base is None:
        return {}
    if spec.kind == "resistor":
        return {"resistance": int(base) if base == int(base) else base}
    if spec.kind == "capacitor":
        return {"capacitance": f"{base:.15f}".rstrip("0")}
    return {}


_KEY_PARAMS = ("Resistance", "Capacitance", "Inductance", "Tolerance",
               "Voltage Rating", "Voltage Rated", "Power(Watts)")


def _key_params(parameters: list | None) -> dict:
    return {p["parameterName"]: p["parameterValue"] for p in (parameters or [])
            if p.get("parameterName") in _KEY_PARAMS}


def _verified_candidates(datasource: DataSource, category: str, spec: SpecKey,
                         exclude: set[str],
                         search: str | None = None) -> tuple[list[dict], dict | None]:
    """Discover, then verify in one batch. Returns (rows, queryUsed|None) —
    the query comes back so it can be SHOWN: a lookup the engineer can't see
    is a lookup they can't correct, even when the app ran it unasked.

    Discovery runs automatically ONLY where the query is deterministic: a
    dense value param (R/C) or a chip package. A spec with neither (e.g. a
    zener in a library footprint) would query the ENTIRE category unfiltered
    and return arbitrary top-of-index parts — for those, discovery runs only
    with a human-supplied ``search`` string, fired verbatim at the full-text
    index. Composing that string is judgment; it is never done here.
    """
    from ..constraints.engine import is_chip_package

    params = dict(_value_params(spec))
    if is_chip_package(spec.package):
        params["package"] = spec.package  # library-local names never match jlcsearch
    if params and category:
        query = {"category": category, "params": params}
    elif search:
        query = {"category": "components", "params": {"search": search}}
    else:
        return [], None
    return _verify_rows(datasource, datasource.discover(query), exclude), query


def explore(datasource: DataSource, search: str) -> list[dict]:
    """Verified candidates for an engineer-fired free search (no spec) —
    the 'explore alternates' path for schematic-pinned parts. Only verified
    rows return; there is nothing advisory to show."""
    rows = datasource.discover({"category": "components",
                                "params": {"search": search}})
    return [r for r in _verify_rows(datasource, rows, set()) if r["verified"]]


def _verify_rows(datasource: DataSource, rows: list[dict],
                 exclude: set[str]) -> list[dict]:
    """One batched verify over discovery rows → the candidate row shape."""
    codes = [r["code"] for r in rows if r.get("code") and r["code"] not in exclude]
    if not codes:
        return []
    facts = datasource.verify(codes)
    out = []
    for r in rows:
        code = r.get("code")
        if not code or code in exclude:
            continue
        fact = facts.get(code)
        verified = bool(fact and fact.found)
        d = fact.raw if fact else {}
        out.append({
            "code": code,
            "model": (d.get("componentModel") if verified else None) or r.get("mfr"),
            "manufacturer": fact.manufacturer if verified else None,
            "package": (d.get("componentSpecification") if verified else None)
                       or r.get("package"),
            "verified": verified,
            "liveStock": fact.stock if verified else None,
            "jlcsearchStock": r.get("jlcsearch_stock"),
            "unitPrice1": _price1(d) if verified else r.get("price1"),
            "libraryType": d.get("libraryType") if verified else None,
            "firstTypeName": d.get("firstTypeName") if verified else None,
            "secondTypeName": d.get("secondTypeName") if verified else None,
            "description": d.get("describe") if verified else r.get("description"),
            "parameters": d.get("parameters") if verified else None,
            "keyParams": _key_params(d.get("parameters")) if verified else {},
        })
    return out


def _price1(detail: dict) -> float | None:
    ranges = detail.get("priceRanges") or []
    usable = [p for p in ranges if p.get("unitPrice") is not None]
    if not usable:
        return None
    return min(usable, key=lambda p: int(p.get("startQuantity") or 0)).get("unitPrice")


def build_approval_queue(
    store: PartsDb,
    requirements: RequirementsBom,
    resolution: dict,
    *,
    datasource: DataSource,
    strategy: ProviderStrategy,
    searches: dict[int, str] | None = None,
) -> dict:
    """Turn a resolution's escalations into the single reviewable queue.

    ``searches`` maps lineIndex → the engineer's search terms, fired
    verbatim for specs whose discovery isn't deterministic (no dense value
    param, no chip package). Without terms, such entries carry
    ``discovery.needsSearch`` and an empty candidate list — a candidate
    list the engineer didn't ask for is never invented.
    """
    from ..constraints.engine import is_chip_package

    searches = searches or {}
    entries = []
    for esc in resolution.get("escalations", []):
        line = requirements.lines[esc["lineIndex"]]
        spec = line.spec
        required = line.required_qty(requirements.production_quantity)
        avl_refs = {c["ref"] for c in esc.get("choices", []) if c.get("ref")}

        candidates: list[dict] = []
        rejected: list[dict] = []
        unconfirmed: list[dict] = []
        discovery: dict = {"category": None, "automatic": False}
        if spec is not None:
            category = KIND_CATEGORIES.get(spec.kind)
            discovery["category"] = category
            deterministic = bool(_value_params(spec)) or is_chip_package(spec.package)
            search = searches.get(esc["lineIndex"])
            if (deterministic and category) or search:
                discovery["automatic"] = deterministic and category is not None
                envelope = None
                cached = store.get_interpretation("footprint",
                                                  footprint=spec.package)
                if cached:
                    envelope = (cached["result"] or {}).get("envelope")
                raw, used = _verified_candidates(
                    datasource, category, spec, avl_refs, search=search)
                if used:
                    discovery["query"] = used          # shown, always
                    if used["category"] == "components":
                        discovery["search"] = used["params"]["search"]
                valid, rejected, unconfirmed = filter_candidates(
                    spec, raw, envelope=envelope)
                candidates = rank_candidates(
                    valid, required_qty=required, strategy=strategy,
                    store=store, spec=spec)
            else:
                discovery["needsSearch"] = True
                discovery["note"] = (
                    "this spec has no deterministic query — enter search "
                    "terms and fire the search yourself")
        else:
            discovery["note"] = ("no spec on this line — an exact-part decision, "
                                 "not a discovery problem")

        entries.append({
            "lineIndex": esc["lineIndex"],
            "designators": esc["designators"],
            "spec": esc["spec"],
            "ref": esc.get("ref"),
            "mpn": esc.get("mpn"),
            "reason": esc["reason"],
            "requiredQty": required,
            "avlChoices": esc.get("choices", []),
            "discovery": discovery,
            # The proposed AVL: rank 1 + two alternates, exactly what one
            # Approve records. The rest stay visible, promotable only
            # deliberately — and unknown fit NEVER ranks (it sits apart).
            "proposal": candidates[:3],
            "alsoFound": candidates[3:],
            "fitUnconfirmed": unconfirmed,
            "candidates": candidates,
            "rejectedCandidates": rejected,
        })

    return {
        "approvalQueueVersion": APPROVAL_QUEUE_VERSION,
        "design": requirements.design,
        "productionQuantity": requirements.production_quantity,
        "provider": strategy.provider,
        "entries": entries,
    }


def apply_approvals(store: PartsDb, approvals: list[dict]) -> list[dict]:
    """Record the engineer's queue answers as deliberate Part Choices.

    Each approval: ``{"spec": {...}, "lcsc"/"providerRefs"/"mpn"/...,
    "rank"?, "design"?, "note"?}``. Returns the recorded choice rows.
    Re-resolve afterwards — recording never mutates a resolution in place.
    """
    recorded = []
    for a in approvals:
        spec = SpecKey.from_dict(a["spec"])
        provider_refs = dict(a.get("providerRefs") or {})
        if a.get("lcsc"):
            provider_refs.setdefault("jlcpcb", a["lcsc"])
        choice = store.record(
            spec,
            mpn=a.get("mpn"),
            manufacturer=a.get("manufacturer"),
            provider_refs=provider_refs or None,
            rank=int(a.get("rank", 1)),
            description=a.get("description"),
            design=a.get("design"),
            note=a.get("note"),
        )
        recorded.append(choice)
        # Search candidates were live-verified before the engineer could tick
        # them. Preserve that snapshot as advisory display data; BOM resolution
        # still verifies independently when an order decision depends on it.
        ref = provider_refs.get("jlcpcb")
        if ref and "liveStock" in a:
            store.update_verified(
                ref, a.get("liveStock"), a.get("unitPrice"),
                mpn=a.get("mpn"), manufacturer=a.get("manufacturer"))
    return recorded
