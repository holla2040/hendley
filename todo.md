# TODO — architecture decisions to investigate

(Working list of decisions we need to track that aren't settled in
`docs/adr/` yet. The formally open items also live in
`docs/architecture.md` §14 — this file is the scratchpad in front of that.)

## ~~Approval queue must be value-aware (no manual typing)~~ — DONE

Resolved 2026-07-11: discovery filters by value (ohms/farads), decisive
parameters shown, and the queue now proposes a reorderable 3-row AVL
(rank 1 + 2 alternates) recorded in one Approve. Ad-hoc value strings and
legacy footprint names are interpreted by the LLM tier (`claude -p`),
cached with provenance, with one-time confirm cards as fallback and fit as
a hard constraint — see `docs/adr/0005-llm-interpretation.md`.

## Shared House Parts database (not local)

**Investigate replacing / augmenting the local `~/.hendley/parts.db` with a
shared House Parts database.**

- Today the knowledge base is per-machine (`~/.hendley/parts.db`,
  overridable via `--db` / `HENDLEY_DB`). Two problems with that:
  1. **Multi-machine, one user:** Craig does schematic work on four
     different computers and needs the same House Parts / AVLs on all of
     them. A local file means four diverging databases.
  2. **Multi-user:** if several people use Hendley (and are all ordering
     through JLC), why should each of them re-find and re-vet a house part
     someone else already found? Approved parts are exactly the knowledge
     worth sharing.
- **Curation/vetting concern:** a shared database multiplies the cost of
  bad entries. There may need to be a vetting process for write access —
  who may record/rerank/remove choices — so we don't write a lot of bad
  information into the shared House Parts list. (Read access could be much
  looser than write access.)
- Things the investigation should cover:
  - sync model: one hosted DB vs. sync/replication of the SQLite file
    (e.g. Litestream/LiteFS-style) vs. an API service in front of it
  - the PRD already anticipates knowledge *scopes* (project / user /
    organization — PRD §14.3, org deferred from v1); a shared DB is
    essentially the organization scope — design them together
  - write vetting: roles, review queue for new Part Choices, or
    propose-then-approve flow; the existing append-only audit trail is the
    right substrate for accountability
  - offline behavior: orders must still resolve when the shared DB is
    unreachable (local cache with sync?)
  - schema is already provider-neutral (v3) and access already goes
    through the `KnowledgeStore` contract, so a remote implementation has
    a clean seam — no source changes yet, this is investigation only.
