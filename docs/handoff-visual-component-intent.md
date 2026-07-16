# Handoff: image-assisted component intent acceptance

## Branch and repository state

Work is on branch `visual-component-intent`, created from `main` at commit
`9279473`.

Committed branch work, newest first:

- `e961372` — transistor visual intent, designator-safe caching/grouping, and
  one-way Fusion Refresh;
- `357d1e3` — diode-family visual intent and catalog proof;
- `d8f0fe4` — complete Refresh-to-approved-parts Mermaid flow;
- `4522d78` — initial image-assisted component intent proof.

The worktree was already dirty when this branch was created. These pre-existing
changes belong to earlier work and must not be casually included, reverted, or
rewritten:

- `CLAUDE.md`
- `HANDOFF.md`
- `README.md`
- `docs/app.md`
- `docs/cli.md`
- `docs/fusion-notes.md`
- `scripts/ui_check.py`
- `src/hendley/cli/manufacturing.py`

Use `git diff` carefully and commit only the visual-intent work unless Craig
explicitly asks otherwise.

## Goal

Hendley lacks enough structured Fusion data to distinguish component subtypes
reliably. Important intent is present in schematic symbols and board graphics:

- ordinary versus polarized/electrolytic capacitors;
- ordinary, Zener, Schottky, and TVS diodes;
- MOSFET/BJT/JFET and P/N type for Q devices.

The solution must be general image-assisted interpretation, not another set of
Python regexes for the current test design.

Refresh must remain free of model calls. Image interpretation happens lazily
when the engineer opens an unresolved red/yellow part, and the result is cached.

## Strict C3 acceptance test

The open Fusion design contains C3:

- designator: `C3`
- value: `10u/25v`
- footprint: `C-E-5`
- footprint headline: `Panasonic Aluminium Electrolytic Capacitor VS-Serie Package C`

Craig changed the fixture from the earlier 10 mm Package G land because the
validation search did not provide a suitable 10 mm part. The current acceptance
flow and image evidence use the 5 mm Package C land.

Craig supplied `C178621` as a known acceptable LCSC/JLC part. It is an **answer
key only**.

The valid test is:

1. Start Hendley normally from this branch.
2. Refresh the open Fusion design.
3. Open C3 through the UI.
4. Let the normal image-assisted read create its description and search plan.
5. Run the normal search through the UI.
6. Inspect eligible returned results.
7. Pass only if `C178621` appears naturally as an eligible result.

Never put `C178621`, its MPN, or catalog facts obtained by directly looking it
up into a prompt, query, fixture, filter, class mapping, or implementation
rule. Do not query that code directly while developing. The code may appear
only in the final assertion over results returned by the ordinary C3 flow.

An earlier attempt violated this boundary by directly verifying `C178621`.
Craig correctly rejected that attempt. No production code changes were made
from that lookup. Treat all facts learned from it as unusable implementation
input.

## Implemented work

### Fusion image capture

New file: `src/hendley/ingestion/fusion/visual.py`

`capture_visual_evidence()` and `add_board_crops()`:

1. Capture begins while the schematic is still active; repeated Refresh may
   return with `EDIT .S1;`, followed by a settle pause.
2. Enumerates `electronics.Sheet`; it never probes nonexistent numbers because
   `EDIT .S<n>` creates a missing sheet.
3. For each returned sheet, runs `EDIT .S<n>;`, `WINDOW FIT;`, and
   `EXPORT IMAGE ... 300;`.
4. Losslessly creates a whitespace-trimmed detail image of each populated
   schematic region so small symbol arrows survive model transport.
5. Runs `BOARD;`, `WINDOW FIT;`, and exports the board. This is treated as the
   one-way transition for the remainder of that Refresh.
6. Board placements are read, then `add_board_crops()` exports the unresolved
   targets without attempting to return to schematic context.
7. Fusion's effectively uncompressed PNGs are losslessly recompressed with the
   Python standard library before hashing or model transport.
8. Hashes metadata plus PNG contents and returns a versioned manifest.
9. Returns `None` on operational failure so image capture cannot break intake.

