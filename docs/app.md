# The Hendley app (`hendley app`)

The primary interface (ADR-0003/0004): a local web app served by the CLI —
Python stdlib only, zero extra dependencies, bound to `127.0.0.1`.

```bash
hendley app            # serves http://127.0.0.1:8341/ and opens the browser
hendley app --interpreter claude  # use Claude instead of the Codex default
hendley app --model gpt-5.6-terra # select the Codex model for this run
```

One page — the order workbench (2026-07 redesign) — a thin surface over the
same library the CLI uses:

- **Left rail**: **Refresh** (reads the open Fusion design — schematic view
  active — then resolves against live JLC stock in one click) and the board
  quantity, above the design's components colored by state: green = the
  order is covered, light red = short or nothing picked yet, amber = an
  unnamed part waiting for your eyes (see below), neutral = present but
  unverifiable (an MPN-only pin), dashed = DNP — the schematic `DNP`
  attribute or a part value of literally `DNP` (sunk to the bottom).
  **The rail and the panel titles show the design's own words** — the
  schematic VALUE and the library footprint name, verbatim (`D6 D7 D8 D9 ·
  D-SOD323`). What the app worked out about a part is bookkeeping and lives
  in the panel's `recorded as` line; a rail that showed you the app's own
  guesses would be a rail you couldn't check. On page load the app
  repopulates from the last read (`~/.hendley/design-cache.json`) with every
  correction re-applied — no Fusion round-trip until you want one.
  Refresh itself is deliberately **cache-only**: it never launches Claude.
  Exact identities, deterministic passives, and prior readings resolve at once;
  a new ambiguous part remains red/yellow until you open it.
- **Design Overview** (nothing selected): one row per part — LCSC code
  (linked to its product page), stock/need, unit and order cost, JLC
  Basic/Extended class — with the per-board parts cost on the title line.
- **Click a component** for its detail panel: the part you chose and the ones
  approved beside it, with manufacturer, package, class, stock and price.
  **The radio is what mounts for this order. The checkbox is what's on the
  approved list.** That is the whole vocabulary — nothing is numbered at you.
  Sort by stock, price, or class from the headers. Opening a panel
  **live-verifies its whole list in one batched call** — every number is
  current as of that click; when live access is down the cells say `????`
  rather than dressing cached values as current.
  Opening an uncached red/yellow part runs one lazy agent reading, records its
  requirement, re-resolves that row, and immediately runs the generated first
  catalog search. The original component click is the whole first-use action;
  there is no redundant Search click after waiting for categorization. Later
  opens and Refreshes reuse the cached reading without automatically firing a
  new search. Family lines skip generic reading and open their bounded family
  search.
- **Selections save themselves.** Tick a checkbox and that part is on the
  approved list; untick it and it is pruned (audited). Pick a radio and that
  part mounts. There is no button to press — it is a database write, and it
  happens on the tick, in whichever table you ticked it in.
- **Pick semantics**: the *first* pick for a requirement with nothing approved
  is the choosing — recorded permanently as the head of its approved list
  ("picked in the app"). A pick that *overrides* an existing approved part is
  **this order only** ("undo — use the automatic pick"); the preferred part
  returns when its stock does.
- **Alternates grow the list**: the next design with the same part gets the
  preferred pick *and* its alternates straight from the database — no search,
  and a short preferred part substitutes silently down the list. Every approved
  part renders pre-checked, the mounted one included.
- **A schematic pin is a default, not a lock.** A part the schematic pins by
  LCSC code can still be given an approved list: choose it, approve alternates
  beside it, and from then on the line resolves against that list — so a short
  pinned part substitutes instead of blocking the order.
- The one button left is on an **amber** line — a part with no VALUE and no part
  number. *"I've looked at this"* is its acknowledgement, because nothing should
  mount silently when the design never said what it is.

## A family part searches itself (ADR-0008)

You place an IC and type **`ULN2003`** into the schematic VALUE, because the value
shows on the schematic and that is convenient. You are never going to type
`SP3485EN-L/TR` in there, and the app does not ask you to.

