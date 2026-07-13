# The Hendley app (`hendley app`)

The primary interface (ADR-0003/0004): a local web app served by the CLI —
Python stdlib only, zero extra dependencies, bound to `127.0.0.1`.

```bash
hendley app            # serves http://127.0.0.1:8341/ and opens the browser
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
- **Design Overview** (nothing selected): one row per part — LCSC code
  (linked to its product page), stock/need, unit and order cost, JLC
  Basic/Extended class — with the per-board parts cost on the title line.
- **Click a component** for its detail panel: one table, radio column on the
  left. **The selected radio is what mounts for this order.** Your part
  leads the table (no radio when it can't cover the order); live-verified
  alternates follow with manufacturer, package, class, and a `why` column
  carrying only judgments the other columns don't (prior approvals,
  shortfall warnings). Sort by stock, price, or class from the headers.
  Opening a panel **live-verifies its whole list in one batched call** —
  every number is current as of that click; when live access is down the
  cells say `????` rather than dressing cached values as current.
- **Pick semantics**: the *first* pick for a spec with nothing approved is
  the choosing — recorded permanently as the AVL rank 1 ("picked in the
  app"). A pick that *overrides* an existing approved part is **this order
  only** ("undo — use the automatic pick"); the preferred part returns
  when its stock does.
- **Alternates grow the list**: the **alt checkbox column** marks parts for
  the spec's ranked list (ranks 2, 3, … — the next design with the same
  part gets the preferred pick *and* its alternates straight from the
  database, no search, and silent substitution covers a short rank 1).
  Every approved part renders pre-checked — the mounted part included —
  and unchecking prunes it from the AVL, audited.
  **Nothing saves on click** — radio and checkbox selections stage until
  the **Update** button (on the part-title line) commits them in one act.

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

**Nothing is hidden and nothing is invented.** Above the results is the line
the agent understood ("22k 0603, 1% or better, 1/4W or better"), how many
parts it looked at, and how many matched. Below them, **"N didn't match your
terms"** opens onto every rejected part *with the reason on its row* — `is
100, not ≥ 250` when your 1/4 W demand meets an ordinary 100 mW 0603, `is
0.05, not ≤ 0.01` for a 5 % part. A part whose data can't settle a term is
listed as uncheckable, never quietly passed. "No parts" is never a mystery.

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
one **Update** confirms it for that design. The box is pre-populated with the
remembered words, so changing your mind is one edit away.
- **Schematic-pinned parts** (an `LCSC` attribute) are verified as-is, with
  the same **Search Alternates** button for order-only substitutes; an
  MPN-only attribute is called out honestly (JLC can't verify by MPN).
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

**The schematic must be the current document before every Refresh** (click
its tab/canvas), with no modal dialog open — an open dialog makes reads come
back empty. A Refresh reads the schematic first and then switches Fusion's
electronics engine to the board to read placements; that switch is one-way,
so the engine is left on the board context afterward. Make the schematic
current again before the next Refresh.