Fusion writes to `C:\tmp\hendley-visual`; WSL reads the same location as
`~/tmp/hendley-visual` (which resolves to `/mnt/c/tmp/hendley-visual` here).
The paths can be overridden with `HENDLEY_FUSION_VISUAL_DIR` and
`HENDLEY_VISUAL_DIR`.

Live export is working. It generated six schematic PNGs plus one board PNG.
The schematic images are 3312×2562 and the board image is 1112×1184.

### Fusion bridge path fix

Modified: `src/hendley/ingestion/fusion/bridge.py`

`run_eagle()` now escapes backslashes and single quotes before embedding an
EAGLE command in generated Fusion Python. Without this, `C:\Users` raised a
Python `unicodeescape` error before Fusion received the command. This also
applies to the current `C:\tmp` path.

### Intake and browser state

Modified:

- `src/hendley/app/server.py`
- `src/hendley/app/ui.py`

`api_intake` captures the images after normal schematic/board extraction and
stores the manifest in the design cache. It performs no AI call.

The browser keeps `visualEvidence` in state and sends it only to `/api/read`
when it lazily opens an unresolved part.

The visual schema version and image digest are appended to the lazy-read cache
key. An unchanged drawing reuses its reading; changed images force a fresh
reading.

### Multimodal Codex interpretation

Modified:

- `src/hendley/ai/codex_cli.py`
- `src/hendley/ai/claude_cli.py`

Codex `_ask()` accepts image paths and adds each as `codex exec --image <path>`.
The shared part-reading prompt tells the model to locate the requested
designator and extract general intent:

- family and subtype;
- polarity/channel;
- mount;
- visible symbol cues;
- uncertainty.

The reading returns an `intent` object in addition to `is`, `spec`, `search`,
`plan`, rationale, and confidence.

Claude accepts the shared `images` argument but currently ignores it; only the
Codex transport has implemented image attachment.

### Documentation and tests

New:

- `docs/adr/0009-schematic-images-are-intent-evidence.md`
- `tests/test_visual_evidence.py`

Modified tests:

- `tests/test_codex_ai.py`
- `tests/test_app.py`

Coverage includes image argv construction, paths with spaces, visual digest and
read-plan cache invalidation, sheet ordering, settled/fresh exports,
dimensioned board crops, catalog-class proof, generated-search draft
provenance, nonfatal missing images, and Windows-path escaping.

The final full run passed:

```text
308 passed in 31.21s
git diff --check: clean
```

## Current live behavior

The end-to-end Fusion → Hendley → Playwright loop now presses Refresh, opens C3,
waits for the lazy multimodal read, and fires the naturally generated search.
Visual evidence established:

- the schematic's `+` mark means polarized/electrolytic intent;
- undrilled rectangular board pads mean SMD, not radial through-hole;
- a centered 12 mm board crop measures the can land at approximately 5 mm.

The resulting ordinary plan uses coarse discovery text equivalent to `10uF 25V
electrolytic D5` and proves all of the following against the live catalog:

- `Capacitance = 10uF`;
- `Voltage Rating >= 25 V`;
- `Diameter = 5 mm`;
- `secondTypeName = Aluminum Electrolytic Capacitors - SMD`.

This produced 14 eligible, live-verified D5 SMD electrolytics. Craig reviewed
the normal results and approved `C271397`, `C249690`, and `C86604` as legitimate
alternatives. They are engineering decisions, not fixtures or allowlists.

The originally supplied terminal answer-key assertion still did not match the
ordinary eligible set. Do not respond by looking it up or encoding it. The
important architectural acceptance—visual intent becoming provider-verifiable
class, mount, and dimensional constraints—passed with engineer-confirmed parts.

## Diode acceptance

The cached/live validation design exercised a generic 1000 V diode, 1N4148,
BAT54 Schottky, and 18 V TVS. The important fixes and results were:

- model requests attach only the requested component crop plus schematic
  sheets, never every other placement crop or the redundant complete board;
- Fusion PNG recompression reduced a six-sheet request from roughly 150 MB to
  a transportable size without changing pixels;
- verified catalog `componentModel` is now an ordinary proof field for family
  requirements such as `BAT54`;
