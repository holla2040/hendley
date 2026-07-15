"""The resolver — rank-walk each requirement's approved choices against live stock.

This is the mechanical half of BOM resolution (the judgment half — spec
interpretation, alternates trade-offs, approval — belongs to the engineer via
the app, or the agent). Given a canonical Requirements BOM, an injected
:class:`~hendley.datasources.base.DataSource`, and an injected
:class:`~hendley.providers.base.ProviderStrategy`, the resolver:

1. Looks up each spec line's House Part and its ranked active Part Choices
   (the injected :class:`~hendley.knowledge.partsdb.PartsDb`).
2. Live-verifies **every** candidate ref across all lines in **one batched**
   ``DataSource.verify`` call (the AVL adds zero extra round-trips),
   refreshing the store's advisory cache — and backfilling MPN identity —
   as a side effect.
3. Walks each line's choices in rank order and selects the first with live
   stock >= the line's required quantity (designators × per-designator qty ×
   N). Selecting at rank > 1 is a **substitution** — resolved silently,
   reported post-hoc (never auto-recorded: the AVL rank stays deliberate,
   ADR-0001). A line whose whole list fails **escalates** (alternates →
   engineer approval → ``record()`` → re-resolve).

DNP lines are carried through with an ``info`` check and zero required
quantity — never resolved, never escalated, never silently dropped.

The input contract is the canonical Requirements BOM
(:class:`~hendley.domain.model.RequirementsBom`); the pre-port ``hendley
resolve`` request JSON loads directly through it (``lcsc`` is the JLC
provider-ref shorthand). The output dict is a superset of the BOM-render
contract — ``hendley bom`` renders it directly — adding per line: ``spec``,
``housePartId``, ``quantityPer``, ``requiredQty``, ``rankUsed``,
``substitution``, ``liveStock``, ``unitPrice``, ``offerType``, ``dnp``,
``provider``, ``ref``, and ``checks``; plus a top-level ``escalations`` list
of the lines needing a decision (each carrying the per-choice live stock so
the alternates search can seed without re-querying).
"""

from __future__ import annotations

import json
from pathlib import Path

from ...datasources.base import DataSource, PartFact
from ...domain.model import RequirementLine, RequirementsBom, SpecKey, make_check
from ...knowledge.partsdb import PartsDb
from ...providers.base import ProviderStrategy


def load_request_json(path: str | Path) -> RequirementsBom:
    """Load a resolve-request JSON file into the canonical Requirements BOM."""
    return RequirementsBom.from_dict(json.loads(Path(path).read_text()))


def _tier_price_at(fact: PartFact | None, qty: int) -> float | None:
    """Unit price at the tier that applies to qty ({startQuantity, unitPrice} rows)."""
    tiers = fact.price_tiers if fact else []
    applicable = [p for p in tiers
                  if int(p.get("startQuantity") or 0) <= qty
                  and p.get("unitPrice") is not None]
    if applicable:
        return max(applicable, key=lambda p: int(p.get("startQuantity") or 0)).get("unitPrice")
    if tiers:
        return min(tiers, key=lambda p: int(p.get("startQuantity") or 0)).get("unitPrice")
    return None


