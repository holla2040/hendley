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
  order is covered, light red = short or unresolved, amber = needs a spec
  search, neutral = present but unverifiable (an MPN-only pin — see below),
  dashed = DNP (sunk to the bottom). On page load the app
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
  the **Update** button (on the part-title line, beside **Search
  Alternates**) commits them in one act. Search Alternates reopens the
  seeded search on any saved part, so the list can grow later without
  undoing anything.
- **Searches are yours**: discovery auto-runs only where the query is
  deterministic (R/C value params, chip packages). Everything else shows a
  search box seeded from the spec — *you* fire it, verbatim, and results
  split honestly: package-confirmed on top (the agent judges each library
  footprint to its catalog package — `C-0603` → `0603` — cached forever),
  with "N other packages" and "M can't cover the order" expandable below.
- **Schematic-pinned parts** (an `LCSC` attribute) are verified as-is, with
  the same **Search Alternates** button for order-only substitutes; an
  MPN-only attribute is called out honestly (JLC can't verify by MPN).
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
- **Nothing is lost to a reload**: picks, searches, and the board quantity
  write through to a server-side draft (`~/.hendley/draft.json`, per
  design), reconciled by line identity on the next load and cleared by a
  clean export.

Under WSL2 the Windows browser reaches the WSL loopback directly — no
port-forwarding needed for the app itself. The app starts fine without JLC
credentials; live actions report the missing `.keys` when first used.

Reading a live design (the **Refresh** button) does need Fusion running with
an Electronics document open, its HTTP endpoint enabled (the
**Preferences > General > API > Fusion MCP Server** toggle), and — under
WSL2 — the port forward up: see
[Reaching Fusion from WSL2](fusion-notes.md#reaching-fusion-from-wsl2--the-windows-port-forward).
