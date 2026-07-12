# The Hendley CLI

The app (`hendley app`) is the primary interface — see [`docs/app.md`](app.md).
Everything the app does is also scriptable from the command line: one-shot part
lookups, BOM stock checks, alternate discovery, order-file generation, and the
Fusion design-change workflow. The CLI and the app drive the same library.

If the installed command is unavailable (venv not active, or `pip install -e .`
didn't land the script on PATH), run Hendley from the repository root:

```bash
PYTHONPATH=src python -m hendley.cli ping
```

Every `hendley <cmd>` below works the same way via that form.

## Quickstart

Verify request signing and API access:

```bash
hendley ping
```

Generate the JLCPCB order files from the open Fusion design (schematic view
active):

```bash
hendley pcba        # writes bom.csv + cpl.csv to ~/tmp/hendley_output/
```

Inspect one or more components:

```bash
hendley detail C2040
hendley detail C2040 C25879
```

Check a Fusion parts export or BOM for stock:

```bash
hendley stock PARTS.json --min-stock 100
```

Find and live-verify alternate candidates:

```bash
hendley alternates --list-categories
hendley alternates C315567   --category mosfets   --package "DFN-8(3x3)"   --top 10
```

Generate a Fusion migration script from reviewed changes:

```bash
hendley scr swaps.json -o changes.scr
```

## Commands

| Command | Purpose |
|---|---|
| `hendley ping` | Verify JLC credentials, signing, and permissions. |
| `hendley detail CODE...` | Retrieve component detail, stock, price tiers, parameters, and datasheet data. |
| `hendley private` | List private or consigned JLC inventory. |
| `hendley library` | Browse the JLC assembly component library. |
| `hendley fusion PARTS.json` | Validate and optionally enrich Fusion parts-export data. |
| `hendley stock PARTS.json` | Check BOM inventory and return nonzero on blocking stock problems. |
| `hendley pcba` (alias: `hendley jlc`) | Generate the JLCPCB PCBA order files (`bom.csv` + `cpl.csv`) from the live Fusion design, rotation-corrected and stock-checked; exits nonzero on stock blockers. |
| `hendley app` | Start the local web app (the single-page order workbench) on 127.0.0.1 — the primary interface. |
| `hendley db lookup\|record\|rerank\|remove\|list\|refresh` | The house-parts knowledge base: House Parts with deliberately ranked, audited Part Choices (the AVL). Local SQLite; only `refresh` hits the live API. |
| `hendley resolve REQUEST.json` | Resolve a Requirements BOM against the AVLs + live stock at the order's board count; `--queue` writes the batched approval queue for escalations; exits 1 on escalations. |
| `hendley bom RESOLUTION.json` | Render a resolution into the upload BOM CSV (JLCPCB, or `--provider pcbway`); a clean `-o` emit also writes the immutable release snapshot; blockers exit 1. |
| `hendley alternates CODE ...` | Discover candidates and verify each against live JLC data. |
| `hendley scr SWAPS.json ...` | Generate Fusion `.scr` migration commands from explicit reviewed swaps. |

Use `hendley <command> --help` for the authoritative option list.

**Output format.** `detail`, `private`, `library`, and `fusion` print **JSON** to
stdout by default — they have **no `--json` flag** (passing one is an error); pipe
them to `jq`/`python3` to parse. The `db` subcommands and `resolve` likewise
emit JSON to stdout by default. Only **`stock`** and **`alternates`** accept
`--json`; without it they print a human-readable report. `ping` prints a status
line; `scr` prints (or writes with `-o`) the `.scr` script; `pcba` writes its two
CSVs and prints the stock report. A command's flags are exactly what
`hendley <cmd> --help` lists — don't assume a flag exists because another
command has it.

## Generating JLCPCB order files (`hendley pcba`)

The one-command flow: with your design open in Fusion (**schematic view
active**), run

```bash
hendley pcba
```

and Hendley reads the live design over the HTTP bridge and writes **exactly two
files** to `~/tmp/hendley_output/` (override with `-o DIR`):

- **`bom.csv`** — `Comment, Designator, Footprint, JLCPCB Part #`; parts grouped
  by identical value / footprint / code, designators natural-sorted. `Comment`
  is the schematic value, falling back to the MPN; the JLC code comes from each
  part's `LCSC` attribute.
- **`cpl.csv`** — `Designator, Mid X, Mid Y, Layer, Rotation`; one row per
  populated placement, coordinates in mm.

Under the hood it: reads the schematic (parts + attributes; GND/supply symbols
and the title block are excluded), switches the electronics engine to the board
with the EAGLE `BOARD;` command (**one-way** — there is no command back, so the
schematic is always read first; the board window is not visibly raised, but
reactivate the schematic in the Fusion UI before the next run), reads the
placements and footprint names, applies rotation corrections (below), and
finally runs the same live JLC stock check as `hendley stock` — exiting nonzero
on out-of-stock / not-found parts so it can gate a submission. `--no-verify`
skips the check and needs no credentials.

Parts marked **do-not-populate** — the schematic `DNP` attribute set to anything
but `0` (test points, mount holes, programming pads), or the board element's
populate flag off — are excluded from both files and from the stock check (the
excluded designators are listed on stderr). Parts with no `LCSC` attribute that
*are* populated (e.g. connectors you solder yourself) are kept in both files but
flagged; JLC's uploader lists them unmatched and you leave them unselected.

### CPL rotation corrections (`data/cpl-rotations.json`)

Some library footprints are drawn with a zero-orientation different from what
JLC's feeder data expects — those parts need the same manual rotation in JLC's
order preview on **every** order. `data/cpl-rotations.json` records each fix
once, keyed by **part identity** (LCSC code or library footprint name — never
the designator: the flaw belongs to the library model and follows the part into
every design that uses it). `hendley pcba` adds each matched part's
`rotationOffsetDeg` (positive = counterclockwise, JLC's convention) to its board
angle. When a part needs hand-rotating in the preview, add an entry — it never
needs fixing again.

Known caveat: `Mid X`/`Mid Y` is the footprint **origin** (not the part
centroid), relative to the board origin — JLC's preview normally normalizes
this; if a part previews off-pad, that's an origin mismatch worth recording
alongside the rotations.

## The workflow

First, the distinction that decides where you work: an **order-time
substitution** ("mount a different part this run — the design is fine") is an
app gesture — click the red part, pick a radio, done. A **design change**
(different package or value, a new `LCSC` attribute, fixing a stale `MPN`) has
to land in Fusion, and that is this workflow.

There is **one** design-change workflow. A part needs to change — it's **out of
stock**, you want a **different package**, or a **different value** — and the
path is the same each time; only the trigger differs. It runs as an interactive
[Claude Code](https://claude.com/claude-code) session in this repo: Claude reads
the live design and does the JLC lookups, **you** make the design decision, and
**Fusion** is where the change is written (the Electronics *object* API is
read-only, but the `.scr` can be applied either manually or fired over the bridge
with `Electron.run` — see step 5). `comet` below is just an example design.

**Before you start**

1. Fusion is running with an **Electronics document open** and its HTTP endpoint
   enabled via the **Fusion MCP Server** toggle (see
   [`docs/fusion-notes.md`](fusion-notes.md)).
2. Under WSL2, the port forward is up — see
   [Reaching Fusion from WSL2](fusion-notes.md#reaching-fusion-from-wsl2--the-windows-port-forward).
3. Your `.keys` file is in place (or use the `PYTHONPATH=src` fallback above).
4. **No modal dialog is open in Fusion** — an open dialog (e.g. *Attributes of
   Rn*) silently blocks the bridge, so every read comes back empty.

**The loop**

1. **Read the live design.** Ask Claude — e.g. *"read the comet design and list
   the resistors with their values and package variants."* Claude reports
   designators, values, and the **exact package variant names** on each deviceset
   (literal library names, often with a leading hyphen — `-0402`, not `0402`).
2. **Find a replacement** for the part that needs changing — Claude discovers
   candidates and verifies them live (`hendley alternates`, with `hendley detail` to
   anchor on the original). See [Finding a replacement part](#finding-a-replacement-part).
3. **Decide the swap** with Claude — weigh inventory / price / spec margin /
   package; Claude surfaces electrical caveats (e.g. a 0603→0402 shrink lowers the
   power rating). The decision is yours.
4. **Generate the `.scr`.** Claude writes a `swaps.json` and runs
   `hendley scr swaps.json -o changes.scr`. The script carries the **package
   variant and the attributes** (`LCSC`/`MPN`/`MANUFACTURER`/…). See
   [The `.scr` file format](#the-scr-file-format).
5. **Apply it in Fusion.** Two ways:
   - **Manual** — *File > Execute Script* (or the
     `neu_dev.run_text_command("SCRIPT …")` line in the text-command Py mode), then
     set anything the script doesn't carry — **notably a changed schematic value**
     (e.g. 220 Ω → 330 Ω) — in Fusion as well.
   - **Over the HTTP bridge** — have Claude fire it with
     `executeTextCommand('Electron.run "script C:\\tmp\\changes.scr"')` via the
     `fusion_mcp_execute` tool (called over HTTP). The same channel sets the value
     (`Electron.run "VALUE R6 330"`), so the whole change is one scripted stream.
     `Electron.run` returns nothing, so Claude verifies by re-reading; changes are
     **unsaved** until you save in Fusion. (Details:
     [`docs/fusion-notes.md`](fusion-notes.md) → "The WRITE path".)
6. **Verify** — ask Claude to re-read the design and confirm each part landed on
   the new package, attributes, and value.
7. **Reconcile** — update your BOM record (the parts JSON) so it points at the new
   code; a later `hendley stock` then reflects reality. Save in Fusion.

**Gotchas**

- Close any modal dialog in Fusion before a read — an open dialog returns empty.
- The Fusion Electronics **object** API is read-only, but the EAGLE command line
  is reachable via `Electron.run` (step 5) — so Claude *can* apply the `.scr` over
  the bridge, or you run it manually. A **bare** `executeTextCommand("script …")`
  does **not** work (hits Fusion's core channel); it must be wrapped in
  `Electron.run "…"`.
- A `.scr` **stops at the first failing command**, which can leave a partial
  change — sanity-check variant names before a big batch, and keep the run undoable.

`docs/comet-0402-migration.md` is one worked example of this workflow (a batch of
resistors moved 0603 → 0402) — a useful template for the decision worksheet.

### Finding a replacement part

The official JLCPCB API **cannot search** — it only verifies codes you already
hold (`getComponentDetailByCode`). So `hendley alternates` finds replacements in
two steps:

1. **Discover** candidate codes from `jlcsearch.tscircuit.com`, a third-party
   parametric index of the whole JLC catalog (one HTTP query, no catalog download).
2. **Verify** *every* returned code against the live JLC API in one batched call,
   for authoritative stock / price / parameters. jlcsearch's stock is a **stale
   cached snapshot** (observed severalfold off in both directions — a part
   listed at 1.9M was really 474k; one listed at 55k was really 252k), so the
   table is built on the live numbers, not jlcsearch's.

It deliberately **does not rank or pick** — it gathers and verifies; you (or
Claude) weigh inventory vs. price vs. spec margin vs. package. It does not
perform the full PRD ranking and approval workflow.

The app's red-panel search and the **Search Alternates** button are the
interactive form of the same two steps — discovery plus one batched live
verify — with the same division of labor: the search string is yours,
fired verbatim; judgment (normalizing footprint names, weighing candidates)
belongs to the agent and to you, never to a parser (ADR-0006).

### Design writes are explicit

The Fusion Electronics object interface is read-only, but reviewed EAGLE/Fusion
commands can be executed through Fusion's command channel.

Hendley can generate a `.scr` file containing package and attribute changes.
Execution is an explicit engineering action and is separate from automatic BOM
resolution.

### The `.scr` file format

`hendley scr` turns a table of swaps into the `.scr` you run in Fusion (loop step
5) — the write channel for package and attribute changes, ideal for batch edits
(migrating dozens of resistors to a new package, repointing parts to new JLC
codes) without clicking each part by hand.

Describe the changes in a swap JSON file (object with a `swaps` list, or a bare
list). Only `designator` is required per swap:

```json
{
  "design": "comet",
  "swaps": [
    {
      "designator": "R1",
      "package": "-0402",
      "lcsc": "C25768",
      "manufacturer": "UNI-ROYAL",
      "mpn": "0402WGF2202TCE",
      "attributes": { "DESC": "1%" }
    }
  ]
}
```

- `package` is the library **variant name** — note it is the exact name from the
  device, often with a leading hyphen (e.g. `-0402`, not `0402`). Omit it to
  change attributes only.
- `lcsc` / `manufacturer` / `mpn` are conveniences that map to the `LCSC` /
  `MANUFACTURER` / `MPN` attributes; `attributes` carries any other attribute
  (e.g. `DESC`) and overrides the conveniences.

Generate the script (offline — no credentials needed). Multiple swap files merge
into one combo script you execute once:

```bash
hendley scr swaps.json -o changes.scr
hendley scr 22k.json 10k.json 220r.json -o changes.scr   # combo
```

Each swap renders as `CHANGE PACKAGE` **before** the `ATTRIBUTE` lines (switching
the variant can reset variant-default attributes, so the values are written
afterward):

```
CHANGE PACKAGE '-0402' R1;
ATTRIBUTE R1 LCSC 'C25768';
ATTRIBUTE R1 MANUFACTURER 'UNI-ROYAL';
ATTRIBUTE R1 MPN '0402WGF2202TCE';
ATTRIBUTE R1 DESC '1%';
```

The script covers **package and attributes**. A changed **schematic value** (e.g.
220 Ω → 330 Ω) is not part of the `.scr` — it's set in Fusion when you apply the
change (loop step 5).

After execution, re-read the design and verify every change. Fusion changes
remain unsaved until the engineer saves the design.

## Python API

```python
from hendley import JLCClient

client = JLCClient()

detail = client.get_component_detail_by_code(["C2040"])
library_page = client.get_component_library_list(page_size=30)
private_inventory = client.get_private_component_library(
    current_page=1,
    page_size=30,
)
```

See the package source and API reference for the current public surface.
