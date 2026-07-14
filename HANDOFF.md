# HANDOFF — where Hendley stands, and what to do next

Written 2026-07-14 for whoever picks this up. Read `CLAUDE.md` first (especially the
**Glossary** — six words, and they are load-bearing). This file is the operational
state: what just shipped, what is broken, what to do, and the things that will waste
your day if nobody tells you.

---

## Standing rules — break these and you break the project

1. **⛔ Hendley READS the design. It NEVER writes to it.** No `.scr`, no `hendley scr`,
   no `Electron.run`, no `fusion_mcp_execute` against a design. The write path still
   *works*, which is exactly why the prohibition is written down next to it. When a part
   must change you **recommend** it; Craig edits Fusion; you re-read. (ADR — see CLAUDE.md.)
2. **Never commit or push unless Craig explicitly asks.** Stage by path; never `git add -A`.
3. **Judgment belongs to the agent and the engineer; Python compares** (ADR-0006). The
   ONE authorized exception is the family query (ADR-0008), and it is bounded to a single
   query shape.
4. **Never invent a fact.** Every claim in `docs/parts/` and `UNPROVABLE_COLUMNS` was
   MEASURED. An unmeasured "fact" is worse than silence, because the agent believes it.

---

## What just shipped (commits `94eb0a4`, `43f1960`, `4b65959`)

**A family is not a part** (ADR-0008 — read it, it is short). A designer types `ULN2003`
into the schematic VALUE. That is a **family**, not something you can order: it ships in
five packages and the **footprint on the board** decides which one may go on it.

The pipeline: **family + footprint → package → the parts.** Open a U part in the app and
it has already searched itself; the traps are shown in red above the table.

Working live on Craig's design: `U1 ULN2003`, `U2 PCF8574`, `U4 MB10S`, `U6 SP3485`,
`U7+U9 LTV-352T`. All resolve, all show traps, picking one flips the rail green.

The bug it fixed was ugly: a family in the **MPN attribute** used to **PIN** the line —
Hendley treated `ULN2003` as an exact orderable part, never sieved it, and shipped it to
the resolver as if you could buy one.

---

## DO NOT RE-MEASURE THESE. They cost hours.

- **`components` DOES honour `package=` and `is_basic=`.** It **silently ignores
  `stock_min`** (999999999 → all rows).
- **The index caps a listing at a hard 100 rows.** `limit=500` changes nothing. `1N4148`,
  `LM358`, `AMS1117` all return exactly 100. Never widen a net to a bare family name.
- **The index's `stock` is a stale snapshot** — `LTV-352T` read 128,222 there and **1,295
  live**. Always verify live.
- **NEVER GUESS THE PACKAGE.** The library says `SOIC-4`; the catalog says `MBS`. The
  library says `SOP04`; the catalog says `SOP-4-2.54mm`. A wrong package returns **zero
  rows while looking exactly like "JLC doesn't stock it"**. Ask the catalog for its own
  package list (search the family with no package) and choose from that.
- **A land is a SET of the catalog's words.** `SOIC-8` and `SOP-8` are the same 3.9 mm
  body and hold **different parts** — the Basic, 327k-stock SP3485 is only under `SOIC-8`.
  U2's land has **four** spellings. A different *body* is still a different *land*.
- **The CLASS is a label. Never a query, never a sieve term.** `search=optocoupler` →
  100 rows topped by LEDs. And the **index's `subcategory` lies**: it files C2886577 — an
  MB10S **mounted on Craig's board** — as `Diodes - General Purpose`, while the catalog
  correctly says `Bridge Rectifiers`. The catalog is consistent; the index is not.
- **The agent can slander a good part.** It claimed `PCF8574T` was "the narrow 3.9 mm
  body" when the catalog lists that very part as `SOIC-16-300mil`. A **trap is FUNCTION
  ONLY** (address, voltage, gain, temp grade, register model) — never about the package,
  because the catalog proves the package exactly and outranks the agent.
- **`MP`/`MF` are NEVER an identity.** `MP` said `MB6S` (600 V) on a part whose VALUE said
  `MB10S` (1000 V). Stale SnapEDA imports. Read `MPN` and only `MPN`.