`ULN2003` is a **family**, not a part. It ships as SOIC-16, SOP-16, TSSOP-16, DIP-16
and a wide-body SO-16-208mil — and **the footprint already on your board decides which
one you may order**. So the app does that for you: you typed the words, the board
states the land, and there is nothing left for you to type. Open the panel and the
candidates are already there.

What it shows you, and why:

- **The part number for your land.** The datasheet's ordering table is the only place
  that says a ULN2003 `D` suffix is a 3.9 mm SOIC and an `NS` is a 5.3 mm SOP. The app
  looks it up once per family, on the web, and remembers it forever.
- **The traps** — the parts that fit the same land and are *not* the same part. These
  are shown, never silently substituted:
  - **`PCF8574A` is a different I²C address** (0x38, not 0x20) in an identical body. It
    will solder down perfectly and your firmware will not find it.
  - **`MB6S` is 600 V** where `MB10S` is 1000 V. Same `MBS` land.
  - **`MAX485` is a +5 V part** on the identical SOIC-8 pinout as the 3.3 V `SP3485`.
  - **`EL357N` has 3–5× less current transfer** than an `LTV-352T`. Same SOP-4 land.
- **Only the parts you can order.** A wide-body part, a TSSOP, a DIP — they all answer
  to the name "ULN2003" and none of them can go on your board. They are not rows.

If the app cannot work out which package your footprint is, it **says so and names the
packages the catalog does stock the family in** — rather than firing a guess, which
would return nothing and look exactly like "JLC doesn't have it".

Before this, a family in the MPN attribute was treated as an **exact orderable part** —
pinned, never checked, sent to the resolver as if you could buy a `ULN2003`. You can't.

## The search box (ADR-0007)

**One box, on every panel, always.** Type whatever you want and press
Search — `22k 0603 1% 1/4W`, `10uF 0805 X7R 25V`, `1N4148WS`, `C25804`, or
just leave the seed alone. It is pre-populated with what the app remembers
for that part, and it is there on green parts too: hunting a better part is
not something you should have to be in trouble to do. The Design Overview
has one as well, for looking anything up without opening a part.

**The agent reads your words; Python proves the results.** Your terms go to
Claude, which turns them into a query plan for the catalog — and the plan
carries every constraint you typed, twice: once as the *query*, once as a
list of terms to check each result against. That second list is the one that
matters. The parts index **silently ignores query params it doesn't know** —
ask it for X7R at 25 V and it hands back a 100 nF 50 V X5R part without a
word of complaint — so a search that trusts its own query ships the wrong
part. Every result you see has been fetched, live-verified, and then *proven*
against each of your terms.

**The results are one table, and the criteria are its columns.** You pick a
part by reading *down* a column, not by opening fifty datasheets:

```
       LCSC       MANUFACTURER  MPN                 value    voltage  dia    height   LIVE STOCK
  ◉ ☑  C72487     —             RVT1H100M0505       10uF     50V      5mm    5.4mm       111,412
  ○ ☑  C22387980  FOLLON        EFVL063ADA100M0554  10uF     63V      5mm    5.4mm         4,031
  ○ ☐  C280397    ROQANG        RT1V100M0505        10uF    [35V]     5mm    5.4mm        22,418
  ○ ☐  C2992591   KNSCHA        RVT10UF25V67RV0020  10uF    [25V]   [6.3mm]  5.4mm         3,957
```

**The table is the parts you can order.** A part that fails a term, or that
hasn't the stock to fill this run, does not get a row — it cannot go on the
board, and the job is to get the order out, not to browse the catalog. So there
is no red cell in the table: every part in it satisfies every term and covers
your board count.

Nothing is *hidden*, though — the say-line above the table counts them
(`100 looked at · 12 you can order · 88 can't be used (24 short of 500, 64 fail
a term)`), and **show the 88 you can't use** puts them back with their reasons in
red. That matters in exactly one case: when nothing is orderable, the app names
the term that did the killing — a bad term rejecting 100 good parts otherwise
looks identical to an empty catalog.

Note the 63 V part. It is *over-rated*, drops straight into a 50 V slot, and an
exact-match search would never have shown it to you — which is the whole reason
a term can say "or better".

