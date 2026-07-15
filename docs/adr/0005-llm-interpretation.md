# ADR-0005 — LLM interpretation tier: replaceable CLI judgment, cached forever

**Status:** Accepted (settled in discussion with Craig, 2026-07-11).
§5 superseded by ADR-0006 (single-radio picks); §4's package rule extended by
ADR-0006 (the agent normalizes footprint names to catalog packages).
**Date:** 2026-07-11

## Context

Two realities broke deterministic intake on the first real design pull:

- **Ad-hoc values.** Designers write requirements freeform (`47u/50V`,
  `10k 0.1%`). We deliberately decided not to impose a format, so
  interpreting these is judgment. A hardcoded parser was starting to grow
  one regex per spelling — the exact anti-pattern the design forbade.
- **Decades of library footprint names.** `C-E-5` means "electrolytic,
  5 mm" to a human and nothing to a catalog query. And a wrong mapping must
  never rank a part that physically cannot land on the board.

## Decision

1. **Interpreter = a replaceable CLI adapter behind the `Interpreter` protocol**
   (`hendley/ai/`). Codex is the default transport: ephemeral, read-only
   `codex exec`, riding the user's existing Codex login with no API key. Use
   `HENDLEY_CODEX_BIN` and optional `HENDLEY_CODEX_MODEL` overrides. Set
   `HENDLEY_INTERPRETER=claude` to use the original Claude CLI compatibility
   backend (`claude -p … --output-format json`), where `HENDLEY_CLAUDE_BIN`
   overrides the binary. Any failure (missing binary, timeout, non-JSON)
   degrades to the fallback, never breaks the flow.
2. **Every judgment is cached** in the knowledge DB (`interpretations`
   table, schema v4) keyed by the verbatim strings, with provenance
   `deterministic < llm < user` — a weaker source never overwrites a
   stronger one. Each unique string is judged **once, ever**; re-pulls are
   deterministic and free.
3. **Fallback = one-time confirm card** in the app (prefilled with the
   low-confidence guess). The user's answer caches as `user` — never asked
   again, never silently replaced.
4. **Footprint interpretations carry a physical envelope** (mount,
   maxDiaMm, maxLenMm, leadSpacingMm). **Fit is a hard constraint**: the
   constraint engine passes candidates whose parsed dimensions fit, rejects
   ones that don't (with the numbers), and puts unparseable ones in a
   separate *fit unconfirmed* bucket that is **never ranked** — promotable
   only deliberately.
5. **The approval queue proposes an AVL of exactly 3** (rank 1 + two
   alternates) with per-row reasons; the engineer reorders/swaps; one
   Approve records the list as the spec's ranked AVL, covering every
   designator sharing the spec and every future design.

## Consequences

- The deterministic fast path (`requirements/specs.py`) stays frozen at the
  trivially unambiguous cases; ambiguity goes to the LLM/user, not to more
  regexes.
- AI remains advisory, optional, replaceable (PRD §13): it proposes specs
  and envelopes with confidence + rationale; below 0.8 confidence the
  engineer decides.
- Interpretation latency is paid lazily the first time the engineer opens an
  uncached unresolved line; the result is reused thereafter.