---

## How to work WITHOUT Fusion (do this)

**Fusion's `BOARD;` switch is one-way.** You typically get **ONE** live read per session,
then the engine is on the board and every schematic read comes back empty. So:

- The app writes the design to **`~/.hendley/design-cache.json`** on every Refresh. It is
  there now, with all the new fields (`family`, `footprintHeadline`). **Work from it.**
- Before any live read: **ask Craig to front the schematic and wait for his confirmation.**
  Then spend the read on a full Refresh (which caches everything).

## How to test the UI (do this too)

`pytest` tests the JSON API. **It cannot tell you the page never CALLS the API** — which
is exactly what happened: the family engine was finished, tested, and completely
unreachable. Two more bugs only appeared in a browser.

```bash
~/.venvs/pw/bin/python scripts/ui_check.py          # fake backend, ~20s, exits 0/1
~/.venvs/pw/bin/python scripts/ui_check.py --live   # real catalog + agent, from cache
```
Screenshots land in `/tmp/hendley-ui/`. **Look at them.** A page that renders wrong raises
no exception.

Always also: `PYTHONPATH=src python3 -m pytest -q` (267 pass) and `ruff check src tests`.

---

## THE WORK, in the order I would do it

### 1. `D1` / `VZ10` — a value, not a family (the real gap, and it is on the board)

`D1`'s VALUE is `VZ10` — **your library's name for a 10 V zener**, not a part number. The
family path searches it by name, matches nothing sensible (it finds *electrolytic
capacitors*), and correctly refuses: *"can't tell which package D-SOD323 is."* It fails
safe and honest, but it does not resolve.

This is the other shape of the same problem, and it needs the **spec** path, not the
family path: `kind=zener, value=10V, package=SOD-323` → the `diodes` category has real
columns to sieve on. There is prior art: see the `vz10-discovery-diagnosis` memory and
`requirements/specs.py` (`infer_spec` — deterministic for R/C/L only; **do not grow its
regexes**, ambiguity belongs to the AI tier).

The judgment "VZ10 means a 10 V zener" is a **shop convention**, so it belongs where the
other conventions live: the agent reads it, the engineer confirms it once, and it is
cached in `interpretations` for ever. Do not hardcode `VZ10`.

### 2. The rail badge lies on a family line

U1 and U2 show red **`short`**. They are not short of stock — they are **unpicked**. The
panel already says the right thing ("no approved part for this yet — search below and pick
one"); the rail does not. A family line needs its own state. See `ui.py` (the rail
component's state classes) and `resolution.lines[i].reason`.

### 3. Decide: should a trap part be *markable* in the table?

Right now `PCF8574AT` (C86832 — the wrong I²C address) is still an **orderable row** you
could pick, with the trap warning above the table. **I deliberately did not auto-exclude
trap parts**, because the `PCF8574T` episode proved the agent's part-name claims can be
wrong, and auto-excluding would have silently killed the genuine NXP part. Warn loudly,
let the human decide. **Ask Craig** before changing this — it is a judgment call, not a bug.

### 4. The CLI does not know about families

`hendley pcba` / `hendley resolve` treat family lines as no-code and block the BOM. That is
**honest** (it will not ship a bad order) and the app is the primary interface (ADR-0003/4),
so it may be fine for ever. But it means the one-prompt `jlc` path cannot complete this
design until the U parts are picked in the app. Confirm with Craig whether that is
acceptable or whether the queue should learn `line.family`.

### 5. `docs/parts/` notes still unwritten

MOSFETs, and the diode families (small-signal / Schottky / zener / avalanche — which the
catalog's `secondTypeName` distinguishes and the index cannot). Note (1) above will teach
you most of the diode note. **Only write what you measured.**

---

## Live supply risk, unrelated to any of the above

**U7/U9 (`LTV-352T`, C10800): 1,295 live units, 1,000 needed for a 500-board run, single
sourced.** The same-package neighbours (`EL357N`, `LTV-357T`) are **3–5× lower CTR**
(200–400 % vs 1000–5000 %) — same SOP-4 land, same pinout, **not drop-ins** without
rechecking the LED drive current. Craig knows. It has not been actioned.
