> **Historical record.** Implemented on branch `house-parts-bom` and ported
> to main per `docs/audit-house-parts-bom.md` (2026-07-10). Two amendments
> supersede parts of this document: **ADR-0001** (computed ranking exists for
> newly discovered candidates; the deliberate AVL rank stands), and the
> **schema v3** provider-neutral choice identity (LCSC code is now a provider
> ref in `choice_provider_ids`, not the choice identity). The referenced
> `Hendley Sidecar - Functional Spec.md` was not carried to main.

# Hendley Production-Sourcing Design

**Status: AGREED — decisions §1 signed off by the user 2026-07-09** (Q1
option C, migration audit-only, Solutions live-computed confirmed explicitly;
the rest endorsed via the approved plan).
*Supersedes `Hendley Sidecar - Functional Spec.md` (which stays in
place as the review record; its Appendix B questions are resolved here). This
is a design document: it defines the model and the work list. No code changes
accompany it.*

## Why

The goal, stated by the user: **take a finished design to a placed JLC order
as fast as possible, with designers doing zero part searches.** The metric
this design optimizes is the number of human interruptions between "design
done" and "CSV uploaded" — target one batched approval, or zero.

Today's model (branch `house-parts-bom`) stores exactly one *current* part
per spec. Every out-of-stock event on a current part is therefore an
interruption: alternates discovery → user pick → re-record. The fix is the
industry's fix — a **ranked approved-vendor list per spec** — so that
out-of-stock becomes a silent fallback down the rank, and a human is consulted
only when the whole list is exhausted.

Nomenclature is adopted from Altium ActiveBOM (verified against their public
documentation 2026-07-09), because it is the established vocabulary for
exactly this layering: **Part Choices**, **Solution**, **Production
Quantity**, **BOM Checks**. One deliberate divergence: ActiveBOM *auto-ranks*
solutions and lets the user override ("User Rank"); Hendley rank is
**deliberate-only** — assigned by user/agent decision, never computed. The
discovery layer (`alternates.py`) keeps its documented refusal to rank or
pick. Do not "fix" this later by adding auto-ranking; it is the product's
differentiator (agent judgment over rule engine).

## 1. Decisions (Q1–Q6 from the Sidecar spec review)

### Q1 — Identity of a house part: **agent-allocated opaque id** (option C)

A **House Part** is identified by an opaque integer id (SQLite rowid —
already present in today's schema). The spec tuple
`(kind, value, package, qualifier)` is demoted from *identity* to *lookup
index*: a unique index that finds the House Part, but is not what other rows
reference.

- Rationale: identity survives attribute/schema drift (the fatal flaw of
  hash-of-attributes, option B); no human part-number bureaucracy (the cost
  of classic CPN, because the agent allocates ids implicitly on first
  record).
- Forecloses: nothing real. New constraint dimensions later (e.g. a second
  qualifier axis) mean a new/changed lookup index; every reference to the
  House Part id survives.
- Canonicalization of the tuple remains the **agent's job** (per
  `partsdb.py` docstring and the `order-bom` skill §2) — unchanged.
- Migration: each distinct spec tuple in the existing DB becomes one House
  Part row; see §5 task 1.

### Q2 — Attribute split: design-intent in Fusion, procurement in Hendley

Adopted as tabled in the Sidecar spec's Attribute Strategy annotation:
`TOLERANCE`, `DIELECTRIC`, `VOLTAGE_RATING`, `POWER_RATING`, `TEMP_COEFF`,
`TECHNOLOGY` (and similar) may live as Fusion attributes — they define the
part. Vendor preference, approval state, rank, notes, and any sidecar
bookkeeping live **only** in Hendley's DB and never enter the schematic.

### Q3 — Fusion write-back: **not on the sourcing path**

Sourcing v1 uses the bridge **read-only** (BOM extraction). The
`.scr`/`Electron.run` write path remains reserved for genuine design changes
(the existing "Job 2" in `CLAUDE.md`). Consequence: constraints expressed
only in conversation (not in Fusion) live in the House Part's qualifier/note;
they do not travel with the design file. Accepted for v1.

### Q4 — Suppliers: **JLC-only, explicitly**

One supplier, two *offer types* (see Solution, §2). The Solution shape is
designed so a future Octopart/Nexar source adds rows, not schema — but no
aggregator work happens now.

### Q5 — Lifecycle data: **out of scope**

JLC's API returns stock/price/parameters, not lifecycle. No EOL/NRND
modeling. `update_verified()` semantics retained verbatim: advisory cache,
never order against it. If lifecycle ever matters, it arrives as a new
verification source under Q4's extension point.

### Q6 — Approval: **presence on the ranked list**

