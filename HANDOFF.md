# HANDOFF — current operational state

## Design-independent search history (schema v5)

Validated mounted/alternate selections preserve the canonical specification and
search intent across designs. Exact stable Fusion identities attach the existing
House Part AVL during intake; the resolver live-verifies it and automatically
uses the first stocked approved choice or alternate. A fresh proved discovery
search still runs on open. Weaker identities are suggestions. Forget disables
reuse and retains evidence; cached candidates and stock are never replayed.

Updated 2026-07-16. Read `CLAUDE.md` first, especially the glossary. This document is a
dashboard, not a development diary: current behavior, known limits, expensive facts,
remaining work, and decisions that require Craig.

## Standing rules

1. **Hendley never changes electrical/design content in Fusion.** Read-only
   `Electron.run` context, display, window, and image-export commands are part
   of intake. Recommend content changes; Craig edits; Hendley re-reads.
2. **Never commit or push unless Craig explicitly asks.** Stage by path; never use
   `git add -A` in a mixed worktree.
3. **Judgment belongs to the agent and engineer; Python compares.** The bounded
   `family + package` catalog query is the one authorized composition exception.
4. **Never invent a catalog or electrical fact.** Repository knowledge must be measured,
   sourced, or explicitly identified as a shop convention awaiting confirmation.

## Current verified capabilities

- Reads the active Fusion schematic and board through `FusionBridge`; Refresh caches the
  full intake at `~/.hendley/design-cache.json`.
- Refresh launches no agent processes. It captures structured data and local
  visual evidence. Opening an uncached red/yellow part performs one lazy reading
  and caches its full executable proof plan; visual cache hydration deliberately
  keeps the row lazy so the plan is not reduced to a compact SpecKey.
- Codex is the default interpretation backend (`codex exec --ephemeral` in a
  read-only sandbox). `HENDLEY_INTERPRETER=claude` retains the former backend.
- Keeps exact provider codes, manufacturer MPNs, incomplete families, specifications,
  local labels, DNP parts, and unresolved parts distinct.
- Resolves approved part lists against live JLC stock and exports gated BOM/CPL files.
- Searches IC families and ordinary plans with one narrow request per exact
  catalog package spelling for a physical land, unions/deduplicates them, and
  proves every candidate against the full live package set.
- Detects a capped 100-row package sample, narrowly confirms package spellings missing
  from that sample, and self-heals cached LLM family reads that produce zero rows.
- Fails closed on low-confidence functional labels such as `RS485` instead of presenting
  electrically incompatible parts as equivalents.
- Shows family lines with no approved choice as **unpicked**, not **short**.
- Records checkbox-only backup approval immediately from the already-live search result;
  it does not re-query JLC or re-resolve a design when the mounted part cannot change.
- Reads durable guidance from `docs/parts/`. `judgment: family` reaches family reads;
  designator-scoped notes reach local-value interpretation.
- Treats a `D` line as a proposed Zener spec only when its VALUE or a meaningful
  attribute value contains `Z`/`Zener`; bare voltages such as `10V0`, `500V`, and
  `1000V` do not establish diode class.
- Treats family selection as app-only. `hendley pcba`, including `--no-verify`, refuses
  to write CSVs while a populated family line has no exact approved part.
- Bare TVS voltage such as `18V TVS` is not assumed to mean `Vrwm`.
  `intent.ratingAmbiguous` keeps voltage out of the sieve and prevents automatic
  SpecKey acceptance regardless of numeric confidence.
- Test baseline: **326 passing**, plus Ruff and `git diff --check`.

## Known limitations

- Bare TVS voltages require the engineer to name the intended catalog parameter
  (`Vrwm`, breakdown, or clamp), select an exact family/part, or record a shop
  convention. This is intentional fail-closed behavior.
- A custom FPGA footprint in the unseen `pte` design could not be proved equivalent to
  catalog package `LQFP-144-EP(20x20)`. Hendley correctly refused it; no alias is approved.