**Short stock is not a judgment call.** A part that matches but has too few in
stock to fill the run sorts to the bottom with its stock in red. There are 174 of
them and you need 400; no opinion changes that. Its checkbox still works, because
stock recovers and the approved list outlives this order.

**show all N specs** widens the table to every other parameter the catalog
publishes for these parts — ripple current, ESR, lifetime, operating
temperature — for the last call.

## Changing the search — all of it

**The part type is a popup on the search line**, to the left of the box, and
it always shows the table the search actually used (`resistors`,
`capacitors`, `diodes` …). That single choice decides which parts can appear
*at all* and which columns exist to filter on, so it is never made behind
your back. Leave it on **auto** and the agent reads it off the part; set it
yourself and your choice is final.

Choose **— no part type —** and the catalog is never narrowed to a table:
your words are matched against part *names* only. The page says so on the
spot. That's the right tool for `1N4148WS` and the wrong one for `22k`
(which would find parts with "22k" *in the name*).

**Correct it once and it sticks.** Override the type on an `X1` and the app
records `X → connector` as *your library's* convention and applies it to
every `X` in every design from then on — the same memory it keeps for
`D → diode`. Your library's letters mean what you say they mean: `X` is a
connector in one house and a socket in another, and no agent can know which.

**"the actual search — change any of it"** opens onto the literal request
(`resistors?resistance=22000&package=0603`) and every term each result had to
satisfy. **drop** any term, or add one by hand (the field list offers the
columns that part type actually publishes, so there are no magic words to
guess) — and it re-runs *exactly as you edited it*, with no agent in the
loop. Drop a term and it is genuinely gone: the request is rebuilt from your
terms, so nothing can quietly re-assert itself. The lookups the app runs for
you unasked (a plain `22k` on an `0603`) show their query in the same panel
and are edited the same way.

For an image-read unresolved part, editing the search box changes discovery
words but does not silently erase schematic intent. Class, polarity/channel,
ratings, dimensions, and package proof stay attached until you explicitly drop
a visible term in this editor. Saved search text is scoped to the visual digest
it was written against; a new drawing revision starts from the new reading.

For a dense R/C value on a chip package there's nothing to judge, so the app
looks it up for you at Refresh — into the *same* results table, under a line
saying what it looked up. Your own search always replaces it.

## What gets remembered (and why it's never silent)

Picking a part is the only thing that writes to the approved-parts list, and
**the agent names the requirement for you** — from the design line, the words
you searched, and the part you picked. You are never asked to fill in
database fields. The key it chose is shown, read-only, under the box:
`recorded as resistor · 22k · 0603 · 1%`. To change it, search again and pick
again.

A **value** is only recorded when the part has one. A general-purpose diode
doesn't; an empty value is a correct answer, and demanding one only ever gets
a fabricated one.

