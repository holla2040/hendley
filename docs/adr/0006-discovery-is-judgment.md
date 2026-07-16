# ADR-0006 — Discovery is judgment: agent-normalized names, human-fired searches, single-radio picks

**Status:** Accepted (settled in discussion with Craig, 2026-07-13; supersedes
ADR-0005 §5). §5 amended 2026-07-13: backup checkboxes + staged Update commit.
**Date:** 2026-07-13

## Context

The VZ10 incident. D1 — a 10 V zener on the `D-SOD323` library footprint —
asked for alternates and was proposed rectifiers:

- The spec had no dense value param (only R/C have one) and no chip package,
  so the queue queried the **entire** jlcsearch `diodes` category unfiltered
  and got the top of the index (1N4148, M7, SS34…).
- The verbatim library footprint name could never equal a catalog package
  name (`D-SOD323` ≠ `SOD-323`), and standard package strings carry no
  parseable dimensions, so the constraint engine put **every** candidate —
  right or wrong — in *fit unconfirmed*. Nothing was confirmed, nothing was
  rejected, and the table looked authoritative.

A first fix attempt added Python heuristics (a composed FTS string, a
substring "value guard") and was rejected on review: a plausible-but-wrong
candidate list is how a non-functional board gets built. With an unbounded
space of footprint spellings and value formats, *"Python wouldn't be able to
parse it — that's why we introduced Claude for this."*

## Decision

1. **Judgment belongs to Claude and the engineer; Python compares.** No
   Python code composes a search, filters by "does the value appear in the
   parameters", or guesses what a name means. Deterministic code performs
   exact comparisons on values judgment already normalized.
2. **The agent normalizes names** (extends ADR-0005): the interpretation
   prompt maps library footprint names to catalog packages
   (`D-SOD323` → `SOD-323`; chip sizes as before; verbatim **only** when
   nothing standard is recognizable, e.g. `C-E-5`). A dedicated
   `interpret_footprint()` judgment serves schematic-pinned parts (which
   skip part interpretation); both cache forever with the usual
   `deterministic < llm < user` provenance.
3. **Discovery auto-runs only where the query is deterministic** — a dense
   value param (R/C) or a chip package with a category. Every other spec
   discovers **nothing** until the engineer fires a search: the terms are
   seeded from the spec, visible, editable, sent verbatim to the full-text
   index, and persisted in the order draft. A candidate list the engineer
   didn't ask for is never invented (`discovery.needsSearch`).
4. **Filter stages are visible and reversible.** Results split into
   package-confirmed (exact compare against the agent-judged package),
   *other packages* (expandable — aliases exist, still pickable), and
   *can't cover the order* (expandable, never pickable). An empty result
   names what each stage dropped.
5. **Picks are single-radio, not list surgery** (supersedes ADR-0005 §5's
   propose-3 / approve-the-list): the selected radio is what mounts.
   The **first** pick for a spec with nothing approved records permanently
   as AVL rank 1 (choosing *is* the approval). A pick that **overrides** an
   existing approved part — or a schematic-pinned part — is order-only: an
   in-memory pin, re-resolved and draft-persisted, never written to the
   parts DB. Both are undoable in place (unchecking the mounted part's
   backup checkbox = audited removal via Update; "undo — use the automatic
   pick / the schematic part" = clear the pin).

   *Amended 2026-07-13 — ranked backups and the staged commit.* A
   **backup checkbox column** rides the same tables: checking a row marks
   it for the spec's approved list (appended after the existing ranks, in
   table order — this is the deliberate act that grows the AVL, so
   substitution and instant alternates work on the next design); rows
   already on the list render pre-checked, and unchecking marks an audited
   removal. **Nothing writes on click**: radio and checkbox changes stage
   in memory, and one **Update** button commits the whole diff — the
   acknowledgement is explicit, an accidental click writes nothing, and
   navigating away discards the stage. Unpicked *and unchecked* search
   rows are still never recorded.

## Consequences

- The zener now yields only zeners: FTS `"zener 10V"` → 93 verified → 16
  package-confirmed SOD-323 candidates, the rest one honest click away.
- Non-R/C parts cost one extra click (fire the seeded search). Given the
  failure mode is a dead board, that click is cheap.
- Search plans now prove every unambiguous stated value/rating against the live
  catalog parameter. A 13 V Zener discovered by the coarse `10V` name search is
  shown as a rejected row, not a matching candidate. Ratings whose parameter
  meaning is genuinely ambiguous remain explicit engineer judgment.
- The AVL grows only by deliberate acts: first picks and CLI `db record`.
  Silent substitution continues to walk ranks the engineer approved.
