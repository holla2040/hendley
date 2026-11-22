# `src/hendley/requirements/` — notes for Claude

Moved from the root `CLAUDE.md` on 2026-11-22. The root's "Invariants — never break these" still apply here.

- `src/hendley/requirements/` — `normalizer.py` (Fusion→RequirementsBom:
  designator grouping, DNP flag, LCSC/MPN pass-through, and auto-spec for
  generic R/C/L via `specs.py` — deterministic ONLY for the trivially
  unambiguous; do NOT grow its regexes: ambiguity belongs to the AI tier).
  **It also routes the FAMILY (ADR-0008)**: a `U`/`D`/`Q` part with no LCSC and
  a footprint names an incomplete part number — `ULN2003`, `MB10S` — in its MPN
  attribute or (far more often) its schematic VALUE. That becomes
  `line.family`, a discovery seed. It is deliberately **NOT** `line.mpn`:
  landing there PINNED it, and Hendley shipped a part number nobody can order,
  unsieved, to the resolver. `family_of()` holds the rule; `FAMILY_PREFIXES`
  the designators.