When the schematic never named a part — no VALUE, no MPN, just a footprint —
whatever the app remembers is a guess about *intent*, and the same footprint
in the next design could be a different device. So it is **never silent**:
the part comes up amber, saying which part it's about to mount and why, and
one press of **"I've looked at this"** confirms it for that design. That is
the only button on the panel, because it is the only act that isn't a
selection. The box is pre-populated with the remembered words, so changing
your mind is one edit away.
- **Schematic-pinned parts** (an `LCSC` attribute) are verified as-is and
  searchable like any other. The pin is a **default, not a lock**: approve a
  list against it and the line resolves against that list from then on, so a
  short pinned part substitutes instead of blocking the order. An MPN-only
  attribute is called out honestly (JLC can't verify by MPN).
- **DNP for this run**: every panel's title line carries a **DNP this run**
  button — the part sits out *this* board run only (excluded from the BOM
  and CPL, its stock and pending spec search stop gating the export). It
  takes effect immediately, like the board quantity: the row goes dashed and
  sinks to the DNP section labeled `DNP · this run`, distinct from schematic
  DNP. **Populate this run** on the DNP'd part restores it — pick, search,
  and all. The flag lives in the order draft (never the schematic or the
  parts DB), survives reloads and Refreshes, and clears with the draft on a
  clean export. A part DNP'd in the schematic stays Fusion's call — the app
  won't un-DNP it.
- **Placement (CPL)** in each panel edits `data/cpl-rotations.json` — set a
  rotation correction once (keyed by footprint/LCSC, never designator) and
  every later export applies it (details:
  [CPL rotation corrections](cli.md#cpl-rotation-corrections-datacpl-rotationsjson)).
- **Export BOM/CPL** in the title bar stays disabled until every row is
  green, then writes `bom.csv` + `cpl.csv` (+ the release snapshot) to the
  server's output directory. In browsers with the File System Access API it
  first opens the standard folder picker and saves copies where you choose;
  browsers without it silently skip the copies (Brave ships the API disabled —
  enable `brave://flags/#file-system-access-api` to get the picker).
- **Nothing is lost to a reload**: picks, searches, per-run DNPs, and the
  board quantity write through to a server-side draft (`~/.hendley/draft.json`,
  per design), reconciled by line identity on the next load and cleared by a
  clean export.

Under WSL2 the Windows browser reaches the WSL loopback directly — no
port-forwarding needed for the app itself. The app starts fine without JLC
credentials; live actions report the missing `.keys` when first used.

Reading a live design (the **Refresh** button) does need Fusion running with
an Electronics document open, its HTTP endpoint enabled (the
**Preferences > General > API > Fusion MCP Server** toggle), and — under
WSL2 — the port forward up: see
[Reaching Fusion from WSL2](fusion-notes.md#reaching-fusion-from-wsl2--the-windows-port-forward).

No modal dialog may be open—an open dialog makes reads come back empty. Hendley
uses `EDIT .S1;` when necessary to request schematic sheet 1, reads every
enumerated sheet, then uses `BOARD;` to read placements. That transition is
one-way for the remainder of the Refresh. Some Fusion MCP builds wedge their
script proxy when returning from board; if reads stay empty and `EDIT .S1;`
reports recursive proxy failure, toggle the MCP server or restart Fusion once.
Fusion exposes
`electronics.Sheet`, so multi-sheet designs can be enumerated without guessing.

### Lazy image-assisted intent

Refresh captures images but makes no model call. Fusion sheet/view changes are
given a short settle interval; stale PNGs are removed and each new export is
awaited. Board exports temporarily hide `UNROUTED`, and unresolved placements
receive centered 12 mm × 12 mm crops with their physical span recorded. Sparse
schematic pages also receive whitespace-trimmed detail images so small symbol
geometry remains readable. Opening a red/yellow unresolved part sends only its
own board crop plus schematic detail sheets to Codex—not other placements or a
redundant complete board. Unchanged images reuse the cached reading; a changed
digest or read-plan schema forces a new one.

The reading's intent is executable. Candidate class is proved against the live
catalog's `secondTypeName`, and dimensions are proved against live catalog
parameters. Keyword discovery is only a coarse net used to avoid the index's
100-row cap; it never proves suitability. Search terms generated by the app are
not persisted as engineer-entered draft text, so an old automatic phrase cannot
silently outrank a newer image reading.

A numeric label is not accepted when its catalog meaning is ambiguous. For
example, bare `18V TVS` does not say whether 18 V is stand-off, breakdown, or
clamp voltage. Such a reading sets `intent.ratingAmbiguous`, omits voltage from
the sieve, and cannot automatically name the requirement until the engineer
supplies the parameter, exact family/part, or an explicit shop convention.

Provisional family values do not suppress a completed visual reading. After a
lazy symbol read, its normalized search and proof terms populate the browser
even when intake initially classified the raw value as a possible family.
Unambiguous numeric ratings must use exact live catalog fields; index rating
columns are never candidate proof. Numeric comparison performs explicit SI
unit scaling (`1kV = 1000V`, `1A = 1000mA`) while continuing to reject compound
strings such as `17mA@120Hz` as uncheckable.

Lazy reading and live catalog verification can each take several seconds. The
results-table area immediately displays an animated, accessible status panel
for both phases—`Reading the component…` and `Searching the live catalog…`—so
the engineer sees activity exactly where the candidate rows will appear.
