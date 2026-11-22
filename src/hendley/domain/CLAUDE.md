# `src/hendley/domain/` — notes for Claude

Moved from the root `CLAUDE.md` on 2026-11-22. The root's "Invariants — never break these" still apply here.

- `src/hendley/domain/model.py` — the canonical vocabulary: `SpecKey`
  (**`kind` + `package` required; `value` OPTIONAL** — a general-purpose diode
  has none, and a key that demands one only ever gets a fabricated answer,
  ADR-0007; the agent derives the key, the engineer never types it),
  `RequirementLine` (one selection mode: spec | mpn | provider refs; `dnp`
  carried), `RequirementsBom` (versioned JSON, `requirementsBomVersion: 1`),
  `Check` + the `CHECKS` severity table (error blocks upload / warning /
  info). Core layers (`domain`, `knowledge`, `resolver`, `requirements`)
  never import concrete providers or `datasources/jlc`.
