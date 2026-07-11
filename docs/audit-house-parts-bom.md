# Audit: `house-parts-bom` branch vs PRD v1.1

**Date:** 2026-07-10
**Auditor:** Claude (commissioned run, see plan)
**Subject:** branch `house-parts-bom` (tip `a80bf7e`, 12 commits, 86 tests,
unmerged), per the audit plan recorded in its own `HANDOFF.md` banner.
**References:** `docs/PRD.md` v1.1, `docs/architecture.md` §15 invariants,
`docs/adr/0001..0003`, the branch's `docs/hendley-sourcing-design.md`
(AGREED 2026-07-09).

**Outcome:** the branch is a sound kernel with a provider coupling that was a
signed-off v1 shortcut, not a design error. Nothing merges as-is; the four
modules port into the new layout with the seam fixes below. No unit is
discarded outright.

## Audit discipline

Per the HANDOFF's own instruction: *deliberately deferred v1 scope* (recorded
in the sourcing design §1/§4) is not misalignment. Only positions the PRD
contradicts are flagged as such.

## Verdict table

| Unit | Verdict | Grounds |
|---|---|---|
| `partsdb.py` — House Part (opaque id + spec-tuple index), ranked Part Choices, `active/removed` state, audit trail, atomic v1→v2 migration | **PORT** → `knowledge/partsdb.py`, with schema v3 | Model matches PRD §12.10–12.11 (knowledge capture/reuse) and ADR-0002. One structural defect (next row). |
| `part_choices.lcsc_code NOT NULL` as choice identity (`partsdb.py:69`, unique index `ux_choice_code:85`) | **REWRITE at port** — schema v3 | Violates provider independence (PRD §4.7, invariant 2): a knowledge-base record must outlive the provider. v3 keys choices by `(mpn, manufacturer)` with provider refs + advisory cache in a `choice_provider_ids` mapping. |
| `resolve.py` — batched verify (one `getComponentDetailByCode` for all candidates), rank-walk first-satisfying-choice, escalations carrying per-choice live stock, `spec`-or-`lcsc` line contract | **PORT** → `resolver/orchestration/resolve.py` | Implements PRD §12.4 (candidate discovery facts), §12.15 (re-resolution), and ADR-0001's deliberate-AVL side exactly. |
| `from .client import JLCClient` … `client = client or JLCClient()` (`resolve.py:157,179`) | **REWRITE at port** — injected `DataSource` | Resolver core must not construct a provider client (invariant 2, PRD §15.1 module boundaries). The injection point already exists (`client=` param); the default and the JLC-shaped contract move behind `datasources/base.DataSource`. |
| `OFFER_TYPE_JLC_MOUNTED` baked into every resolved row (`resolve.py:80,239`) | **REWRITE at port** — supplied by `ProviderStrategy` | Strategy owns offer semantics (invariant 4). The sourcing design itself marked the Solution layer as the extension seam; this honors it. |
| `spec` XOR `lcsc` line contract; `quantityPer >= 1` enforced; **no DNP model** | **REWRITE at port** — Requirements BOM line | PRD §9 defines three selection modes (requirements / manufacturer-constrained / exact-part); the branch has two. DNP: PRD §12.1 requires preserving designators and §12.14 forbids silent omission — main's working `is_dnp` semantics (carry, mark, exclude from resolution and order files) is the model. |
| `bom.py` — JLC CSV (`Comment, Designator, Footprint, LCSC Part #`), `blocking_checks()` gate, `READY TO UPLOAD` report, `db|pick|explicit` provenance | **PORT** → `providers/jlcpcb/bom_csv.py` | This is exactly "adapters format, never select" (invariant 5) and the PRD §12.13 output set. Becomes the BOM half of the JLCPCB ProviderAdapter. |
| `snapshot.py` — immutable release record beside the CSV, resolution embedded verbatim, never overwrites | **PORT** → `reporting/snapshot.py`, unchanged | Satisfies PRD §15.7 auditability. Contains nothing JLC-specific. |
| BOM Checks table (named checks with validated severities) | **PORT** → `domain/model.py` | PRD §12.2's blocking/warning/informational triad. The mis-cased-severity bug was already fixed on-branch (`cf3a73a`); intake validation comes along. |
| "Rank is deliberate-only, **never** computed" (sourcing design §"divergence from ActiveBOM") | **AMENDED** by ADR-0001 | Kept for the approved AVL (never reordered); relaxed for newly discovered candidates, which the PRD §12.6 ranking engine orders. The branch's stance survives where it mattered. |
| Lifecycle evaluation absent (design Q5) | **NOT misalignment** — signed-off deferral | JLC API returns no lifecycle data. Stays deferred (plan: v1 deferral list). |
| Fusion write path excluded from sourcing (design Q3) | **ALIGNED** | Matches invariant 10 and README "Design writes are explicit". |
| CLI surface: `resolve`, `bom`, `db lookup/record/rerank/remove/list/refresh` | **PORT** → `cli/knowledge.py` + `cli/manufacturing.py` | `db record` gains `--mpn/--manufacturer` as identity; `--lcsc` becomes a provider ref. |
| 86 tests (`test_partsdb/resolve/bom/snapshot.py`) | **PORT with adaptation** | Identity-related assertions updated for v3; migration tests extended to the v2→v3 and v1→v2→v3 chains. |
| `order-bom` skill | **REWRITE** (Phase 8) | Reframed as the secondary surface per ADR-0003, driving the same library flow as the app. |
| `docs/hendley-sourcing-design.md`, `docs/overnight-decisions.md`, `HANDOFF.md` | **CARRY as historical record** | Brought to `docs/` with a header noting where ADR-0001/0003 amend them. `HANDOFF.md` is superseded by this audit and not carried. |
| No CPL, no `bridge.py`, no rotation data | **NOT misalignment** — parallel development | The branch forked before main's `pcba` work. The JLCPCB adapter (Phase 6) unifies the branch's BOM gate with main's CPL emission. |

## What does NOT port

- `HANDOFF.md` (superseded by this audit).
- The `Hendley Sidecar - Functional Spec.md` annotated review (superseded by
  the PRD; the sourcing design records the decisions that came out of it).
- The `spec`-or-`lcsc` request JSON as a public contract — it becomes a thin
  adapter over the canonical Requirements BOM (`load_request_json` kept for
  compatibility during the port, retired when the app lands).

## Notes for the port (Phase 4)

1. Schema v3 must migrate the real v2 DB at `~/.hendley/parts.db`: file-copy
   backup first, one `BEGIN IMMEDIATE` transaction, `schema_version` bump
   last — the same discipline the branch's v1→v2 migration proved.
2. Existing LCSC-only choices (no MPN recorded) are legal in v3: identity
   falls back to the provider ref; the verify path backfills
   `mpn`/`manufacturer` opportunistically from catalog detail responses.
3. The escalation payload's per-choice live stock (seeding the alternates
   search without a re-query) is a deliberate efficiency — preserve it.
