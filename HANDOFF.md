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

## What just shipped

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

(Archaeology note: `43f1960`'s commit message describes the UI fixes — `S.familyTried`,
traps above the table, every-request display — but its diff touches only `claude_cli.py`.
The UI work itself landed in `94eb0a4`. All the code is present; only the log
misattributes it.)

### Generic-family hardening (`ea6b5de`, `f1615e4`)

The family path is no longer limited to what happened to appear in the catalog's capped
100-row sample. A truncated package listing is marked incomplete; a package spelling the
agent derives from the ordering table is admitted only after a narrow catalog query proves
that exact spelling. Cached LLM family reads also self-heal: if every saved package query
returns zero rows, Hendley discards that judgment and reads the family once more. A
source-qualified delete protects engineer-confirmed interpretations.

An unseen design, **`pte`**, was read through the Fusion bridge and kept as the current
generalization fixture. It contains USB bridges, smart switches, a regulator module,
RS-485, an STM32, an FPGA, a voltage reference, digital isolators, MOSFETs, diodes,
oscillators, connectors and local footprints. It exposed two generic identity failures:

- a provisional `family` and a cached `spec` could coexist, leaving the resolver to choose
  one silently; U families now stay on the bounded family path, while a successful D/Q
  spec judgment replaces (rather than accompanies) the provisional family;
- a functional label is not a family. `RS485` leaves voltage and behavior unstated; its
  0.75-confidence read now fails closed instead of presenting 3.3 V and 5 V parts together.

The first blind reads succeeded for `FT232RL`, `TPS4H160A`, and `R-78E3.3-1.0`. The FPGA
`10M08SCE144C8G` failed honestly: the local 145-pad footprint and the catalog's
`LQFP-144-EP(20x20)` word could not be reconciled confidently. Do not paper over that
with a package alias until the geometry is proved.

Checkbox-only approval of a backup part is now immediate. The search row was already
live-verified before it could be checked, so its stock/price snapshot is recorded and
shown in the upper AVL table without another JLC call or a whole-design re-resolution.
Actions that can change what mounts (radio pick, removal, unresolved line) still resolve;
the resolve response carries its already-verified AVL snapshot so the page never verifies
the same list twice.

Family lines with no approved part now say **`unpicked`** in both the rail and detail
badge. They use the warning state, not the red stock-short state; no inventory conclusion
has been made yet.

Repository knowledge is now available to the judgments that need it. `judgment: family`
selects `ics-by-family-mpn.md` for `read_family`, independent of the original board's five
catalog classes, and designator-scoped notes reach local part interpretation. The first
new note is `zener-diodes.md`: `VZ10`, `10V0`, and `10.0` are recorded as this shop's
10 V Zener conventions on a diode line, proposed as a spec and confirmed once—never
searched literally as a manufacturer family.

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

Always also: `.venv/bin/python -m pytest -q` (**274 pass**) and `ruff check src tests`.

The documented Playwright environment was absent on 2026-07-14
(`~/.venvs/pw/bin/python` did not exist). Recreate it before claiming browser-level
coverage; the API suite cannot prove the checkbox event calls the intended fast path.

---

## THE WORK, in the order I would do it

### 1. Validate the local-value path on `D1` / `VZ10`

`D1`'s VALUE is `VZ10` — **your library's name for a 10 V zener**, not a part number. The
old family path searched it by name and found nothing sensible. The generic identity fix
now permits a high-confidence D/Q spec judgment to **replace** the provisional family,
which is the correct mechanism; this has unit coverage and worked from cache for `3V3`
and `10V0` on `pte`, but `VZ10` itself has not been re-read live since the fix.

This is the other shape of the same problem, and it needs the **spec** path, not the
family path: `kind=zener, value=10V, package=SOD-323` → the `diodes` category has real
columns to sieve on. There is prior art: see the `vz10-discovery-diagnosis` memory and
`requirements/specs.py` (`infer_spec` — deterministic for R/C/L only; **do not grow its
regexes**, ambiguity belongs to the AI tier).

The judgment "VZ10 means a 10 V zener" is a **shop convention**, so it belongs where the
other conventions live: the agent reads it, the engineer confirms it once, and it is
cached in `interpretations` for ever. Do not hardcode `VZ10`.

The Zener knowledge note and prompt routing are now implemented and tested without a live
agent. The remaining work is an actual Refresh/search on the original design: confirm the
first interpretation, inspect the query and candidates, and ensure the catalog labels the
chosen rows `Zener Diodes`. Do not call the path finished from prompt tests alone.

### 2. Decide: should a trap part be *markable* in the table?

Right now `PCF8574AT` (C86832 — the wrong I²C address) is still an **orderable row** you
could pick, with the trap warning above the table. **I deliberately did not auto-exclude
trap parts**, because the `PCF8574T` episode proved the agent's part-name claims can be
wrong, and auto-excluding would have silently killed the genuine NXP part. Warn loudly,
let the human decide. **Ask Craig** before changing this — it is a judgment call, not a bug.

### 3. The CLI does not know about families

`hendley pcba` / `hendley resolve` treat family lines as no-code and block the BOM. That is
**honest** (it will not ship a bad order) and the app is the primary interface (ADR-0003/4),
so it may be fine for ever. But it means the one-prompt `jlc` path cannot complete this
design until the U parts are picked in the app. Confirm with Craig whether that is
acceptable or whether the queue should learn `line.family`.

### 4. `docs/parts/` notes still unwritten

MOSFETs, and the remaining diode families (small-signal / Schottky / avalanche-TVS —
which the catalog's `secondTypeName` distinguishes and the index cannot). The Zener note
is written; extend it only with catalog fields measured from real candidates. **Only write
what you measured.**

### 5. Validate on a third unseen design

Do not tune against it before recording the first pass. Prefer analog/power/sensor content
and different custom libraries. Measure: cleanly classified, safely unresolved, wrong
candidate offered, and source/prompt changes required. The target is useful failure with
no code change, not an artificially green board.

---

## Live supply risk, unrelated to any of the above

**U7/U9 (`LTV-352T`, C10800): 1,295 live units, 1,000 needed for a 500-board run, single
sourced.** The same-package neighbours (`EL357N`, `LTV-357T`) are **3–5× lower CTR**
(200–400 % vs 1000–5000 %) — same SOP-4 land, same pinout, **not drop-ins** without
rechecking the LED drive current. Craig knows. It has not been actioned.
