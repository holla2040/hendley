# HANDOFF — current operational state

Updated 2026-07-14. Read `CLAUDE.md` first, especially the glossary. This document is a
dashboard, not a development diary: current behavior, known limits, expensive facts,
remaining work, and decisions that require Craig.

## Standing rules

1. **Hendley reads the Fusion design; it never writes to it.** Do not use `.scr`,
   `Electron.run`, or `fusion_mcp_execute` against a design. Recommend; Craig edits;
   Hendley re-reads.
2. **Never commit or push unless Craig explicitly asks.** Stage by path; never use
   `git add -A` in a mixed worktree.
3. **Judgment belongs to the agent and engineer; Python compares.** The bounded
   `family + package` catalog query is the one authorized composition exception.
4. **Never invent a catalog or electrical fact.** Repository knowledge must be measured,
   sourced, or explicitly identified as a shop convention awaiting confirmation.

## Current verified capabilities

- Reads the active Fusion schematic and board through `FusionBridge`; Refresh caches the
  full intake at `~/.hendley/design-cache.json`.
- Keeps exact provider codes, manufacturer MPNs, incomplete families, specifications,
  local labels, DNP parts, and unresolved parts distinct.
- Resolves approved part lists against live JLC stock and exports gated BOM/CPL files.
- Searches IC families as `family + catalog package`, including multiple catalog words
  for one physical land, and proves package fit after discovery.
- Detects a capped 100-row package sample, narrowly confirms package spellings missing
  from that sample, and self-heals cached LLM family reads that produce zero rows.
- Fails closed on low-confidence functional labels such as `RS485` instead of presenting
  electrically incompatible parts as equivalents.
- Shows family lines with no approved choice as **unpicked**, not **short**.
- Records checkbox-only backup approval immediately from the already-live search result;
  it does not re-query JLC or re-resolve a design when the mounted part cannot change.
- Reads durable guidance from `docs/parts/`. `judgment: family` reaches family reads;
  designator-scoped notes reach local-value interpretation.
- Knows the shop's diode aliases `VZ10`, `10V0`, and `10.0` as proposed 10 V Zener specs,
  subject to first-time engineer confirmation; it never searches them as literal families.
- Live-validated `VZ10` on the original Fusion design: D1 becomes a 10 V SOD-323 Zener
  spec, and the bounded search proves C353563 (`BZT52C10S`) from catalog parameters;
  its catalog class is `Zener Diodes`.
- Treats family selection as app-only. `hendley pcba`, including `--no-verify`, refuses
  to write CSVs while a populated family line has no exact approved part.
- Test baseline: **276 passing**, plus `ruff check src tests` and `git diff --check`.

## Known limitations

- A custom FPGA footprint in the unseen `pte` design could not be proved equivalent to
  catalog package `LQFP-144-EP(20x20)`. Hendley correctly refused it; no alias is approved.
- The documented Playwright environment `~/.venvs/pw` is absent. API tests cannot prove
  that every browser event reaches its intended endpoint.
- Knowledge notes remain unwritten for MOSFETs, small-signal diodes, Schottky diodes, and
  avalanche/TVS devices.
- Generalization has been exercised on the original board and unseen `pte`; a third design
  must remain unseen until its first-pass results are recorded.

## Remaining work, in order

1. **Restore browser coverage.** Recreate the Playwright environment, run
   `scripts/ui_check.py` and `--live`, and inspect `/tmp/hendley-ui/` screenshots.
2. **Write measured part notes.** MOSFET, small-signal diode, Schottky, TVS/avalanche.
   Measure real catalog records and index fill behavior before writing claims.
3. **Run a third unseen-design audit.** Record the first pass before changing prompts or
   code. The representative multi-block fixture is specified in `README.md`; build it
   naturally rather than adding metadata to make Hendley happy. Classify each result as
   correct, safely unresolved, wrong candidate, or required local knowledge.
4. **Resolve the FPGA land only from geometry.** Compare measured footprint pitch/body/
   exposed-pad geometry to the manufacturer package drawing and catalog package. Never
   approve a name-only alias.

## Decisions Craig must make

- **Trap rows:** keep functionally warned same-land parts selectable, or prohibit marking
  them? Current behavior warns but permits selection because the agent has previously
  slandered a valid part; automatic exclusion can silently remove the right answer.
- **Local conventions:** decide whether shop aliases should remain global to this parts DB
  or eventually be scoped by Fusion library/organization.

## Expensive measured facts — do not re-measure casually

- `components` honors `package=` and `is_basic=`; it silently ignores `stock_min`.
- Index listings hard-cap at 100 rows; `limit=500` changes nothing. Measured on `1N4148`,
  `LM358`, and `AMS1117`.
- Index stock is advisory and can be wrong by orders of magnitude. Always verify live.
- A library footprint name is not catalog vocabulary: `SOIC-4` may be catalog `MBS`;
  `SOP04` may be `SOP-4-2.54mm`. A wrong word returns zero rows indistinguishably from
  true non-stock.
- One land may have several catalog spellings holding different parts (`SOIC-8`, `SOP-8`).
  Body width remains physical identity: 150-mil and 300-mil SOIC are different lands.
- Catalog `secondTypeName` is the part class. Index `subcategory`, `is_schottky`, and
  `is_polarized` have contradicted real catalog parts and must not prove class.
- JLC publishes nominal Zener voltage as `Zener Voltage(Nom)`. A live SOD-323 package
  sample contained 30 Zeners and one proved 10 V row: C353563 (`BZT52C10S`), catalog
  class `Zener Diodes`. The index sample was capped at 100 and mixed six diode classes.
- A trap is functional—address, voltage, CTR, register model, temperature grade—not a
  package claim. The catalog proves package and outranks the agent.
- Fusion's `BOARD;` context switch is effectively one-way per session. Ask Craig to front
  the schematic, wait for confirmation, then spend the read on a full Refresh and cache it.
- `MP`/`MF` are stale import metadata, never identity. Read `MPN`; exact JLC identity is
  `LCSC`/providerRefs.

## Live supply risk

Original-board `LTV-352T` C10800 was measured at 1,295 live units against 1,000 required
for 500 boards, single-sourced. Same-land `EL357N`/`LTV-357T` have materially lower CTR and
are not drop-ins without LED-current review. Craig knows; no design action is recorded.