- This Fusion MCP build can wedge on a board-to-schematic return. Intake orders
  all schematic capture before `BOARD`; a genuinely wedged proxy requires one
  MCP/Fusion reset.
- Generalization has been exercised on the original board and unseen `pte`; a third design
  must remain unseen until its first-pass results are recorded.

## Remaining work, in order

1. **Hands-on acceptance.** Refresh, open C3/D/Q rows, inspect live proof columns,
   select/approve parts, repeat Refresh, and confirm cached readings retain their
   plans. Verify `18V TVS` remains unresolved for voltage meaning.
2. **Run a third unseen-design audit.** Record the first pass before changing prompts or
   code. The representative multi-block fixture is specified in `README.md`; build it
   naturally rather than adding metadata to make Hendley happy. Classify each result as
   correct, safely unresolved, wrong candidate, or required local knowledge.
3. **Resolve the FPGA land only from geometry.** Compare measured footprint pitch/body/
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
- A trap is functional—address, voltage, CTR, register model, temperature grade—not a
  package claim. The catalog proves package and outranks the agent.
- `BOARD;` activates the layout engine. `EDIT .S1;` can return to schematic
  sheet 1 in a healthy session, but this MCP build may wedge its script proxy
  on that return. Refresh therefore captures all schematic evidence first and
  treats `BOARD;` as one-way for the remainder of the run. If the return fails
  with empty rows/recursive proxy errors, reset the MCP server or Fusion once.
  Enumerate `electronics.Sheet` rather than probing `EDIT .S<N>`—a missing
  number would create a new sheet. The live `hendley test` fixture was verified
  with exactly seven sheets (1–7) on 2026-07-15. Full round trip measured:
  S1 = 36 Part / 0 Element; board = 0 Part / 30 Element; returned S1 =
  36 Part / 0 Element.
- `MP`/`MF` are stale import metadata, never identity. Read `MPN`; exact JLC identity is
  `LCSC`/providerRefs.
- Unresolved-part intent is lazy and image-assisted. Refresh makes no model
  call; it exports schematic sheets, a clean board (`UNROUTED` hidden), and a
  centered 12 mm crop for each unresolved placement. Sparse sheets receive
  populated-region detail crops. A read attaches only the requested placement
  crop plus schematic details. Fusion view changes need a settle pause, stale
  files must be removed, and a fresh PNG awaited.
- Search-box edits change discovery wording but retain the visual reading's hard
  proof terms. Only the visible term editor drops them. Persisted search text is
  keyed to the visual digest so stale phrases cannot outrank a changed drawing.
- If `electronics.Schematic` is empty while parts are readable, the design name
  falls back to Fusion's active document name; never share drafts under
  `unknown`.
- Visual intent becomes executable catalog proof: live `secondTypeName` proves
  class and live parameters prove value/rating/dimensions. Index flags never
  prove class. Coarse keyword discovery may avoid the 100-row cap but remains
  advisory.
- Live C3 validation uses `C-E-5` / Panasonic VS Package C. Its crop produced a
  5 mm SMD electrolytic plan; Craig approved `C271397`, `C249690`, and `C86604`
  as legitimate alternatives found through the normal flow.
- The 2026-07-16 fresh-browser audit opened and searched C3, D1–D7, and Q1–Q6
  against the open `hendley test` design. A completed visual reading now
  outranks a provisional family label in the search box. Unambiguous diode and
  transistor ratings use exact live catalog parameters; explicit SI scaling
  lets catalog `1kV` prove a 1000 V minimum. The final suite is 330 passing.

## Live supply risk

Original-board `LTV-352T` C10800 was measured at 1,295 live units against 1,000 required
for 500 boards, single-sourced. Same-land `EL357N`/`LTV-357T` have materially lower CTR and
are not drop-ins without LED-current review. Craig knows; no design action is recorded.
