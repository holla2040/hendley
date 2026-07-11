# TODO — architecture decisions to investigate

(Working list of decisions we need to track that aren't settled in
`docs/adr/` yet. The formally open items also live in
`docs/architecture.md` §14 — this file is the scratchpad in front of that.)

## Approval queue must be value-aware (no manual typing)

Found live with R10 (82k 0402, 2026-07-11): an escalated resistor's queue
entry discovered candidates by **package only**, so the list was
mixed-value junk — and the workaround was typing the part into the record
form by hand. Wrong workflow; the queue should have been one click.

- Include the value in discovery for kinds where jlcsearch has a dense
  param (`resistance`, `capacitance`) — the spec's canonical value needs
  converting to the param's unit (e.g. `82k` → `82000`).
- Show the decisive parameters (resistance/tolerance/package) in the
  queue's candidate table so a pick is judgeable at a glance.
- Goal: escalation → queue → radio button → Record approvals. Manual
  `db record` / the form is for deliberate curation only, never the happy
  path.

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
