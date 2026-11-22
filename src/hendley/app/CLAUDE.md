# `src/hendley/app/` — notes for Claude

Moved from the root `CLAUDE.md` on 2026-11-22. The root's "Invariants — never break these" still apply here.

- `src/hendley/app/` — **the app, the primary interface** (ADR-0003/0004):
  `hendley app` serves a stdlib-only local web UI on 127.0.0.1 (`server.py` =
  JSON API 1:1 over library calls; `ui.py` = the single embedded page). One
  page: left rail = Refresh + board qty + the design's components colored by
  state (green covers / red short-or-unpicked / amber unnamed-part-needs-a-look
  / dashed DNP). **The rail and panel titles show the DESIGN'S OWN WORDS** —
  schematic VALUE + library footprint, verbatim (`D6 D7 D8 D9 · D-SOD323`);
  what the app worked out lives in the panel's read-only `recorded as` line,
  never in the title (ADR-0007 — the app quoting its own guess back as fact
  is how a fabricated `1000V` once became "the design").
  Click a component → detail panel: **the search box (ADR-0007) is on every
  panel and the overview** — one line: **[part type ▾] [type anything] [Search]**,
  seeded from what's remembered. The AGENT plans the query (`/api/search`),
  Python fires it and PROVES every result against every term, showing the
  say-line, the counts, and every rejected part **with its reason** (`is 100,
  not ≥ 250`). **Nothing about the query is hidden or fixed**: the part-type
  popup shows the table actually used and overrides the agent (`auto` = let it
  read the part; `— no part type —` = keyword-only, and the page warns that
  words must then be specific); an overridden type is remembered as the shop's
  convention for that designator letter (`X → connector` — `X` is a connector
  in one library and a socket in another); and **"the actual search"** shows
  the literal request + every proven term, each droppable, plus add-a-term
  (fields offered from `/api/categories`). An edited query fires EXACTLY as
  given (no agent call) and the request is rebuilt from the terms, so a dropped
  term can't sneak back in as a net param. Deterministic R/C lookups still
  auto-run at Refresh — into the same table, showing their query the same way.
  **A FAMILY line searches itself (ADR-0008)**: the designer already typed
  `ULN2003` and the board already states the land, so there is nothing left for
  the engineer to type — asking them to would be asking them to repeat the
  schematic back to us. `/api/search` with no `terms` on a line carrying a
  `family` fires `search=<family>&package=<package>` and returns the panel's
  `family` block: the complete part number for this land, the class (a LABEL),
  and the **traps** — shown, never silently substituted. The package is read off
  the CATALOG'S OWN LIST for that family (asked once, then cached), never guessed
  from the footprint name: the library says `SOIC-4` where the catalog says
  `MBS`, and firing the guess returns zero rows while looking exactly like a part
  JLC doesn't stock. **A land is a SET of the catalog's words** — `SOIC-8` and
  `SOP-8` are the same 3.9mm body and hold DIFFERENT parts (the Basic 327k-stock
  SP3485 is under `SOIC-8`), so the sieve's `in` op carries all of them and the
  net widens to the family alone. A different BODY is still a different land:
  150-mil `SOIC-16` ≠ 300-mil `SOIC-16-300mil`.
  **The results are ONE comparison table, and it holds only the parts you can
  ORDER**: every part that satisfies EVERY term and covers the run, with its
  actual value under each criterion as a column (`value = 10uF`,
  `voltage ≥ 50V`, `Diameter = 5mm`), so a part is picked by reading DOWN a
  column, not by opening fifty datasheets. **A part that fails a term, or is
  short of the run, is NOT a row** — it cannot go on the board, and the goal is
  open → refresh → assign → alternates → export, not browsing the catalog. So
  **the table carries no red cell at all**. Nothing is hidden, though: the
  say-line counts them (`100 looked at · 12 you can order · 88 can't be used
  (24 short of 500, 64 fail a term)`) and **`show the N you can't use`** puts
  them back with their red reasons — which matters in exactly one case, when
  NOTHING is orderable and the app must name the term that did the killing (a
  bad term rejecting 100 good parts looks just like an empty catalog otherwise).
  Column rule: a term earns a
  column iff the CATALOG names the field (`package`/`capacitance_farads` are
  query plumbing and don't; `tolerance_fraction` IS the catalog's `Tolerance`
  and does — via `CATALOG_ALIAS`, or the engineer sets `0.01` and reads `±1%`
  with nothing on screen tying the two together). **ONE TERM PER FIELD**: the
  sieve collapses names that differ only in case or punctuation (`resistance` /
  `Resistance`), keeping the term that can actually be proven — stating both
  compares `10000` against `"10kΩ"` and rejects every part alive.
  `show all N specs` adds every other catalog
  parameter. Headers are the shop's words (`value`, `voltage`, `temp_co`,
  `tol`) with the constraint stacked underneath; the field's real name is what
  the sieve, the sort and the term list still use.
  **Selections save themselves** — there is no commit button. The radio picks
  what mounts (order-only when overriding an approved part; recorded at the head
  of the list on a first pick — `rank` is a DB column, never a word on screen);
  the **alt checkbox** grows/prunes the AVL from either table (unchecking is the
  one audited removal path). Both fire `/api/approve` / `/api/remove` on the tick. The two tables use SEPARATE radio groups (`pick`
  and `found`): the same part appears in both, and one shared group meant the
  lower table silently unchecked the upper one on every render. Opening a panel
  live-verifies its whole list, `????` when live access is down — never
  stale-as-current. The requirement's key comes from the READING the panel
  already made (`/api/key` answers from it — the agent is only asked when the
  schematic named the part *nothing*, where the engineer's search words are the
  only thing that knows what it is). An **unnamed part** (no VALUE, no MPN)
  never mounts silently: amber, says which part and why, and the one button
  that remains — *"I've looked at this"* — is its acknowledgement (draft
  `acks`). A **schematic-pinned part is a DEFAULT, not a lock**: approve a list
  against it and the recorded key converts the line to spec-driven at intake, so
  a short pin substitutes down the list instead of blocking the order.
  **Never show the word "rank" in the UI** — the engineer sees a *chosen* part
  and its *alternates*; rank is internal bookkeeping.
  **DNP this run** (title line, immediate like board qty) sits a part out of
  the current run only — `DNP · this run` in the rail, excluded from export and
  its gates, restored by **Populate this run**, schematic DNP untouchable;
  Placement section edits `data/cpl-rotations.json`;
  Export BOM/CPL in the title bar stays disabled until all rows are green
  (Chromium: standard folder picker for the copies). Page load repopulates
  from the last read (`~/.hendley/design-cache.json`) with all corrections
  re-applied; picks/searches/qty/per-run DNPs/acks persist via the server-side
  draft (`~/.hendley/draft.json`, cleared on clean export). Zero new
  dependencies.
