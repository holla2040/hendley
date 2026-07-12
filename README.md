# Hendley

<img src="image/hendley.png" alt="Hendley — James Garner as Hendley, 'the Scrounger', in The Great Escape" width="160" align="right">

Hendley is a Python tool for querying JLCPCB/LCSC component data and integrating that information with Autodesk Fusion Electronics.

Today, Hendley can inspect live JLC component details, check BOM stock, discover and verify alternates, read a live Fusion Electronics design, and generate explicit Fusion migration scripts. The project is evolving toward an AI-assisted, provider-independent BOM Resolver that transforms engineering requirements into an approved manufacturing BOM.

> Hendley is named after James Garner's character in *The Great Escape*: "the Scrounger" who finds what the team needs.

## Project Status

### Available today

- JLCPCB OpenAPI authentication and component queries
- component detail, stock, pricing, parameters, and datasheet information
- assembly-library and private-inventory queries
- BOM stock checking
- alternate discovery with live JLC verification
- live Fusion Electronics reads over Fusion's local HTTP interface
- **JLCPCB PCBA order-file generation** (`hendley pcba`) — `bom.csv` + `cpl.csv`
  from the live Fusion design, rotation-corrected, DNP-aware, and stock-checked
  (see [Generating JLCPCB order files](#generating-jlcpcb-order-files-hendley-pcba))
- **the house-parts knowledge base** (`hendley db`) — House Parts with
  deliberately ranked, audited Part Choices (the AVL), provider-neutral
  identity, SQLite at `~/.hendley/parts.db`
- **spec-driven resolution** (`hendley resolve`) — rank-walk the AVL against
  live stock at the order's board count, silent substitution down the rank,
  one batched approval queue (discovered + verified + ranked candidates) for
  the gaps
- **gated BOM emission** (`hendley bom`) — the upload CSV plus an immutable
  release snapshot; error checks block the emit (JLCPCB and PCBWay formats)
- **the Hendley app** (`hendley app`) — the single-page order workbench over
  all of the above (see [The app](#the-app-hendley-app))
- generation of Fusion `.scr` migration scripts
- optional, explicit execution of reviewed scripts through Fusion's command channel

### Target product

The target product is described in [`docs/PRD.md`](docs/PRD.md). It adds:

- a provider-independent Requirements BOM
- deterministic constraint validation
- ranked and explainable candidate recommendations
- engineer review and approval
- reusable project and user knowledge
- JLCPCB and PCBWay Provider Strategies
- provider-specific Manufacturing BOM adapters

The core pipeline (ingestion → canonical Requirements BOM → constraint
filtering → deliberate-AVL resolution with computed candidate ranking →
engineer approval → provider adapters → gated output) is implemented, with
JLCPCB as the live provider and PCBWay as the provider-independence proof.
Still open (see `docs/adr/` and `docs/architecture.md` §14): user-editable
ranking configuration, the AI assistance layer, additional ECAD importers,
and organization-level knowledge scopes.

## Why Hendley

For generic components, the circuit usually requires engineering characteristics rather than one permanently fixed purchasable part.

For example:

```text
22 kΩ
±1%
0603
minimum 100 mW
```

The specific JLC/LCSC part depends on current stock, provider eligibility, lifecycle, cost, and build quantity. Manually searching and maintaining those identifiers can consume hours after the design is complete.

Hendley's long-term goal is to keep engineering intent stable and resolve procurement choices later:

```text
Fusion / ECAD design
        |
        v
Requirements BOM
        |
        v
Resolver + Provider Strategy
        |
        v
Engineer approval
        |
        v
Manufacturing BOM
```

> **Free engineers to do design.**

## Documentation

Read the design documents in this order:

1. [`docs/vision.md`](docs/vision.md) — why the project exists
2. [`docs/architecture-principles.md`](docs/architecture-principles.md) — rules the implementation must preserve
3. [`docs/PRD.md`](docs/PRD.md) — product scope, workflows, and acceptance criteria
4. [`docs/architecture.md`](docs/architecture.md) — target modules, interfaces, and migration from the current codebase

Additional repository documentation:

- [`docs/api-reference.md`](docs/api-reference.md) — reverse-engineered JLCPCB API contract
- [`docs/fusion-notes.md`](docs/fusion-notes.md) — Fusion HTTP integration details

## Install

Requires Python 3.10 or later.

```bash
git clone git@github.com:holla2040/hendley.git
cd hendley
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

Development dependencies:

```bash
pip install -e ".[dev]"
```

The core package depends on `requests`.

If the installed command is unavailable, run Hendley from the repository:

```bash
PYTHONPATH=src python -m hendley.cli ping
```

## Configure JLCPCB Credentials

Hendley reads JLCPCB OpenAPI credentials from a git-ignored `.keys` file.

```text
JLCAPI:
    AppID:     <your-app-id>
    Accesskey: <your-access-key>
    SecretKey: <your-secret-key>
```

Credential lookup order:

1. `--keys PATH`
2. `HENDLEY_KEYS`
3. `.keys` discovered by walking up from the current directory

Optional endpoint override:

```text
HENDLEY_ENDPOINT
```

Do not commit `.keys`, PEM files, private keys, or secrets.

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
them to `jq`/`python3` to parse. Only **`stock`** and **`alternates`** accept
`--json`; without it they print a human-readable report. `ping` prints a status
line; `scr` prints (or writes with `-o`) the `.scr` script; `pcba` writes its two
CSVs and prints the stock report. A command's flags are exactly what
`hendley <cmd> --help` lists — don't assume a flag exists because another
command has it.

## The app (`hendley app`)

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
  search, dashed = DNP (sunk to the bottom). On page load the app
  repopulates from the last read (`~/.hendley/design-cache.json`) with every
  correction re-applied — no Fusion round-trip until you want one.
- **Design Overview** (nothing selected): one row per part — LCSC code
  (linked to its product page), stock/need, unit and order cost, JLC
  Basic/Extended class — with the per-board parts cost on the title line.
- **Click a component** for its detail panel: one table, radio column on the
  left. **The checked radio is what mounts for this order.** Your part leads
  the table (no radio when it can't cover the order); live-verified
  alternates follow with manufacturer, package, class, and a `why` column
  carrying only judgments the other columns don't (prior approvals,
  shortfall warnings). Sort by stock or price from the headers.
- **Pick semantics**: the *first* pick for a spec with nothing approved is
  the choosing — recorded permanently as the AVL rank 1 ("picked in the
  app", with a **stop using this part** undo). A pick that *overrides* an
  existing approved part is **this order only** ("undo — use the automatic
  pick"); the preferred part returns when its stock does.
- **Searches are yours**: discovery auto-runs only where the query is
  deterministic (R/C value params, chip packages). Everything else shows a
  search box seeded from the spec — *you* fire it, verbatim, and results
  split honestly: package-confirmed on top (the agent judges each library
  footprint to its catalog package — `C-0603` → `0603` — cached forever),
  with "N other packages" and "M can't cover the order" expandable below.
- **Schematic-pinned parts** (an `LCSC` attribute) are verified as-is, with
  an **explore alternates** button for order-only substitutes; an MPN-only
  attribute is called out honestly (JLC can't verify by MPN).
- **Placement (CPL)** in each panel edits `data/cpl-rotations.json` — set a
  rotation correction once (keyed by footprint/LCSC, never designator) and
  every later export applies it.
- **Export BOM/CPL** in the title bar stays disabled until every row is
  green, then writes `bom.csv` + `cpl.csv` (+ the release snapshot) — in
  Chromium browsers it first opens the standard folder picker and saves
  copies where you choose (Brave ships the picker disabled:
  `brave://flags/#file-system-access-api`).
- **Nothing is lost to a reload**: picks, searches, and the board quantity
  write through to a server-side draft (`~/.hendley/draft.json`, per
  design), reconciled by line identity on the next load and cleared by a
  clean export.

Under WSL2 the Windows browser reaches the WSL loopback directly — no
port-forwarding needed for the app itself. The app starts fine without JLC
credentials; live actions report the missing `.keys` when first used.

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
   [Fusion Electronics Integration](#fusion-electronics-integration)).
2. Under WSL2, the port forward is up (same section,
   [networking note](#reaching-fusion-from-wsl2-networking-note)).
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
     [Fusion Electronics Integration](#fusion-electronics-integration)
     and `docs/fusion-notes.md` → "The WRITE path".)
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
   cached snapshot** (seen off by 30–600× in both directions), so the table is
   built on the live numbers, not jlcsearch's.

It deliberately **does not rank or pick** — it gathers and verifies; you (or
Claude) weigh inventory vs. price vs. spec margin vs. package. It does not
perform the full PRD ranking and approval workflow.

The app's red-panel search and the **explore alternates** button are the
interactive form of the same two steps — discovery plus one batched live
verify — with the same division of labor: the search string is yours,
fired verbatim; judgment (normalizing footprint names, weighing candidates)
belongs to the agent and to you, never to a parser (ADR-0006).

## Fusion Electronics Integration

Hendley communicates with Fusion's local Electronics interface over HTTP. No separate MCP client library is required by Hendley.

Fusion must be running with an Electronics document open and its local server enabled — the **Preferences > General > API > Fusion MCP Server** toggle (this Autodesk setting is the *only* thing here named "MCP"; it just publishes the HTTP endpoint Hendley talks to). See [`docs/fusion-notes.md`](docs/fusion-notes.md) for the verified handshake, read operations, and command execution details.

### Reaching Fusion from WSL2 (networking note)

If you run Hendley on the same Windows machine as Fusion, `http://127.0.0.1:27182`
just works. If you run it under **WSL2**, Windows loopback isn't reachable across
the NAT boundary, so forward the port on the **Windows** side (elevated
PowerShell).

> ⚠️ **Use the WSL gateway IP as `listenaddress`, NOT `0.0.0.0`.** A `0.0.0.0`
> listener on `27182` sits in front of the *same* loopback port Fusion's server
> and the Claude Desktop "Autodesk Fusion" connector use, and hijacks their
> `127.0.0.1:27182` traffic — Fusion appears to "connect then close
> unexpectedly" and **Claude Desktop stops connecting**. Bind the WSL-facing
> gateway address specifically so loopback is never intercepted.

First get the WSL→Windows gateway IP **from inside WSL** (it is also the address
WSL uses to reach Windows):

```bash
ip route | grep default | awk '{print $3}'   # e.g. 172.17.64.1
```

Then, on Windows (elevated), forward that address only — substitute your gateway
IP for `172.17.64.1`:

```powershell
netsh interface portproxy add v4tov4 listenaddress=172.17.64.1 listenport=27182 connectaddress=127.0.0.1 connectport=27182
```

From WSL, reach Fusion at `http://172.17.64.1:27182/mcp`. The gateway IP can
change across WSL restarts — re-check it with the `ip route` line above and
re-add the rule if Fusion becomes unreachable.

**Health check / troubleshooting.** On Windows, `curl http://127.0.0.1:27182/mcp`
should return an instant JSON error when Fusion's server is healthy —
`{"error": "Not Found"}` on older builds, `{"error": "Server does not offer an
SSE stream at this endpoint"}` on newer ones (observed 2026-07-10). Either body
means healthy; only a hang or "connection closed unexpectedly" is bad. (In
PowerShell, `curl` is `Invoke-WebRequest` and paints non-2xx responses as red
exceptions — read the body, not the color.)
If it (or Claude Desktop) "closes the connection unexpectedly," a bad `0.0.0.0`
forward is almost certainly hijacking loopback — delete it and the symptom
clears:

```powershell
netsh interface portproxy show all     # look for a 0.0.0.0 ... 27182 entry
netsh interface portproxy delete v4tov4 listenaddress=0.0.0.0 listenport=27182
```

Remove the (correct) gateway forward when you're done with:

```powershell
netsh interface portproxy delete v4tov4 listenaddress=172.17.64.1 listenport=27182
```

### Design writes are explicit

The Fusion Electronics object interface is read-only, but reviewed EAGLE/Fusion commands can be executed through Fusion's command channel.

Hendley can generate a `.scr` file containing package and attribute changes. Execution is an explicit engineering action and is separate from automatic BOM resolution.

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

After execution, re-read the design and verify every change. Fusion changes remain unsaved until the engineer saves the design.

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

## Architecture Boundaries

The target resolver keeps these responsibilities separate:

- Fusion and other ECAD integrations capture engineering requirements.
- Data-source connectors retrieve sourced component facts.
- The Resolver Core applies deterministic constraints.
- Provider Strategies express sourcing policy.
- Ranking orders valid candidates.
- AI explains and assists with ambiguity.
- Engineers approve.
- Provider Adapters generate manufacturing files.
- Fusion migration tools remain explicit ancillary utilities.

## Roadmap

The PRD/architecture v1 pipeline is implemented (2026-07-10): canonical
Requirements BOM schema, live Fusion ingestion, deterministic constraints,
JLCPCB strategy + adapter, candidate ranking with explanations, approval
persistence (the audited AVL), the PCBWay strategy/adapter provider-
independence proof, and the app as the primary interface. The AI
interpretation tier (`ai/` — ad-hoc values and footprint names judged via
`claude -p`, cached forever, ADR-0005/0006) and the single-page app
(2026-07-12 redesign) followed.

Next, from the PRD and the open decisions in `docs/architecture.md` §14:

1. User-editable ranking configuration (weights are hardcoded; ADR when it hurts)
2. Additional ECAD importers (generic CSV, KiCad)
3. Lifecycle data (needs a source beyond the JLC API)
4. Organization-level knowledge scopes

PCBA order placement and website-loop automation are useful future ideas but are outside the Version 1 resolver scope.

> **Order files are already covered.** `hendley pcba` generates the BOM + CPL
> directly from the live design (rotation-corrected, stock-checked) — see
> [Generating JLCPCB order files](#generating-jlcpcb-order-files-hendley-pcba).
> Driving JLC's own upload/validation through the order API remains out of scope.

## Security

- Never commit `.keys`, private keys, PEM files, or provider credentials.
- External AI use must be explicit and configurable.
- Do not log secrets.
- Use the minimum provider permissions required.
- Treat BOM and design data as potentially proprietary.

## License

The repository currently states that it is **Proprietary**.

The product vision calls for an open and community-extensible architecture, but the repository must not be described as open source until an explicit license change is made.
