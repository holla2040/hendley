# ADR-0001 — Ranking synthesis: computed for discovery, deliberate for the AVL

**Status:** Accepted
**Date:** 2026-07-10

## Context

Two committed positions conflicted:

- The AGREED sourcing design (`docs/hendley-sourcing-design.md`, signed off
  2026-07-09) made the rank of an approved Part Choice **deliberate-only —
  never computed** — and called that the product's differentiator.
- The vision and PRD v1.1 (§12.6) require a configurable ranking engine whose
  factors include history, availability, lifecycle, and cost.

The `house-parts-bom` HANDOFF flagged this as the central tension the PRD had
to adjudicate: "the PRD must adjudicate; this branch enforces one side."

## Decision

Both stances hold — at different layers:

1. **Candidate discovery is computed.** When a requirement has no satisfying
   approved Part Choice (or the engineer asks for alternatives), newly
   discovered candidates are ranked by the deterministic Ranking Engine.
   Prior approvals and usage history are ranking factors. Every score is
   decomposable into visible contributions with a human-readable explanation.
2. **The AVL is deliberate.** Once the engineer approves a Part Choice, its
   rank within the House Part's AVL is an explicit engineering decision. The
   system never reorders it — not by stock, not by price, not by history.
   Resolution walks the deliberate rank order and selects the first choice
   that live data can satisfy.

Approved AVL choices never pass through the Ranking Engine. Computed ranking
never writes to the knowledge base.

## Consequences

- PRD §12.6 is read as applying to candidate discovery, not to the approved
  AVL. The sourcing design's "never computed" rule is preserved where it
  mattered (the AVL) and relaxed where the PRD needed it (discovery).
- Invariant 8 ("historical use influences ranking but never eligibility")
  applies to the discovery ranker.
- The ranking **configuration model** (user-editable weights/format) remains
  an open decision; v1 ships hardcoded weights.
