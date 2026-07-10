"""The resolver — rank-walk each BOM line's approved choices against live stock.

This is the mechanical half of BOM resolution (the judgment half — spec
interpretation, alternates trade-offs, approval — belongs to the agent; see
``.claude/skills/order-bom/SKILL.md``). Given interpreted design lines and a
**Production Quantity** (board count ``N``), the resolver:

1. Looks up each spec line's House Part and its ranked active Part Choices
   (``hendley.partsdb``).
2. Live-verifies **every** candidate code across all lines in **one batched**
   ``getComponentDetailByCode`` call (the AVL adds zero extra round-trips),
   refreshing the advisory cache as a side effect.
3. Walks each line's choices in rank order and selects the first with live
   stock >= the line's required quantity (designators × per-designator qty ×
   N). Selecting at rank > 1 is a **substitution** — resolved silently,
   reported post-hoc. A line whose whole list fails **escalates** to the
   agent (alternates → user approval → ``record()`` → re-resolve).

Input contract (JSON), agent-composed::

    {
      "design": "comet",                # optional, for the report/snapshot
      "productionQuantity": 25,         # required, boards to build (N)
      "lines": [
        {
          "designators": ["R1", "R4"],  # required, non-empty
          "comment": "22k",             # value/description (CSV Comment col)
          "footprint": "0603",
          "spec": {"kind": "resistor", "value": "22k",
                   "package": "0603", "qualifier": ""},   # resolve via AVL...
          "quantityPer": 1              # per-designator qty, default 1
        },
        {
          "designators": ["U1"],
          "comment": "STM32F103C8T6",
          "footprint": "LQFP-48",
          "lcsc": "C8734"               # ...or explicit code: verify only
        }
      ]
    }

The output dict is a superset of the ``hendley.bom`` resolution contract —
``hendley bom`` renders it directly — adding per line: ``spec``,
``housePartId``, ``requiredQty``, ``rankUsed``, ``substitution``,
``liveStock``, ``unitPrice``, ``offerType``, and ``checks``; plus a top-level
``escalations`` list of the lines needing the agent (each carrying the
per-choice live stock so the alternates search can seed without re-querying).

**BOM Checks** (per ``docs/hendley-sourcing-design.md`` §2) are named
validations with fixed severities; ``error`` blocks upload, ``warning`` is
reported. ``CHECKS`` below is the authoritative name → severity table.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .alternates import _unit_price_at_qty1
from .partsdb import lookup, update_verified

# BOM Check name → severity. Errors block upload; warnings are reported.
CHECKS = {
    "unresolved": "error",           # line has no LCSC code after resolution
    "no-part-choices": "error",      # spec has no House Part / no active choices
    "avl-exhausted": "error",        # choices exist; none satisfies required qty
    "not-in-catalog": "error",       # a code the catalog no longer returns
    "insufficient-stock": "error",   # explicit code's stock < required qty
    "substitution": "warning",       # resolved at rank > 1
    "no-code-uncheckable": "warning",  # no spec and no code — nothing to verify
}
ERROR_CHECKS = tuple(k for k, v in CHECKS.items() if v == "error")

# The one supplier offer type v1 computes (see design §2 "Solution").
OFFER_TYPE_JLC_MOUNTED = "jlc-mounted"


@dataclass
class ResolveLine:
    """One interpreted design line: a spec to resolve, or an explicit code."""

    designators: list[str]
    spec: dict | None = None  # {kind, value, package, qualifier} — AVL path
    lcsc: str | None = None  # explicit code — verify-only path
    comment: str | None = None
    footprint: str | None = None
    quantity_per: int = 1  # per-designator quantity
    note: str | None = None
    attributes: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "ResolveLine":
        designators = d.get("designators")
        if not isinstance(designators, list) or not designators:
            raise ValueError(f"line is missing required non-empty 'designators': {d!r}")
        spec = d.get("spec")
        if spec is not None:
            missing = [k for k in ("kind", "value", "package") if not spec.get(k)]
            if missing:
                raise ValueError(f"line spec is missing {missing}: {d!r}")
        return cls(
            designators=[str(x) for x in designators],
            spec=spec,
            lcsc=d.get("lcsc"),
            comment=d.get("comment"),
            footprint=d.get("footprint"),
            quantity_per=int(d.get("quantityPer", 1) or 1),
            note=d.get("note"),
        )

    def required_qty(self, production_quantity: int) -> int:
        return len(self.designators) * self.quantity_per * production_quantity


def load_request_json(path: str | Path) -> tuple[str | None, int, list[ResolveLine]]:
    """Load a resolve-request JSON file → (design, production quantity, lines)."""
    doc = json.loads(Path(path).read_text())
    if not isinstance(doc, dict):
        raise ValueError("resolve request must be a JSON object")
    n = doc.get("productionQuantity")
    if not isinstance(n, int) or n < 1:
        raise ValueError(f"'productionQuantity' must be a positive integer, got {n!r}")
    lines = doc.get("lines")
    if not isinstance(lines, list) or not lines:
        raise ValueError("resolve request needs a non-empty 'lines' list")
    design = doc.get("design")
    return (str(design) if design else None), n, [ResolveLine.from_dict(x) for x in lines]


def _check(name: str, message: str) -> dict:
    return {"check": name, "severity": CHECKS[name], "message": message}


def resolve(
    conn,
    lines: list[ResolveLine],
    production_quantity: int,
    client=None,
    design: str | None = None,
) -> dict:
    """Resolve lines against the house AVLs and live stock; see module docstring."""
    from .client import JLCClient

    if production_quantity < 1:
        raise ValueError("production_quantity must be >= 1")

    # Pass 1 — gather every candidate code (AVL choices + explicit codes).
    houses: list[dict | None] = []
    codes: set[str] = set()
    for line in lines:
        house = None
        if line.spec is not None:
            house = lookup(conn, line.spec["kind"], line.spec["value"],
                           line.spec["package"], line.spec.get("qualifier", ""))
            if house:
                codes.update(c["lcscCode"] for c in house["choices"])
        if line.lcsc:
            codes.add(line.lcsc)
        houses.append(house)

    # One batched live verify for everything; refresh the advisory cache.
    details: dict[str, dict] = {}
    if codes:
        client = client or JLCClient()
        fetched = client.get_component_detail_by_code(sorted(codes)) or []
        details = {d.get("componentCode"): d for d in fetched}
        for code, d in details.items():
            update_verified(conn, code, d.get("stockCount"), _unit_price_at_qty1(d))

    # Pass 2 — rank-walk each line.
    out_lines: list[dict] = []
    escalations: list[dict] = []
    for i, line in enumerate(lines):
        required = line.required_qty(production_quantity)
        row = {
            "designators": line.designators,
            "comment": line.comment,
            "footprint": line.footprint,
            "lcsc": None,
            "source": None,
            "note": line.note,
            "spec": line.spec,
            "housePartId": houses[i]["id"] if houses[i] else None,
            "requiredQty": required,
            "rankUsed": None,
            "substitution": False,
            "liveStock": None,
            "unitPrice": None,
            "offerType": None,
            "checks": [],
        }

        if line.spec is not None:
            _resolve_spec_line(row, line, houses[i], details, required, escalations, i)
        elif line.lcsc:
            _resolve_explicit_line(row, line, details, required, escalations, i)
        else:
            row["checks"].append(_check(
                "no-code-uncheckable",
                f"{','.join(line.designators)}: no spec and no LCSC code — "
                "nothing to resolve or verify"))
            row["checks"].append(_check(
                "unresolved", f"{','.join(line.designators)}: no part"))
            escalations.append(_escalation(i, line, "no-code", []))
        out_lines.append(row)

    return {
        "design": design,
        "productionQuantity": production_quantity,
        "lines": out_lines,
        "escalations": escalations,
    }


def _stock(details: dict, code: str) -> int:
    d = details.get(code)
    return int(d.get("stockCount") or 0) if d else 0


def _fill_selected(row: dict, details: dict, code: str, required: int) -> None:
    d = details.get(code) or {}
    row["lcsc"] = code
    row["liveStock"] = d.get("stockCount")
    row["unitPrice"] = _unit_price_at_required(d, required)
    row["offerType"] = OFFER_TYPE_JLC_MOUNTED


def _unit_price_at_required(detail: dict, required: int) -> float | None:
    """Unit price at the break that applies to the required quantity."""
    ranges = (detail or {}).get("priceRanges") or []
    applicable = [p for p in ranges
                  if int(p.get("startQuantity") or 0) <= required and p.get("unitPrice")]
    if applicable:
        best = max(applicable, key=lambda p: int(p.get("startQuantity") or 0))
        return best.get("unitPrice")
    return _unit_price_at_qty1(detail)


def _resolve_spec_line(row, line, house, details, required, escalations, index) -> None:
    choices = house["choices"] if house else []
    if not choices:
        where = "no House Part recorded" if house is None else "no active choices"
        row["checks"].append(_check(
            "no-part-choices",
            f"{','.join(line.designators)} ({_spec_str(line.spec)}): {where}"))
        row["checks"].append(_check(
            "unresolved", f"{','.join(line.designators)}: no part"))
        escalations.append(_escalation(index, line, "no-part-choices", []))
        return

    for choice in choices:
        code = choice["lcscCode"]
        if _stock(details, code) >= required:
            row["source"] = "db"
            row["rankUsed"] = choice["rank"]
            _fill_selected(row, details, code, required)
            if choice["rank"] > 1:
                row["substitution"] = True
                skipped = [f"rank-{c['rank']} {c['lcscCode']} "
                           f"stock {_stock(details, c['lcscCode'])}"
                           for c in choices if c["rank"] < choice["rank"]]
                msg = (f"{','.join(line.designators)}: {'; '.join(skipped)} < "
                       f"required {required} → used rank-{choice['rank']} {code}")
                row["checks"].append(_check("substitution", msg))
                if not row["note"]:
                    row["note"] = msg
            return

    row["checks"].append(_check(
        "avl-exhausted",
        f"{','.join(line.designators)} ({_spec_str(line.spec)}): no approved choice "
        f"has stock >= {required}"))
    row["checks"].append(_check(
        "unresolved", f"{','.join(line.designators)}: no part"))
    escalations.append(_escalation(
        index, line, "avl-exhausted",
        [{"lcscCode": c["lcscCode"], "rank": c["rank"],
          "liveStock": _stock(details, c["lcscCode"]), "requiredQty": required}
         for c in choices]))


def _resolve_explicit_line(row, line, details, required, escalations, index) -> None:
    code = line.lcsc
    row["source"] = "explicit"
    if code not in details:
        row["checks"].append(_check(
            "not-in-catalog",
            f"{','.join(line.designators)}: {code} not returned by the JLC catalog"))
        row["checks"].append(_check(
            "unresolved", f"{','.join(line.designators)}: no part"))
        escalations.append(_escalation(index, line, "not-in-catalog", []))
        return
    _fill_selected(row, details, code, required)
    stock = _stock(details, code)
    if stock < required:
        # An explicit pick can't be silently substituted — that's a user call.
        row["checks"].append(_check(
            "insufficient-stock",
            f"{','.join(line.designators)}: {code} stock {stock} < required {required}"))
        escalations.append(_escalation(
            index, line, "insufficient-stock",
            [{"lcscCode": code, "rank": None, "liveStock": stock,
              "requiredQty": required}]))


def _spec_str(spec: dict | None) -> str:
    if not spec:
        return "?"
    parts = [spec.get("kind", "?"), spec.get("value", "?"), spec.get("package", "?")]
    if spec.get("qualifier"):
        parts.append(spec["qualifier"])
    return " ".join(parts)


def _escalation(index: int, line: ResolveLine, reason: str, choices: list[dict]) -> dict:
    return {
        "lineIndex": index,
        "designators": line.designators,
        "spec": line.spec,
        "lcsc": line.lcsc,
        "reason": reason,
        "choices": choices,  # per-choice live stock — seeds the alternates search
    }


def format_escalation_report(result: dict) -> str:
    """Human-readable summary of a resolve() result for the terminal/agent."""
    lines = result["lines"]
    escalations = result["escalations"]
    n = result["productionQuantity"]
    resolved = [x for x in lines if x["lcsc"]]
    subs = [x for x in lines if x["substitution"]]
    head = (f"Resolution — {len(lines)} line(s) × {n} board(s): "
            f"{len(resolved)} resolved")
    head += ", ALL CLEAN" if not escalations else f", {len(escalations)} ESCALATED"
    out = [head]
    if subs:
        out.append("")
        out.append(f"Substitutions ({len(subs)}) — resolved silently, review:")
        for x in subs:
            out.append(f"  {x['note']}")
    if escalations:
        out.append("")
        out.append(f"Escalations ({len(escalations)}) — need the agent/user:")
        for e in escalations:
            what = _spec_str(e["spec"]) if e["spec"] else (e["lcsc"] or "no code")
            out.append(f"  {','.join(e['designators'])}  {what}  → {e['reason']}")
            for c in e["choices"]:
                out.append(f"    rank-{c['rank']} {c['lcscCode']}: "
                           f"stock {c['liveStock']} < required {c['requiredQty']}")
    return "\n".join(out)
