# ADR-0002 — Persistence: SQLite for the knowledge store

**Status:** Accepted
**Date:** 2026-07-10

## Context

`docs/architecture.md` §8 deliberately withdrew SQLite as a settled choice
("not approved merely because it appeared in an earlier draft"). Meanwhile the
`house-parts-bom` implementation built and proved a SQLite knowledge store at
`~/.hendley/parts.db`: schema versioning via a `meta` table, a
single-transaction v1→v2 migration with rollback, and 86 passing tests. A real
user database exists at that path.

## Decision

SQLite **is** the persistence technology for the knowledge store (House Parts,
Part Choices, audit trail) and future project-state storage.

Rationale:

- Zero dependencies (stdlib `sqlite3`) — holds the requests-only core rule.
- Single-user, local-first product profile (PRD §15.3); no server, no ORM.
- The migration discipline is already proven in production data: versioned
  via `meta.schema_version`, single `BEGIN IMMEDIATE` transaction, rollback to
  pristine on failure.
- A real v2 database already exists; continuity beats a rewrite.

Constraints carried forward:

- Every schema change is a numbered migration; chains run in order on open
  (v1→v2→v3…).
- Destructive migrations write a file-copy backup beside the DB first.
- Tests never touch the default DB path (`HENDLEY_DB` points at temp files).

## Consequences

- Closes "persistence technology and migrations" in architecture.md §14.
- The `KnowledgeStore` contract stays storage-agnostic; SQLite is the
  implementation, not the interface.
