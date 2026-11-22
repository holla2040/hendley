# `src/hendley/knowledge/` — notes for Claude

Moved from the root `CLAUDE.md` on 2026-11-22. The root's "Invariants — never break these" still apply here.

- `src/hendley/knowledge/partsdb.py` — the house-parts DB (SQLite v5 at
  `~/.hendley/parts.db`, `HENDLEY_DB` to override): House Parts (opaque id +
  spec-tuple index), ranked Part Choices (deliberate rank, `active|removed`),
  `choice_provider_ids` (provider-neutral identity: mpn/manufacturer preferred,
  LCSC code is the `jlcpcb` ref; per-provider advisory stock/price cache —
  NEVER order against it), append-only audit trail. **Choice identity: the
  provider ref decides first; a bare-MPN match is rejected when the row
  carries a conflicting ref** — different manufacturers publish the same MPN
  (e.g. 1N4148WS), and collapsing them once overwrote a recorded pick. Migrations chain
  v1→v2→v3→v4→v5 on open (v4 adds the `interpretations` cache, ADR-0005; v5 adds
  reusable search intent and its append-only audit evidence), one
  transaction each, file backup (`.v<N>.bak`) first.
  `PartsDb` class = the KnowledgeStore contract.
