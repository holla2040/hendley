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

## Amendments — what the first real design taught us

Everything below was **measured**, not reasoned about, by driving the app at one
line (`C4 C12 C13 C14` — a 10 µF 50 V aluminium electrolytic in a D5 × 5.4 mm
can) until it could actually be used to choose a part.

### The sieve speaks the CATALOG's language, not the index's

The index's `attributes` blob is a scrape of the **raw datasheet keys**, and they
drift per manufacturer: of 680 sampled electrolytics, 583 call the diameter `φD`
and 62 call it `Diameter`. The official API's `parameters[]` are **normalized** —
`Capacitance`, `Voltage Rating`, `Diameter`, `Height - Seated (Max)`, identical
for every maker — and they arrive in the `verify()` call the app already makes.
Sieving on the blob records an honest-looking *miss* on a part that in fact
matches, which is the worst failure this ADR exists to prevent. The blob is out
of the proof path. Terms are written in the catalog's names.

### A term may declare its unit — and that is what makes "or better" possible

A catalog value is TEXT (`"50V"`, `"5.4mm"`). Until a term could carry the unit
the catalog prints, `Voltage Rating >= 50` was *uncheckable* and every part
missed — so the engineer was forced back to exact-match, and a 63 V can, a
strictly better drop-in, was invisible. A term now carries `unit`, and Python
coerces the string **only** against the unit the agent declared. It still never
guesses: `"17mA@120Hz"` asked for in mA remains an honest miss.

### The index publishes 44 columns that are a LIE

`capacitors.is_polarized` is `false` on **every** aluminium electrolytic.
`diodes.is_schottky`, `is_zener`, `is_tvs` are `false` on every schottky, zener
and TVS. The agent, handed these as a menu of facts, wrote `is_polarized isTrue`
and **rejected all 36 good candidates** — a wall of "✗ False is not true". They
are constant, always-null, or too sparse to prove anything; they are now absent
from the agent's menu (`UNPROVABLE_COLUMNS`). **A part's class comes from the
catalog's `secondTypeName`, never from an index flag.** And a cached plan that
names one is thrown away rather than replayed, or the bug would outlive its fix.

### There is no one approach across part types — so stop looking for one

Resistors put power in milliwatts; electrolytics hide the can dimensions inside
the package string; diodes split into families the index cannot distinguish at
all. That is knowledge, and it belongs written down: `docs/parts/`, one note per
class, read into the prompt when the agent opens a part of that class. It works —
the agent now leaves `Tolerance` out of an electrolytic's sieve *on its own*,
because `eq ±20%` would reject a better ±10% part, and says so.

### The results are a comparison table, and selections save themselves

A list of parts with a *reason string* on each rejection cannot be used to choose
between them; the engineer would have to open fifty datasheets. The results are
now ONE table with the criteria as **columns** — a part is picked by reading down
a column, and a failing part keeps its row and all its numbers with only the
failing cell red. Rejects stay pickable (35 V may be fine on that rail); short
STOCK is not a judgment call, so it sorts last and is marked.

The **Update button is gone**. Ticking a checkbox records the alternate; the
radio records the pick. Both are a SQLite write, and the staging gate was buying
nothing — it was gating them behind a *second* agent call that re-derived a key
the panel's own reading had already produced. The button survives only for the
one act that is not a selection: confirming an unnamed part.

**A schematic pin is a default, not a lock.** A pinned line can now hold an
approved list: the recorded key converts it to spec-driven at intake, so a short
pin substitutes down the list instead of blocking the order.

**"Rank" is never shown.** The engineer sees a *chosen* part and its
*alternates*. A radio means one choice; a checkbox means membership. Those
conventions are older than this tool and were not ours to reinvent.