- *Approved* = the part appears as a Part Choice on the House Part's list.
- *Preference* = rank (1 = first tried). Deliberate-only; re-ranking is a
  recorded decision.
- *Removal* = state change (`removed`), never row deletion. The audit trail
  (today's promote/demote history) is retained **alongside** rank: rank
  answers "what may we use, in what order"; history answers "what did we
  decide, and when". Per user decision these are separate relations, not one.

## 2. Object model

Terms below are the only names for these concepts; no synonyms in code, CLI,
docs, or reports.

### House Part
The spec-level identity — the CPN. Opaque id; found via the unique spec-tuple
index; carries a human description. Created implicitly the first time a spec
is recorded. Never deleted.

### Part Choice
An approved concrete orderable part (JLC `Cxxxx`, plus MPN/manufacturer/
description) attached to one House Part, with:
- `rank` — unique per House Part among active choices.
- `state` — `active` | `removed`.
- decision metadata — who/when/why (approved_at, design that prompted it,
  note).
- the **advisory verified cache** (`last_stock`, `last_price`,
  `last_verified_at`) — moves here from the spec row, since it describes the
  concrete part. Same rule as today: advisory only, never order against it.

Today's single "current" part maps to "the rank-1 active Part Choice".

### Solution
A live supplier offer realizing a Part Choice: price breaks, stock, and
**offer type** — for JLC there are two: `jlc-mounted` (assembled from JLC's
own stock; what the component API reports) and `lcsc-consigned` (bought at
LCSC, consigned to the assembly; different price/lead/risk). Solutions are
**computed at resolution time from the live verify and are not stored in the
DB** — the DB holds policy, not offers. The Solution actually used is
persisted in the Release Snapshot. v1 computes `jlc-mounted` only;
`lcsc-consigned` is a named enum value awaiting a data source.

### Production Quantity
`N`, the board count for the run — a required input to resolution (CLI flag
on the resolve/emit step; the agent asks the user once per order). Per-line
required quantity = per-board quantity × N. Per-board quantity is derived
from the design: number of designators on the line × per-designator quantity
(`DesignPart.quantity`, already in the parts contract, default 1). "In
stock" is undefined without N; nothing resolves without it.

### Resolution
The act, per BOM line: walk the House Part's active Part Choices in rank
order; select the first whose **live-verified** stock ≥ required quantity.
- All candidate codes across all lines are collected into **one batched**
  `getComponentDetailByCode` call before walking — rank-walking is local, so
  the AVL adds zero API round-trips over today's flow.
- A selection at rank > 1 is a **substitution**: resolved silently, reported
  post-hoc in the resolution report and snapshot (per user decision:
  fall back silently, report after).
- An exhausted list (no active choice satisfies N) **escalates**: alternates
  discovery → the batched approval queue (§3) → the pick is recorded as a
  new Part Choice with a rank the user confirms.

### BOM Checks
Named validations with severities, superseding the informal
out/low/not_found/no_code/ok classes of `check_stock()`:

| Check | Fires when | Severity |
|---|---|---|
| `unresolved` | line has no LCSC code after resolution | error |
| `no-part-choices` | spec's House Part has no active choices (or no House Part) | error |
| `avl-exhausted` | choices exist; none satisfies required qty | error |
| `not-in-catalog` | a code the catalog no longer returns | error |
| `insufficient-stock` | selected part's stock < required qty (explicit-code lines) | error |
| `substitution` | resolved at rank > 1 | warning |
| `no-code-uncheckable` | explicit part with no JLC code | warning |

Errors block upload (the existing exit-1 contract of `hendley bom` extends to
cover them); warnings appear in the report. Severities are fixed in v1 (no
per-part overrides — noted as a possible future for precision parts).

### Release Snapshot
An immutable JSON file written beside the CSV at emit time: design name,
timestamp, N, and per line — spec key + House Part id, chosen code, rank
used, substitution flag, live stock and unit price at emit, offer type,
source (`db | pick | explicit`), and the check results. Never updated. The
DB holds *policy*; the snapshot holds *fact* — it is the only thing that can
answer "what exactly did we build in rev C?" after stock and ranks have
moved on. Location: written with the other artifacts under
`~/tmp/hendley_output/` (and worth copying alongside the order records).

## 3. Workflow narrative

### Happy path — 0 interruptions
1. Design is done. Agent reads the BOM (bridge read or parts JSON).
2. Agent interprets each line into canonical spec keys (unchanged, skill §2);
   asks the user one question it cannot know: **N** (and this rides along
   with the "get it ready to order" request itself, so it usually isn't a
   separate interruption).
3. Resolver: look up each House Part's AVL → one batched live verify of
   every candidate code → rank-walk each line → all lines resolve (some at
   rank > 1: silent substitutions).
4. Emit: CSV + resolution report (substitutions and warnings listed) +
   Release Snapshot. User uploads.

### Exception A — specs with no AVL: 1 interruption
New specs (first use of "4.7u 0805") resolve to `no-part-choices`. The agent
runs alternates discovery for **all** gap specs, prepares a verified
trade-off per spec with a recommendation (existing skill §3 judgment,
bias: high stock beats cheapest, same package first, surface electrical
caveats), and presents **one batched approval queue**. The user approves in
one sitting; each pick is recorded as a rank-1 Part Choice; resolution
resumes to the happy path.

### Exception B — AVL exhausted: merged into the same interruption
Lines whose entire list fails for N join the same queue as Exception A —
alternates seeded from the best-known choice, approved picks recorded (user
confirms rank: usually new rank-1, existing choices kept below). One queue,
one sitting, regardless of the mix of A and B.

The search never disappears; it moves off the critical path and is batched.
After a design's first order, its specs are populated and subsequent orders
trend to zero interruptions.

## 4. Explicitly out of scope

- **Feeder-fee / consolidation optimizer** — advisory analysis of JLC's
  per-unique-part-type loading charge (type diversity × tier × N economics,
  which distributor-cost tools structurally can't model). Valuable, later;
  it never blocks an order. The Release Snapshot's per-line data is designed
  to feed it.
- **Voice intake** — a UI over the engine; the agent conversation already
  provides natural-language intake. Last.
- **Multi-supplier aggregation and lifecycle data** (Q4/Q5) — extension
  points named, no work.
- **Fusion attribute write-back** (Q3) — read-only bridge on this path.
- **Order-placement API** — the `.keys` tokenization block stays unused.

## 5. Implementation work list (output of this design — NOT started)

Ordered; each depends on the ones before it unless noted.

1. **partsdb schema v2 + migration** (M) — `house_parts` becomes the House
   Part identity table (id + spec tuple as unique lookup index +
   description); new `part_choices` table (house_part_id, code, mpn,
   manufacturer, rank, state, decision metadata, advisory cache); audit
   history preserved. Migration: distinct spec tuple → House Part; each
   `current=1` row → rank-1 active Part Choice; `current=0` rows → audit
   history **only** (demoted parts were demoted for a reason — they are not
   silently re-approved onto the AVL; the user can re-approve deliberately).
   `SCHEMA_VERSION` 1→2 with idempotent upgrade in `open_db()`.
2. **`db` CLI surface** (S–M) — `db lookup` returns the full AVL
   (choices in rank order + history); `db record` appends/promotes with rank
   semantics; add explicit re-rank and remove operations. JSON-by-default
   output convention unchanged.
3. **Resolver** (M) — new module (e.g. `resolve.py`): input = interpreted
   design lines + N; performs the batched verify and rank-walk; output = the
   resolution JSON. This makes the currently agent-assembled resolution
   partially mechanical; the agent still owns spec interpretation and all
   approval-queue judgment.
4. **Quantity plumbing** (S) — `BomLine` gains per-board quantity; required
   qty = per-board × N flows into resolution and the report. CSV output
   unchanged (JLC's upload derives qty from designators).
5. **BOM Checks** (S–M) — named checks + severities per §2, replacing the
   informal stock statuses in the resolution path; `hendley bom` exit-1
   covers all error-severity checks. (`hendley stock`'s standalone report
   can adopt the same names for consistency.)
6. **Release Snapshot writer** (S) — emitted by the bom step alongside the
   CSV; schema per §2.
7. **`order-bom` skill rewrite** (M) — the new flow: N intake, AVL
   resolution, silent substitution, single batched approval queue,
   snapshot. Rules section updated (never trust cache, user approves picks,
   artifacts to `~/tmp/hendley_output/` — all unchanged).
8. **Docs + tests** (M, spans all) — README, `CLAUDE.md` (workflow section,
   CLI output table), module docstrings; tests pinning: migration
   idempotence + data preservation, rank-walk selection incl. substitution
   and exhaustion, N-sufficiency, check severities and exit codes, snapshot
   immutability/shape.

Not touched: `alternates.py` (discovery still refuses to rank),
`auth.py`/`client.py`/`config.py`, the `.scr` path, `fusion.py`'s read
contract (its `check_stock` gains nothing until task 5 touches its labels).

## Verification of this design (from the approved plan)

- Six decisions above carry explicit user sign-off. ✓ (2026-07-09.)
- §3 demonstrates ≤1 interruption on the happy path with a
  partially-populated AVL. ✓ (0 on happy path; 1 batched for A/B.)
- One name per concept. ✓ (§2 is normative.)
- Every `[REVIEW]` block in the Sidecar spec is addressed here (Q1–Q6) or
  explicitly deferred (§4). ✓
- Zero source changes accompany this document. ✓
