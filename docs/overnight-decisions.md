> **Historical record** of the 2026-07-09 overnight autonomous run on branch
> `house-parts-bom`. Kept for traceability; the code it describes was ported
> to main (amended) per `docs/audit-house-parts-bom.md`.

# Overnight run — decision log (2026-07-09 → 07-10)

**Read this first.** Every judgment call I made that the design doc left open,
in task order. Items marked ⚠️ are the ones to review hardest (the "would have
been a sign-off question" tier). This file is deliberately uncommitted —
delete it after review.

_Reference: `docs/hendley-sourcing-design.md` (AGREED). Commits land per task
on `house-parts-bom`._

---

## Task 1 — partsdb schema v2 + migration

- **v1 table kept as backup.** Migration renames `house_parts` →
  `house_parts_v1` and leaves it in place (free rollback for your real DB; a
  later cleanup can drop it). `open_db()` only migrates when
  `schema_version=1`.
- **`record()` on a code already on the AVL promotes it** (moves it to the
  requested rank, default 1, updating any newly supplied metadata) rather
  than erroring or duplicating. Rationale: "make this the house part again"
  is the natural meaning of re-recording.
- **`record()` gains a `rank=` parameter** (default 1 = promotion, matching
  v1's spirit). Out-of-range ranks clamp to the end of the list rather than
  erroring — conservative for agent-driven use.
- **`history()` now returns the audit trail** (events: recorded, promoted,
  reranked, removed, superseded), not demoted part rows. Migrated v1 history
  rows appear as `superseded` events carrying their old part data in
  `detail`. Migrated *current* rows get no synthetic audit event — the
  choice row's `approved_at` already records it.
- **Advisory cache (`last_*`) updated on ALL rows carrying the code**
  (active and removed), preserving v1's "every row carrying a code"
  semantics.
- Rank-shift mechanics use the negative-rank two-step to respect the unique
  `(house_part_id, rank) WHERE state='active'` index inside one transaction.
- **Minimal `db refresh` compatibility fix folded into this task's commit**
  (it read the old flat `lcscCode` shape and would have crashed at runtime;
  tests don't cover cli.py). Full CLI surface is task 2 as planned.
- **ruff is not installed on this box** (no pip in system Python; installing
  needs sudo). Skipped for the run; line-length 100 / py310 held manually.
  Run `ruff check .` yourself after review, or I can when tooling exists.

## Task 3 — resolver (`resolve.py`)

- **The BOM Checks vocabulary is defined in `resolve.py`** (the §2 table:
  names + severities) since the resolver is what detects them; task 5 then
  wires severity gating into the emit path. Same end state as the design,
  different file boundary than a literal reading of the task list.
- **Added a `hendley resolve` CLI command** (request JSON in → resolution
  JSON out, escalation report to stderr, exit 1 when any line escalates).
  The design's task 3 named only the module, but the agent needs a way to
  run it; a module without an entry point isn't a completable step.
- **Input contract** (`resolve request.json`): lines carry either `spec`
  (the canonical 4-tuple, resolved via the AVL) or `lcsc` (explicit part,
  verified only); `quantityPer` (per-designator, default 1) × designator
  count × `productionQuantity` = required qty.
- **Resolver refreshes the advisory cache** (`update_verified`) for every
  code it live-verifies — free, and keeps `db list` honest.
- **Substitution auto-composes the line note** ("rank-1 C31850 stock 40 <
  required 50 → used rank-2") so the report explains itself; an
  agent-supplied note is never overwritten.
- **Escalations carry the per-choice live stock** so the follow-up
  alternates search can seed from the best-known part without re-querying.

## Task 5 — BOM Checks in the emit path

- **`hendley stock`'s out/low/not_found/no_code/ok labels are left as-is.**
  The design said its report "can adopt the same names" — I chose not to:
  it's a standalone pre-flight tool with its own contract, and renaming its
  statuses buys consistency at the cost of churning a working report. The
  resolution path (resolve → bom) is fully on named checks. Revisit if the
  two reports ever get confused for each other in practice.
- `hendley bom` exits 1 on any error-severity check even when every line
  carries an LCSC code (e.g. `insufficient-stock` on an explicit part —
  selected, but short). Warnings (substitutions) never block; they print in
  the report's Checks section.

## Task 8 — self-review (10 confirmed findings, all fixed)

A high-effort multi-agent review of the series found **10 confirmed
defects** (several reproduced by execution). All are fixed in the final
commit; the full list was reported via the review tool. The two you should
know about:

- ⚠️ **The v1→v2 migration was not atomic** — `executescript` implicitly
  commits the table rename, so a crash mid-migration would have permanently
  bricked `~/.hendley/parts.db` (every reopen re-fails). Now the whole
  migration runs in one explicit transaction (SQLite DDL is transactional);
  a forced-failure test proves rollback-to-pristine-v1 + clean retry.
  **Your real DB had not yet been migrated when this was fixed.**
- ⚠️ **A miscased check severity (`"Error"`) slipped every gate** — the emit
  exited 0 and wrote a snapshot for a known-short BOM. Severities are now
  validated at intake (`error`/`warning` only, loud failure).

Judgment calls made while fixing (flagging per protocol):
- **`spec` + `lcsc` on one line is now rejected** (ValueError) rather than
  silently preferring one. The contract is documented as either/or; the
  reviewer showed the explicit code was being silently discarded. Rejecting
  keeps the agent honest; if you'd rather it fall back to the explicit code
  when the AVL fails, that's a small change.
- **`quantityPer < 1` is rejected** — DNP isn't modeled (design §2); omit
  unmounted lines from the request. `0` used to silently become `1`.
- **Snapshot same-second collision → `-2`/`-3` suffix** instead of a crash;
  still never overwrites.
- **Report headline reworded**: `READY TO UPLOAD` / `N BLOCKER(S) — DO NOT
  UPLOAD`, keyed on the same gate as the exit code (it used to say "ALL
  RESOLVED" on error-blocked BOMs).
- **Resolver no longer double-stamps** a generic `unresolved` check next to
  the specific one; `hendley bom` now reports every blocker in one pass
  (was: one blocker class per run).
- **The skill's seedless `alternates` instruction was wrong** (inherited from
  the old skill text — the CLI requires a seed code); now documents seeding
  with any similar known code.
- Cleanup applied: dead `ResolveLine.attributes` field removed; the two
  price-break extractors unified into public `alternates.unit_price_at_qty`;
  partsdb's two rank-shift helpers merged; shared require-house/choice
  preambles; `load_resolution_json` returns the raw doc so the snapshot
  embeds exactly what was validated (no second read).
- Deferred as not-worth-it tonight (all sub-millisecond on this data):
  `list_parts` N+1 query, per-code commit in the advisory-cache refresh,
  count query in record/rerank. Noted here so they're deliberate.

## Task 6 — Release Snapshot

- **Timestamped filename** (`<csv-stem>.<UTC-compact>.snapshot.json`) rather
  than one fixed name: every emit is its own immutable fact; re-emitting
  after a fix creates a second snapshot instead of failing on (or worse,
  overwriting) the first. The writer still refuses to overwrite as a
  belt-and-braces check.
- **Snapshots are written only for CLEAN emits** (CSV written via `-o`, no
  unresolved lines, no error checks). A blocked BOM exits 1 and records no
  fact — the snapshot answers "what did we order," not "what did we try."
  `--no-snapshot` opts out entirely.
- **Snapshot content = the raw resolution document verbatim** (so all
  resolver fields — spec, housePartId, rankUsed, liveStock, unitPrice,
  offerType, checks — survive even if BomLine never learns them) + emit
  metadata (emittedAt, csv path, summary counts).