def resolve(
    store: PartsDb,
    requirements: RequirementsBom,
    *,
    datasource: DataSource,
    strategy: ProviderStrategy,
) -> dict:
    """Resolve a Requirements BOM against the house AVLs and live stock."""
    provider = strategy.provider
    n = requirements.production_quantity

    # Pass 1 — gather every candidate ref (AVL choices + explicit refs).
    houses: list[dict | None] = []
    refs: set[str] = set()
    for line in requirements.lines:
        house = None
        if line.spec is not None and not line.dnp:
            house = store.lookup(line.spec)
            if house:
                refs.update(r for r in
                            (c["providerRefs"].get(provider) for c in house["choices"])
                            if r)
        explicit = line.provider_ref(provider)
        if explicit and not line.dnp:
            refs.add(explicit)
        houses.append(house)

    # One batched live verify for everything; refresh the advisory cache and
    # backfill neutral identity onto LCSC-only choices.
    to_verify = strategy.query_context(requirements, sorted(refs))
    facts: dict[str, PartFact] = datasource.verify(to_verify) if to_verify else {}
    for ref, fact in facts.items():
        if fact.found:
            store.update_verified(ref, fact.stock, _tier_price_at(fact, 1),
                                  provider=provider, mpn=fact.mpn,
                                  manufacturer=fact.manufacturer)

    # Pass 2 — rank-walk each line.
    out_lines: list[dict] = []
    escalations: list[dict] = []
    for i, line in enumerate(requirements.lines):
        required = line.required_qty(n)
        row = {
            "designators": line.designators,
            "comment": line.comment,
            "footprint": line.footprint,
            "provider": provider,
            "ref": None,
            "lcsc": None,  # convenience mirror of ref for the JLC daily driver
            "mpn": line.mpn,
            "manufacturer": line.manufacturer,
            "source": None,
            "note": line.note,
            "dnp": line.dnp,
            "spec": line.spec.to_dict() if line.spec else None,
            "housePartId": houses[i]["id"] if houses[i] else None,
            "quantityPer": line.quantity_per,
            "requiredQty": required,
            "rankUsed": None,
            "substitution": False,
            "liveStock": None,
            "unitPrice": None,
            "offerType": None,
            "offerClass": None,
            "selectedPackage": None,
            "checks": [],
        }

        if line.dnp:
            row["checks"].append(make_check(
                "dnp", f"{','.join(line.designators)}: do-not-populate — "
                       "carried for the record, excluded from resolution and "
                       "order files").to_dict())
        elif line.spec is not None:
            _resolve_spec_line(row, line, houses[i], facts, required,
                               escalations, i, strategy)
        elif line.provider_ref(provider):
            _resolve_explicit_line(row, line, facts, required, escalations, i, strategy)
        else:
            orderable, checks = strategy.evaluate(line, None, required)
            row["checks"].extend(c.to_dict() for c in checks)
            if orderable:
                # Strategy accepted the line without a live fact (e.g. an
                # MPN-based provider): render from the line's own identity.
                row["source"] = "explicit"
            else:
                escalations.append(_escalation(i, line, "no-code", [], provider))
        out_lines.append(row)

    return {
        "design": requirements.design,
        "productionQuantity": n,
        "provider": provider,
        "lines": out_lines,
        "escalations": escalations,
    }


def _stock(facts: dict[str, PartFact], ref: str | None) -> int:
    f = facts.get(ref) if ref else None
    return int(f.stock or 0) if f and f.found else 0


def _fill_selected(row: dict, facts: dict[str, PartFact], ref: str,
                   required: int, strategy: ProviderStrategy) -> None:
    fact = facts.get(ref)
    row["ref"] = ref
    if strategy.provider == "jlcpcb":
        row["lcsc"] = ref
    row["liveStock"] = fact.stock if fact else None
    row["unitPrice"] = _tier_price_at(fact, max(required, 1))
    row["offerType"] = strategy.offer_type
    row["offerClass"] = fact.offer_class if fact else None
    if fact:
        row["selectedPackage"] = (
            (fact.raw or {}).get("componentSpecification") or None)
    if fact and fact.mpn and not row["mpn"]:
        row["mpn"] = fact.mpn


def _resolve_spec_line(row, line, house, facts, required, escalations, index,
                       strategy) -> None:
    provider = strategy.provider
    choices = house["choices"] if house else []
    if not choices:
        where = "no House Part recorded" if house is None else "no active choices"
        row["checks"].append(make_check(
            "no-part-choices",
            f"{','.join(line.designators)} ({_spec_str(line.spec)}): {where}").to_dict())
        escalations.append(_escalation(index, line, "no-part-choices", [], provider))
        return

    if not getattr(strategy, "requires_live_stock", True):
        # No live stock source for this provider: take the first choice with a
        # usable identity, honestly marked unverified (never invented inventory).
        for choice in choices:
            ref = choice["providerRefs"].get(provider)
            if ref or choice["mpn"]:
                row["source"] = "db"
                row["rankUsed"] = choice["rank"]
                row["ref"] = ref
                row["mpn"] = row["mpn"] or choice["mpn"]
                row["manufacturer"] = row["manufacturer"] or choice["manufacturer"]
                row["offerType"] = strategy.offer_type
                row["checks"].append(make_check(
                    "unverified",
                    f"{','.join(line.designators)}: "
                    f"{ref or choice['mpn']} — no live {provider} stock source; "
                    "availability must be confirmed with the provider").to_dict())
                return
        row["checks"].append(make_check(
            "avl-exhausted",
            f"{','.join(line.designators)} ({_spec_str(line.spec)}): no approved "
            f"choice carries an identity usable for {provider}").to_dict())
        escalations.append(_escalation(index, line, "avl-exhausted", [], provider))
        return

    for choice in choices:
        ref = choice["providerRefs"].get(provider)
        if ref and _stock(facts, ref) >= required:
            row["source"] = "db"
            row["rankUsed"] = choice["rank"]
            if choice["mpn"] and not row["mpn"]:
                row["mpn"] = choice["mpn"]
            if choice["manufacturer"] and not row["manufacturer"]:
                row["manufacturer"] = choice["manufacturer"]
            _fill_selected(row, facts, ref, required, strategy)
            if choice["rank"] > 1:
                row["substitution"] = True
                skipped = [f"rank-{c['rank']} "
                           f"{c['providerRefs'].get(provider) or c['mpn'] or '?'} "
                           f"stock {_stock(facts, c['providerRefs'].get(provider))}"
                           for c in choices if c["rank"] < choice["rank"]]
                msg = (f"{','.join(line.designators)}: {'; '.join(skipped)} < "
                       f"required {required} → used rank-{choice['rank']} {ref}")
                row["checks"].append(make_check("substitution", msg).to_dict())
                if not row["note"]:
                    row["note"] = msg
            return

    row["checks"].append(make_check(
        "avl-exhausted",
        f"{','.join(line.designators)} ({_spec_str(line.spec)}): no approved choice "
        f"has stock >= {required}").to_dict())
    escalations.append(_escalation(
        index, line, "avl-exhausted",
        [{"ref": c["providerRefs"].get(provider), "mpn": c["mpn"],
          "rank": c["rank"],
          "liveStock": _stock(facts, c["providerRefs"].get(provider)),
          "requiredQty": required}
         for c in choices], provider))


