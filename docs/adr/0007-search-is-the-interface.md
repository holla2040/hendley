# ADR-0007 — The search box is the interface: the agent plans, Python proves

**Status:** Accepted (settled in discussion with Craig, 2026-07-13; supersedes
ADR-0006 §"human-fired searches" and retires the four-field spec form).
**Date:** 2026-07-13

## Context

The four-field spec form (kind / value / package / qualifier) put the AVL's
**database key** in front of the engineer and made him fill it in. On an
unlabeled diode — no schematic VALUE, because a general-purpose diode has no
"value" — the form refused to search without one, so a `1000V` got typed into
the value field, was recorded as an authoritative user answer, and was then
displayed back in the title as though the design had said it. Every part of
that is wrong: the form leaked a schema, extorted a fiction, and then quoted
the fiction as fact.

What an engineer wants from this step is what every search box of the last
twenty years does: **type what you want, press Search, get parts.** That step
is the keystone of the whole tool — a BOM workbench nobody can search is a BOM
workbench nobody will use.

Two things were measured against the live index before designing it, and both
overturned the obvious approach:

1. **The index cannot be trusted to filter.** jlcsearch category endpoints
   honour `package` plus one value param (`resistance` / `capacitance`) and
   **silently ignore every other param** — including invented ones
   (`made_of=cheese` changed nothing). A "10uF 0805 X7R 25V" query returns 100
   rows whose top hit is a **100 nF 50 V X5R** part. No error, no warning; it
   simply looks filtered. Column names lie too: `power_watts` is milliwatts.
2. **Full-text search is worse the harder you try.** `components?search=` ANDs
   tokens against part *names*: `22k 0603` mixes a 2.2 nF capacitor into the
   resistors, and `10uF 0805 X7R 25V` — the more you specify, the fewer
   name-matches survive — collapses to 3 rows. Passives are precisely where
   engineers type the most words.

So neither the query nor the keyword index can be the source of truth, and
Python must not compose either (ADR-0006: it parses no names, invents no
filters).

## Decision

**The agent plans the query; Python executes it and proves every result.**

One search box on every panel (and the overview), seeded from what the app
remembers, accepting any text. On Search, `claude -p` turns the engineer's
words — plus the design line they were typed against — into a **plan**:

- **net** — only the params the index actually honours. A coarse net to fetch
  fewer rows. Nothing is trusted about it.
- **sieve** — typed predicates (`tolerance_fraction ≤ 0.01`,
  `temperature_coefficient = X7R`, `power_watts ≥ 250`) covering **every**
  constraint the engineer stated, *including the ones already in the net*.
- **lookingFor** / **say** — the agent's reading, for the screen only.

Python fires the net, live-verifies every hit against the JLC API, and then
proves each candidate against each sieve term by **pure comparison** over data
it holds (the index row's typed columns, the row's `attributes`, the verified
`parameters`). A term that cannot be checked is a **miss**, never a pass.

The invariant that makes the index's dishonesty harmless: **every net param is
re-asserted in the sieve** (`NET_COLUMNS`), so a param the index quietly
dropped still cannot leak a wrong part through.

Rejected parts are kept and shown with their reason (`is 100, not ≥ 250`).
"Nothing matched" is always accounted for.

**Every part of the query is visible and overridable.** A plan the engineer
cannot see is a plan they cannot correct — and the category is the most
load-bearing part of it, since it picks the table (deciding both which parts
can appear and which columns exist to filter on). So:

- the **part type is a popup on the search line**, showing the table actually
  used; `auto` lets the agent read it off the design line, and an explicit
  choice is final (`GET /api/categories` serves the 44 tables and each one's
  filterable columns — no magic words to guess);
- **— no part type —** means "don't narrow to a table": words are matched
  against part names only, and the page says so before the search runs;
- **the actual search** panel shows the literal request and every proven term,
  each droppable, with an add-a-term row. An edited query is fired **exactly as
  given** (no agent call), and the request is *rebuilt from the terms*, so a
  dropped term cannot sneak back in as a net param;
- an **overridden category is remembered as the shop's convention** for that
  designator letter (`X → connector`), because `X` is a connector in one
  library and a socket in another and no agent can know which.

Corollary: the deterministic lookups the app runs unasked must show their query
in the same panel, and be editable the same way (`discovery.query` on the queue
entry). A lookup the engineer didn't ask for owes them the query all the more.

**The AVL key is derived, never typed.** At pick time the agent names the
requirement (`derive_key`) from the design line, the engineer's search words,
and the picked part's verified facts. `SpecKey.value` therefore becomes
optional: a part with no value gets none, and nothing is fabricated.

**An unnamed part is never mounted silently.** When the schematic gives no
VALUE and no MPN, what the app remembers is a guess about intent — the same
footprint in another design could be a different device. The line comes up
amber, states which part it is about to mount and why, and requires one
**Update** per design.

## Consequences

- A search costs one `claude -p` (~9 s) the first time those words are used on
  that line; the plan is cached forever (`interpretations`, scope `search`).
  Deterministic R/C lookups still run at Refresh with no agent call — and land
  in the same results table, under a line saying what was looked up.
- The four-field form, `/api/confirm-spec`, `/api/explore`, the amber
  "needs a spec search" state and "Edit spec" are all **gone**: the box is the
  edit path, and re-searching + re-picking re-keys the line.
- The rail and titles show the **design's own words** only. The derived key is
  visible, read-only, in the panel (`recorded as …`).
- Honest failure is the design goal: when the index truncates at 100 rows, or a
  part doesn't publish a column, the page says so.

## Alternatives rejected

- **Free text straight to full-text search.** What a naive box would do. It is
  the trap above: it looks like it works, mixes part types, and degrades as the
  engineer adds detail.
- **Let the agent name query params freely.** Any hallucinated param is
  silently ignored by the index and the results look filtered. Fatal.
- **Python parses the engineer's text.** ADR-0006 exists because that is how
  the tool ships the wrong part; a regex tier would be re-litigating it.