- live measurement corrected a stale class assumption: authoritative
  `secondTypeName` is `Schottky Diodes`, not the index/API example
  `Schottky Barrier Diodes (SBD)`;
- TVS class is `ESD And Surge Protection (TVS/ESD)` and its measured voltage
  parameter is `Reverse Stand-Off Voltage (Vrwm)`.

The ordinary BAT54 plan proved model family, `Schottky Diodes`, and SOD-323,
yielding 15 eligible candidates. `18V TVS` remains an engineering convention:
the current reader treats 18 V as reverse stand-off voltage, but Craig has not
explicitly confirmed whether this shop always means Vrwm rather than breakdown
or clamp voltage.

See `docs/parts/schottky-and-tvs-diodes.md`.

## Transistor acceptance

The final physical sheet is the seventh enumerated sheet. Fusion reports it as
sheet entity number 7 with library name `sheet8`; trust enumeration and do not
probe/create sheets by guessed number.

The live fixture contains:

- Q2: `40V`, N-channel MOSFET symbol, `SOT23-3`;
- Q3: `40V`, P-channel MOSFET symbol, `SOT23-3`;
- Q4: `40V 100mA`, NPN BJT symbol, `SOT23-3`;
- Q5: `40V 100mA`, PNP BJT symbol, `SOT23-3`;
- Q6: `JFET TEST`, N-channel JFET symbol, `SOT23`.

Q2 and Q3 deliberately have identical written value and land. This exposed two
pre-interpretation identity bugs: normalization grouped them before reading
their unique symbols, and a prefix/value/footprint cache could replay Q2's
N-channel answer onto Q3. Mode-less/family parts now remain separate until
interpretation, visual readings are keyed by exact designator, and a generic
LLM cache cannot cross designators when visual evidence is available. An
engineer-recorded generic correction remains authoritative and reusable.

The live image-assisted reads and ordinary catalog searches passed:

| Ref | Visual reading | Required live proof | Eligible |
|---|---|---|---:|
| Q2 | N-channel MOSFET | `MOSFETs`, `Type=N-Channel`, Vds ≥ 40 V, SOT-23 land | 30 |
| Q3 | P-channel MOSFET | `MOSFETs`, `Type=P-Channel`, Vds ≥ 40 V, SOT-23 land | 11 |
| Q4 | NPN BJT | `Bipolar (BJT)`, `type=NPN`, VCEO ≥ 40 V, Ic ≥ 100 mA | 5 |
| Q5 | PNP BJT | `Bipolar (BJT)`, `type=PNP`, VCEO ≥ 40 V, Ic ≥ 100 mA | 3 |
| Q6 | N-channel JFET | `JFETs`, `FET Type=N-Channel`, SOT-23 | 12 |

The fixture is correct: Q4's emitter arrow points away from the base (NPN), Q5
is the PNP high-side counterpart, and Q6's gate arrow points into the channel
(N-channel JFET). For the `SOT23-3` library land, discovery now sends separate
narrow requests for the live catalog spellings `SOT-23` and `SOT-23-3`, unions
them, and repeats the complete spelling set in one live package proof term.
The real-browser pass displayed separate Q2–Q6 rows, generated terms, eligible
and rejected proof columns, and selection controls without JavaScript errors.

See `docs/parts/transistors.md`.

## Relevant architecture

- Lazy read: `HendleyApp.api_read()` in `src/hendley/app/server.py`.
- Prompt and plan parsing: `src/hendley/ai/claude_cli.py`.
- Search execution/proof: `src/hendley/resolver/orchestration/search.py`.
- Verified candidate shape: `_verify_rows()` in
  `src/hendley/resolver/orchestration/queue.py`.
- `_verify_rows()` preserves live catalog `firstTypeName` and `secondTypeName`.
- `docs/parts/aluminium-electrolytic-capacitors.md` explicitly states that an
  electrolytic's class comes from catalog `secondType`, never the index's
  broken `is_polarized`/`capacitor_type` fields.
- `UNPROVABLE_COLUMNS` in `src/hendley/datasources/jlc/alternates.py` documents
  why index class flags must not be restored.