def _resolve_explicit_line(row, line, facts, required, escalations, index,
                           strategy) -> None:
    provider = strategy.provider
    ref = line.provider_ref(provider)
    row["source"] = "explicit"
    fact = facts.get(ref)
    orderable, checks = strategy.evaluate(line, fact, required)
    if fact is not None and fact.found:
        _fill_selected(row, facts, ref, required, strategy)
    row["checks"].extend(c.to_dict() for c in checks)
    if not orderable:
        # An explicit pick can't be silently substituted — that's a user call.
        reason = checks[0].check if checks else "not-orderable"
        stock = _stock(facts, ref)
        escalations.append(_escalation(
            index, line, reason,
            [{"ref": ref, "mpn": line.mpn, "rank": None, "liveStock": stock,
              "requiredQty": required}] if fact is not None and fact.found else [],
            provider))


def _spec_str(spec: SpecKey | None) -> str:
    if not spec:
        return "?"
    parts = [spec.kind, spec.value, spec.package]
    if spec.qualifier:
        parts.append(spec.qualifier)
    return " ".join(parts)


def _escalation(index: int, line: RequirementLine, reason: str,
                choices: list[dict], provider: str) -> dict:
    ref = line.provider_ref(provider)
    return {
        "lineIndex": index,
        "designators": line.designators,
        "spec": line.spec.to_dict() if line.spec else None,
        "ref": ref,
        "lcsc": ref if provider == "jlcpcb" else None,
        "mpn": line.mpn,
        "reason": reason,
        "choices": choices,  # per-choice live stock — seeds the alternates search
    }


def format_escalation_report(result: dict) -> str:
    """Human-readable summary of a resolve() result for the terminal/app/agent."""
    lines = result["lines"]
    escalations = result["escalations"]
    n = result["productionQuantity"]
    resolved = [x for x in lines if x["ref"]]
    subs = [x for x in lines if x["substitution"]]
    dnp = [x for x in lines if x.get("dnp")]
    head = (f"Resolution — {len(lines)} line(s) × {n} board(s): "
            f"{len(resolved)} resolved")
    if dnp:
        head += f", {len(dnp)} DNP"
    head += ", ALL CLEAN" if not escalations else f", {len(escalations)} ESCALATED"
    out = [head]
    if subs:
        out.append("")
        out.append(f"Substitutions ({len(subs)}) — resolved silently, review:")
        for x in subs:
            out.append(f"  {x['note']}")
    if escalations:
        out.append("")
        out.append(f"Escalations ({len(escalations)}) — need a decision:")
        for e in escalations:
            what = (_spec_str(SpecKey.from_dict(e["spec"])) if e["spec"]
                    else (e["ref"] or e["mpn"] or "no code"))
            out.append(f"  {','.join(e['designators'])}  {what}  → {e['reason']}")
            for c in e["choices"]:
                label = f"rank-{c['rank']} " if c["rank"] is not None else ""
                out.append(f"    {label}{c['ref'] or c.get('mpn') or '?'}: "
                           f"stock {c['liveStock']} < required {c['requiredQty']}")
    return "\n".join(out)