## Implemented architectural fixes

1. Live catalog class fields survive verification and are ordinary proof fields.
2. Part-note `catalogType` declarations provide a bounded class vocabulary; the
   model chooses from it and Python only compares.
3. Class-essential searches may use coarse keyword discovery to avoid the
   parametric index's 100-row cap, while the live sieve remains authoritative.
4. Generated search text is no longer persisted as engineer-entered draft text.
5. Read-plan versioning invalidates obsolete voltage-only cached readings.
6. Board capture hides `UNROUTED`; every export removes stale PNGs, pauses for
   Fusion context/window settling, then waits for a fresh non-empty file.
7. Each unresolved placement receives a centered, dimensioned board crop. This
   fixed both target localization and physical scale.
8. Playwright owns the real Refresh → open → Search loop and screenshots.
9. Refresh captures every sheet before its one-way BOARD transition, then reads
   placements and adds board crops without returning to schematic context.
10. Unresolved visually distinct instances are not grouped prematurely, and
    visual read/part caches are scoped to the exact designator.
11. Part notes now provide measured live class and polarity vocabularies for
    Schottky/TVS diodes and MOSFET/BJT/JFET transistors.
12. Visual cache hydration preserves lazy opening and restores the cached full
    reading/proof plan instead of resolving from a compact `SpecKey` alone.
13. Ordinary plans support general multi-package union discovery: one capped
    request per exact spelling, deduplicated results, and one full-set live
    package proof term.
14. Sparse schematic exports receive automatic populated-region detail crops;
    this made Q4/Q5 emitter-arrow geometry reliably readable without a
    component-specific answer key.

## Live Fusion observations

The bridge is reachable when Fusion is running. `BOARD;`, `EDIT .S1;`,
`EDIT .S<n>;`, `WINDOW`, `DISPLAY -UNROUTED`, and `EXPORT IMAGE` work through
`Electron.run`, but this Fusion MCP build can wedge its script proxy when asked
to return from board to schematic. Refresh therefore captures schematic sheets
first and treats BOARD as one-way. Context/window commands are deferred enough
to require a settle pause before reads and exports. Never accept a pre-existing
output file as evidence that a new export completed. If Electronics reads return
zero rows and `EDIT .S1` raises a recursive proxy stack overflow, toggle the
Fusion MCP server or restart Fusion once; do not keep retrying the wedged proxy.

`GRID MM 1.0` changes the visible Fusion canvas, but `EXPORT IMAGE` omits the
grid. Electronics also exposes no `app.activeViewport`; dimensioned crop bounds
are the automated scale source.

At the most recent live read, `electronics.Sheet` returned seven entities
numbered 1–7. Names were `sheet1`, `sheet2`, `sheet3`, `sheet5`, `sheet6`,
`sheet7`, and `sheet8`. The user refers to the final physical page as sheet 7/7;
the library name `sheet8` reflects earlier deletion/history. Trust enumeration
and never create a missing sheet by probing.

## UX automation

Craig explicitly wants the agent to own the test loop. The next agent should:

- start the feature-branch app on a separate port if necessary;
- use Playwright to press Refresh, open C3/D/Q lines, and run Search;
- inspect API responses and screenshots itself;
- make general fixes;
- inspect the normal eligible proof set and preserve the answer-key boundary;
- avoid asking Craig to operate the UI for routine verification.

## Recommended next work

1. Decide whether `18V TVS` is a shop convention for Vrwm. If Craig confirms,
   document it as a convention; otherwise keep the voltage interpretation below
   automatic acceptance.
2. Review the remaining dirty worktree separately. At handoff it contains only
   older unrelated changes in `CLAUDE.md`, `HANDOFF.md`, `README.md`,
   `docs/app.md`, `docs/cli.md`, `docs/fusion-notes.md`, `scripts/ui_check.py`,
   and `src/hendley/cli/manufacturing.py`. Do not sweep them into this branch's
   next commit without Craig's explicit scope decision.

The definitive post-acceptance run completed with `320 passed in 49.72s`;
Ruff and `git diff --check` were clean.
