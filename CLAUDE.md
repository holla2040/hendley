# CLAUDE.md — guidance for Claude Code in this repo

## Purpose

**Hendley** is a Python tool to query the JLCPCB parts inventory (LCSC / JLC
components) and, going forward, to consolidate part info pulled directly from
Autodesk Fusion Electronics — so the user can validate part availability and
speed up JLCPCB **PCBA** order submissions. It is a Python reimplementation of
JLCPCB's official Java OpenAPI SDK. (Named after James Garner's character
Hendley, "the Scrounger", in *The Great Escape*.)

## Architecture / file map

The package follows `docs/architecture.md` §13: ingestion → domain →
resolver/knowledge → providers, with the CLI (and later the app) as thin
consumers. Nothing under `resolver/`, `knowledge/`, or `domain/` may import
concrete `providers/*` or `datasources/jlc` — only the base protocols.

- `src/hendley/config.py` — loads credentials from the git-ignored `.keys` file;
  resolves endpoint. `Credentials`, `Settings`, `load_credentials`,
  `load_settings`. Path order: explicit arg → `HENDLEY_KEYS` → `.keys` found by
  walking up from cwd. Endpoint order: `HENDLEY_ENDPOINT` → default host.
- `src/hendley/cli/` — argparse CLI; entry point `hendley = hendley.cli:main`
  (also `python -m hendley.cli`). `__init__.py` holds `build_parser`/`main`;
  commands live in `catalog.py` (`ping`, `detail`, `private`, `library`,
  `alternates`), `manufacturing.py` (`fusion`, `stock`, `pcba`/`jlc`, `bom`),
  `knowledge.py` (`db lookup/record/rerank/remove/list/refresh`, `resolve`),
  `app.py` (`app`), and `migration.py` (`scr`).
- `src/hendley/app/` — **the app, the primary interface** (ADR-0003/0004):
  `hendley app` serves a stdlib-only local web UI on 127.0.0.1 (`server.py` =
  JSON API 1:1 over library calls; `ui.py` = the single embedded page). One
  page: left rail = Refresh + board qty + the design's components colored by
  state (green covers / red short-or-unpicked / amber unnamed-part-needs-a-look
  / dashed DNP). **The rail and panel titles show the DESIGN'S OWN WORDS** —
  schematic VALUE + library footprint, verbatim (`D6 D7 D8 D9 · D-SOD323`);
  what the app worked out lives in the panel's read-only `recorded as` line,
  never in the title (ADR-0007 — the app quoting its own guess back as fact
  is how a fabricated `1000V` once became "the design").
  Click a component → detail panel: **the search box (ADR-0007) is on every
  panel and the overview** — one line: **[part type ▾] [type anything] [Search]**,
  seeded from what's remembered. The AGENT plans the query (`/api/search`),
  Python fires it and PROVES every result against every term, showing the
  say-line, the counts, and every rejected part **with its reason** (`is 100,
  not ≥ 250`). **Nothing about the query is hidden or fixed**: the part-type
  popup shows the table actually used and overrides the agent (`auto` = let it
  read the part; `— no part type —` = keyword-only, and the page warns that
  words must then be specific); an overridden type is remembered as the shop's
  convention for that designator letter (`X → connector` — `X` is a connector
  in one library and a socket in another); and **"the actual search"** shows
  the literal request + every proven term, each droppable, plus add-a-term
  (fields offered from `/api/categories`). An edited query fires EXACTLY as
  given (no agent call) and the request is rebuilt from the terms, so a dropped
  term can't sneak back in as a net param. Deterministic R/C lookups still
  auto-run at Refresh — into the same table, showing their query the same way.
  **The results are ONE comparison table, and it holds only the parts you can
  ORDER**: every part that satisfies EVERY term and covers the run, with its
  actual value under each criterion as a column (`value = 10uF`,
  `voltage ≥ 50V`, `Diameter = 5mm`), so a part is picked by reading DOWN a
  column, not by opening fifty datasheets. **A part that fails a term, or is
  short of the run, is NOT a row** — it cannot go on the board, and the goal is
  open → refresh → assign → alternates → export, not browsing the catalog. So
  **the table carries no red cell at all**. Nothing is hidden, though: the
  say-line counts them (`100 looked at · 12 you can order · 88 can't be used
  (24 short of 500, 64 fail a term)`) and **`show the N you can't use`** puts
  them back with their red reasons — which matters in exactly one case, when
  NOTHING is orderable and the app must name the term that did the killing (a
  bad term rejecting 100 good parts looks just like an empty catalog otherwise).
  Column rule: a term earns a
  column iff the CATALOG names the field (`package`/`capacitance_farads` are
  query plumbing and don't; `tolerance_fraction` IS the catalog's `Tolerance`
  and does — via `CATALOG_ALIAS`, or the engineer sets `0.01` and reads `±1%`
  with nothing on screen tying the two together). **ONE TERM PER FIELD**: the
  sieve collapses names that differ only in case or punctuation (`resistance` /
  `Resistance`), keeping the term that can actually be proven — stating both
  compares `10000` against `"10kΩ"` and rejects every part alive.
  `show all N specs` adds every other catalog
  parameter. Headers are the shop's words (`value`, `voltage`, `temp_co`,
  `tol`) with the constraint stacked underneath; the field's real name is what
  the sieve, the sort and the term list still use.
  **Selections save themselves** — there is no commit button. The radio picks
  what mounts (order-only when overriding an approved part; recorded at the head
  of the list on a first pick — `rank` is a DB column, never a word on screen);
  the **alt checkbox** grows/prunes the AVL from either table (unchecking is the
  one audited removal path). Both fire `/api/approve` / `/api/remove` on the tick. The two tables use SEPARATE radio groups (`pick`
  and `found`): the same part appears in both, and one shared group meant the
  lower table silently unchecked the upper one on every render. Opening a panel
  live-verifies its whole list, `????` when live access is down — never
  stale-as-current. The requirement's key comes from the READING the panel
  already made (`/api/key` answers from it — the agent is only asked when the
  schematic named the part *nothing*, where the engineer's search words are the
  only thing that knows what it is). An **unnamed part** (no VALUE, no MPN)
  never mounts silently: amber, says which part and why, and the one button
  that remains — *"I've looked at this"* — is its acknowledgement (draft
  `acks`). A **schematic-pinned part is a DEFAULT, not a lock**: approve a list
  against it and the recorded key converts the line to spec-driven at intake, so
  a short pin substitutes down the list instead of blocking the order.
  **Never show the word "rank" in the UI** — the engineer sees a *chosen* part
  and its *alternates*; rank is internal bookkeeping.
  **DNP this run** (title line, immediate like board qty) sits a part out of
  the current run only — `DNP · this run` in the rail, excluded from export and
  its gates, restored by **Populate this run**, schematic DNP untouchable;
  Placement section edits `data/cpl-rotations.json`;
  Export BOM/CPL in the title bar stays disabled until all rows are green
  (Chromium: standard folder picker for the copies). Page load repopulates
  from the last read (`~/.hendley/design-cache.json`) with all corrections
  re-applied; picks/searches/qty/per-run DNPs/acks persist via the server-side
  draft (`~/.hendley/draft.json`, cleared on clean export). Zero new
  dependencies.
- `src/hendley/resolver/orchestration/search.py` — **the search executor
  (ADR-0007): a coarse net, then an honest sieve.** jlcsearch honours only
  `package` + one value param (`resistance`/`capacitance`) and **silently
  ignores every other param** — ask it for X7R/25V and it returns a 100n/50V
  X5R part with no complaint, so a query proves NOTHING. `run_search()` fires
  the agent's `net`, live-verifies every hit, then proves each candidate
  against every `sieve` term by pure comparison over data we hold, in order of
  authority: the **live-verified fact** → the index row's typed column (matched
  by name, so the catalog's `Voltage Rating` finds the index's typed
  `voltage_rating` and gets a real number for free) → the catalog's own
  `parameters`. Unprovable = a **miss** (with the reason), never a pass.
  **The sieve speaks the CATALOG's language, not the index's.** The official API
  publishes specs as NORMALIZED name/value pairs (`Capacitance`,
  `Voltage Rating`, `Diameter`, `Height - Seated (Max)`) — the same names for
  every manufacturer. The index's `attributes` blob is a scrape of the RAW
  datasheet keys and they drift (of 680 sampled electrolytics the diameter is
  `φD` on 583 rows, `Diameter` on 62), so it is **deliberately not consulted**:
  it can only answer worse than the parameters we already fetched, and a key it
  happens to miss would be recorded as an honest-looking miss on a part that in
  fact matches.
  A term may declare the **unit the catalog prints** (`{"field": "Voltage
  Rating", "op": "gte", "value": 50, "unit": "V"}`), which is what makes "50 V
  or better" expressible at all — without it `"63V"` is uncheckable and every
  part misses. Python still never GUESSES a unit: it checks the string conforms
  to the one the agent handed it, and `"17mA@120Hz"` asked for in mA stays an
  honest miss. Every net param is re-asserted in the sieve (`NET_COLUMNS`) so a
  dropped param can't leak a wrong part. Each part carries its `proof` — one
  entry per term, pass AND fail, with the catalog's own string (`shown`) and a
  `catalog` flag — because the engineer picks by comparing a column, not by
  reading a sentence about why some other part was rejected.
  Python compares; it never parses a value or composes a query.
- `src/hendley/domain/model.py` — the canonical vocabulary: `SpecKey`
  (**`kind` + `package` required; `value` OPTIONAL** — a general-purpose diode
  has none, and a key that demands one only ever gets a fabricated answer,
  ADR-0007; the agent derives the key, the engineer never types it),
  `RequirementLine` (one selection mode: spec | mpn | provider refs; `dnp`
  carried), `RequirementsBom` (versioned JSON, `requirementsBomVersion: 1`),
  `Check` + the `CHECKS` severity table (error blocks upload / warning /
  info). Core layers (`domain`, `knowledge`, `resolver`, `requirements`)
  never import concrete providers or `datasources/jlc`.
- `src/hendley/requirements/` — `normalizer.py` (Fusion→RequirementsBom:
  designator grouping, DNP flag, LCSC/MPN pass-through, and auto-spec for
  generic R/C/L via `specs.py` — deterministic ONLY for the trivially
  unambiguous; do NOT grow its regexes: ambiguity belongs to the AI tier).
- `src/hendley/ai/` — the interpretation tier (ADR-0005/0006/0007):
  `Interpreter` protocol + `claude_cli.py` (`claude -p`, rides the
  subscription, `HENDLEY_CLAUDE_BIN` override). Four judgments, all cached:
  `interpret_part` (ad-hoc values: `47u/50V` → value `47u`, qualifier `50V`),
  `interpret_footprint` (**normalize to catalog packages**: `D-SOD323` →
  `SOD-323`, `C-0603` → `0603`; verbatim only when nothing standard is
  recognizable, e.g. `C-E-5`), **`plan_search`** (the engineer's words → a
  catalog query plan: `net` + `sieve` + `say`; the prompt carries the MEASURED
  index facts — which params actually filter, and **ONE TERM PER FIELD**, since
  an index column and a catalog parameter differing only in case are the same
  field — because a hallucinated param is silently ignored and looks like a
  filter, and a duplicated one rejects every part alive),
  and **`derive_key`** (the AVL's SpecKey for a pick, from the design line +
  search words + the picked part's verified facts; leaves `value` empty when
  the part has none — never invents one).
  `interpret_footprint()` serves schematic-pinned parts. Every judgment is
  cached in the DB (`interpretations`, provenance user > llm >
  deterministic — user answers are never overwritten or re-asked); failures
  degrade to one-time confirm cards in the app, never break the flow.
  **But a judgment made against a LIE is thrown away**, not replayed: a cached
  plan that sieves on a column since measured to be unprovable would keep
  rejecting every good part for ever, so `Server._stale_plan()` discards it and
  re-reads the part. The DB heals itself.
  **An incomplete reading is knowledge, not failure**: a diode with no
  schematic VALUE comes back as `Interpretation(spec=None, partial={kind,
  package})` — it prefills the confirm card (only the value is the
  engineer's ask) and the interpreter stays alive for the rest of the
  design. `None` means the INTERPRETER is unavailable, and only then does
  the caller stop asking it.
  **Standing rule (ADR-0006): judgment belongs to Claude and the engineer;
  Python never composes searches, invents filters, or parses names.**
- `src/hendley/ai/partnotes.py` + **`docs/parts/`** — **the part-class knowledge
  base.** There is no one way to search for a part, and pretending there is has
  cost us real searches: a resistor's index column `resistance` has the SAME NAME
  as the catalog's `Resistance` (so a plan stating both asks "10000 = `10kΩ`" and
  rejects every part alive), while a capacitor — column `capacitance_farads` —
  must state both; an electrolytic hides its can dimensions inside the
  package string; a diode's family (small-signal / Schottky / zener / avalanche)
  is something the index **cannot tell you at all**. So the knowledge lives in
  `docs/parts/` — one markdown note per class, human-editable, pasted whole into
  the agent's prompt when it opens a part of that class. A note opens with a
  fenced ` ```applies-to ` block naming the CATALOG's `secondTypeName`(s)
  (`Aluminum Electrolytic Capacitors - SMD`, `Schottky Barrier Diodes (SBD)`) and
  the jlcsearch slug as a coarse fallback. `note_for()` resolves the directory
  `HENDLEY_PART_NOTES` → `docs/parts` beside the source → none. Stdlib only.
  **No note = no special knowledge**: the agent stays conservative rather than
  guessing, and an unmeasured "fact" in a note is worse than silence because the
  agent will believe it. Written so far: aluminium electrolytics
  (`aluminium-electrolytic-capacitors.md`) and chip resistors
  (`chip-resistors.md` — the `Resistance` name collision, `tolerance_fraction`
  is a FRACTION and wants `lte`, and **never sieve on power**). Still to write:
  MOSFETs, the diode families.
- `src/hendley/knowledge/partsdb.py` — the house-parts DB (SQLite v4 at
  `~/.hendley/parts.db`, `HENDLEY_DB` to override): House Parts (opaque id +
  spec-tuple index), ranked Part Choices (deliberate rank, `active|removed`),
  `choice_provider_ids` (provider-neutral identity: mpn/manufacturer preferred,
  LCSC code is the `jlcpcb` ref; per-provider advisory stock/price cache —
  NEVER order against it), append-only audit trail. **Choice identity: the
  provider ref decides first; a bare-MPN match is rejected when the row
  carries a conflicting ref** — different manufacturers publish the same MPN
  (e.g. 1N4148WS), and collapsing them once overwrote a recorded pick. Migrations chain
  v1→v2→v3→v4 on open (v4 adds the `interpretations` cache, ADR-0005), one
  transaction each, file backup (`.v<N>.bak`) first.
  `PartsDb` class = the KnowledgeStore contract.
- `src/hendley/resolver/` — provider-independent core:
  - `orchestration/resolve.py` — the rank-walk resolver (one batched verify,
    silent substitution down the AVL, escalations carrying per-choice live
    stock, DNP pass-through) over injected DataSource + ProviderStrategy.
  - `orchestration/queue.py` — the ONE batched approval queue: discovery
    auto-runs only where deterministic (dense R/C value param, or chip
    package + category); anything else needs the engineer's search terms
    (`searches={lineIndex: terms}`, fired verbatim at the FTS index) and
    says `discovery.needsSearch` without them (ADR-0006). Verify, filter,
    rank; `apply_approvals` records picks; `explore()` = free search for
    pinned parts.
  - `constraints/engine.py` — deterministic candidate rejection BEFORE
    ranking (unverified, wrong package), reasons attached.
  - `ranking/engine.py` — orders NEWLY DISCOVERED candidates only (ADR-0001;
    the AVL rank is deliberate and never computed): prior approval > stock
    margin > price, every score decomposed into a visible `why` list.
- `src/hendley/providers/` — strategies select, adapters format:
  - `jlcpcb/` — `strategy.py` (jlc-mounted, live-verified), `adapter.py`
    (validate = blocking gate; export = bom.csv + cpl.csv + rotations),
    `bom_csv.py` (resolution→CSV renderer + gate), `order_files.py`
    (BOM/CPL builders behind `hendley pcba`).
  - `pcbway/` — the anti-coupling proof: MPN-based strategy
    (`requires_live_stock=False`, facts honestly `unverified` — no PCBWay
    API, no scraping) + the MPN BOM template adapter.
- `src/hendley/reporting/snapshot.py` — Release Snapshots: the immutable
  what-was-ordered record written beside a clean CSV emit (DB holds policy;
  the snapshot holds fact).
- `src/hendley/datasources/jlc/` — everything that talks to JLC-side services:
  - `auth.py` — `JOP` request signing (HMAC-SHA256). Builds the
    `Authorization` header and the string-to-sign.
  - `client.py` — `JLCClient`: signed `_post` plumbing plus the read-only
    component endpoints; `JLCError` and the `{code, success, message, data}`
    envelope unwrap.
  - `alternates.py` — alternate-part discovery: `fetch_candidates()`
    (DISCOVER candidate codes from the third-party parametric index
    `jlcsearch.tscircuit.com` — the official API can't search),
    `discover_and_verify()` (VERIFY *every* hit in one batched
    `getComponentDetailByCode` call — jlcsearch stock is a stale snapshot),
    and `format_alternates_report()` (the trade-off table). It deliberately
    does **not** rank or pick — Claude/the user weighs the verified data.
    jlcsearch matches `package` (and other string filters) by **exact
    equality, no wildcards**; the fuzzy escape hatch is `--category components
    -p search=…` (FTS). `CATEGORIES` holds the 44 jlcsearch category slugs.
    **`UNPROVABLE_COLUMNS` — the 46 columns the index publishes that are a
    LIE.** Measured live (100+ rows per category, re-probed across distinct
    packages so a stock-skewed sample couldn't fool us): each is constant,
    always-null, so sparsely populated that a term on it rejects nearly
    everything — or **numerically meaningless**: `resistors.power_watts` is the
    catalog's string with its UNIT THROWN AWAY, so a 0603 reads `100`
    (milliwatts) and a 2512 reads `1` (a WATT), and `power_watts gte 100` rejects
    every 1 W part while passing a 250 mW one. A column whose unit is not
    constant proves nothing, however well populated it looks.
    `capacitors.is_polarized` is **`false` on every aluminium
    electrolytic**; `diodes.is_schottky`, `is_zener` and `is_tvs` are `false` on
    every schottky, zener and TVS; `capacitor_type` is `"unknown"` and
    `diode_type` is `"general_purpose"` for all of them. They are the most
    dangerous thing in the index because they LOOK like the answer — a plan that
    trusts one returns **ZERO parts while looking like it filtered** (this is not
    hypothetical: `is_polarized isTrue` once rejected all 36 candidates for a
    good 10uF 50V can). They are therefore **absent from `CATEGORY_COLUMNS`** —
    and so from the agent's menu and the engineer's field list — but kept, named,
    in `UNPROVABLE_COLUMNS` so the knowledge survives and a test holds the line.
    **Never re-add one.** A part's CLASS comes from the catalog's
    `secondTypeName`; its specs come from the catalog's `parameters`. A category
    left with only `package` is an honest answer, not a gap: the index cannot
    filter that part type, so the catalog must do the proving.
- `src/hendley/ingestion/fusion/` — reading designs out of Fusion:
  - `bridge.py` — `FusionBridge`: the committed HTTP client for Fusion's local
    endpoint. Encodes the full verified handshake (gateway IP with spoofed
    `Host: 127.0.0.1:27182`, `MCP-Session-Id` capture/resend,
    `notifications/initialized` before any `tools/call`) plus `read()`,
    `read_all()` (pagination), `execute_script()`, and `run_eagle()` (the
    `Electron.run` wrapper). Host order: arg → `HENDLEY_FUSION_HOST` → WSL
    default-gateway IP.
  - `live_design.py` — live extraction behind `hendley pcba`:
    `extract_schematic()` (Part + part-scoped Attribute reads; excludes
    GND/supply pseudo-parts and the title block), `extract_board()` (probes
    `electronics.Element`, fires the one-way `BOARD;` switch when needed,
    joins `electronics.Package` for footprint names), `is_dnp()`, `Placement`,
    `natural_key()`.
  - `parts_json.py` — the `DesignPart` model and `load_parts_json()` (the
    parts-export ingest contract); `extract_components()` is a **stub** kept
    for an eventual in-Fusion add-in.
- `src/hendley/providers/jlcpcb/` — JLCPCB-specific manufacturing output:
  - `order_files.py` — the BOM/CPL builders (`build_bom_rows`,
    `build_cpl_rows`, `write_csv`, `BOM_FIELDS`/`CPL_FIELDS`) and rotation
    corrections (`load_rotations`/`rotation_for` over
    `data/cpl-rotations.json`).
- `src/hendley/reporting/stock.py` — JLC enrichment + the inventory check:
  `enrich_with_jlc()`, `check_stock()`/`format_stock_report()` (classify each
  part out/low/not_found/no_code/ok via one `getComponentDetailByCode` call),
  `STOCK_BLOCKERS`.
- `src/hendley/migration/fusion_script/scr.py` — Fusion `.scr`
  migration-script generator: `PartSwap`, `load_swaps_json()`,
  `render_script()`. Turns a list of part swaps (designator + package variant
  + attributes) into the EAGLE command-line script the user runs in Fusion
  (`File > Execute Script`, or `neu_dev.run_text_command("SCRIPT …")` in the
  text-command Py mode). The write side: the Electronics **object** API is
  read-only, but the EAGLE command line **is** reachable over the HTTP
  endpoint via `executeTextCommand('Electron.run "script C:\\path\\changes.scr"')` — so
  Hendley can either hand the user the `.scr` *or* fire it into Fusion over the
  bridge (see "Fusion access from WSL → write side" below). `CHANGE PACKAGE`
  precedes `ATTRIBUTE` per part (variant switch can reset variant-default
  attrs); injection chars are rejected.
- `data/cpl-rotations.json` — per-footprint CPL rotation corrections. Some
  library footprints are drawn rotated vs. what JLC's feeders expect; each fix
  is recorded ONCE, keyed by **LCSC code or library footprint name — never
  designator** (the flaw belongs to the library model and follows the part
  across designs). `rotationOffsetDeg` is positive = CCW (JLC's convention).
  When the user reports hand-rotating a part in JLC's order preview, add an
  entry here (lcsc, mpn, footprint, offset, verified date/design).
- `src/hendley/__init__.py` — public API exports (`JLCClient`, `JLCError`,
  config helpers).
- `docs/api-reference.md` — **the API contract** (reverse-engineered from the
  Java SDK). Source of truth for endpoints, request/response shapes, and the
  PCB/TDP order routes (wrapped in `client.py` but not exercised end-to-end).
- `docs/app.md` — the app user guide (the order workbench page: rail, detail
  panel, the comparison table, pick semantics, export).
- `docs/parts/` — **the part-class knowledge base** the agent reads. One note
  per class (`aluminium-electrolytic-capacitors.md`), keyed on the catalog's
  `secondTypeName`. `README.md` has the format and how to add a class.
- `docs/cli.md` — the CLI guide (commands + output formats, `hendley pcba`
  and the CPL rotations, the design-change workflow, the `.scr` swap-JSON
  contract, the Python API). The README is a TL;DR pointing here.
- `docs/writing-a-provider.md` — the developer guide for adding a board
  house: the strategy/adapter contracts, identity via provider refs, the
  honest-unverified shape, wiring points, and the required tests (PCBWay is
  the reference implementation).
- `docs/adr/` — architecture decision records (ranking synthesis, SQLite,
  app-first interface, …).
- `sdk/` — reference JLCPCB Java SDK jars (Core + Business).
- `image/` — project avatar (`hendley.png`, `hendley_80x80.png`).
- `.keys` — credentials (git-ignored; never commit). `notes` — holds the
  developer-portal URL (not the API host).

- `tests/` — one file per subsystem, all offline (fake bridge/datasource/
  interpreter): `test_auth.py` (signing, pinned to the Java SDK algorithm),
  `test_fusion.py` (parts-export ingest contract), `test_pcba.py` +
  `test_pcba_golden.py` (BOM/CPL builders; byte-identical end-to-end gate),
  `test_app.py` (the JSON API over a real HTTP server: intake → search →
  key → approve → emit, interpretation caching, the recorded key outranking a
  stale spec, a plan that sieves on a lying column being thrown away, and a
  **pinned line building an approved list that survives a Refresh**),
  **`test_search_executor.py`** (the sieve's honesty: an index
  that silently ignores a param must not leak a wrong part; an uncheckable
  term is a miss, never a pass; units are never guessed at; **the
  manufacturer's spelling never decides the answer** — a `φD` part is proven by
  the catalog's `Diameter`; the workings are kept for every part, matched or
  not), `test_app_draft_rotations.py` (rotations/draft/design-cache/overview
  search), `test_queue_discovery.py`
  (deterministic-only auto-discovery), `test_datasources_jlc.py`
  (manufacturer brand-slug parsing, **and that no unprovable column is ever
  offered**), plus
  `test_domain/normalizer/specs/partsdb/resolve/resolver_engines/providers/
  bom/snapshot/alternates/scr/ai`. Fixtures must pass tmp `db_path`,
  `draft_path`, and `cache_path` — tests never touch `~/.hendley`.

## `help` — the plain-speak menu (READ THIS FIRST)

The user must never need the README or the source to use this project, and
never need to guess magic words. Match their message against this table
**before anything else**:

- **`help`** (bare word, or "what can you do", "commands", "menu") → print the
  menu below **verbatim**. Run nothing. Ask nothing. Add nothing.
- **`jlc`**, **`hendley jlc`**, **`pcba`**, "order files", "generate files for
  JLC/JLCPCB", "bom and cpl", or any ask for the JLC order files → run
  **`hendley pcba`** immediately. Do NOT ping first, do NOT present options, do
  NOT ask what they want — run it, then relay the stock report and flag
  blockers. (`hendley jlc` is a real alias of `pcba` — if they typed it, run it.)
- **`app`**, "start the app", "open hendley" → run **`hendley app`** (the
  primary UI: the single-page order workbench at http://127.0.0.1:8341).
- "resolve the BOM", "order N boards", "prepare a PCBA order from specs" →
  the **order-bom skill** (`.claude/skills/order-bom/SKILL.md`): Requirements
  BOM → `hendley resolve --queue` → one approval batch → `hendley bom`.
- "is `<Cxxxx>` in stock", "check `<Cxxxx>`" → `hendley detail <code>`,
  summarize stock/price/package.
- "find a replacement/alternate for `<part>`" → the alternates workflow below.
- "check stock on the design/BOM" → `hendley pcba --no-verify` is NOT it — run
  the full `hendley pcba` (its stock report is the check), or `hendley stock
  PARTS.json` if they point at a parts JSON.
- "what parts do we use for `<spec>`", "house parts", "the AVL" →
  `hendley db lookup/list` (local SQLite, no credentials needed).

### The menu (print verbatim on `help`)

```
Hendley — say any of these:

  app                      open the Hendley app (the single-page order workbench)
                           in your browser — the main way to drive everything below
  jlc                      generate bom.csv + cpl.csv from the open Fusion design
                           and check JLC stock (= hendley pcba). Fusion must be
                           open with the SCHEMATIC view active.
  order 25 boards          resolve the design against your approved house parts
                           (the AVL) at that quantity, one approval batch for any
                           gaps, then emit the upload CSV + release snapshot
  is C25804 in stock?      live stock / price / specs for one part
  find a replacement for R8 (out of stock / different package / different value)
                           discover + verify alternates, then build the Fusion swap
  check stock              stock-check every part in the open design before ordering
  house parts              show the approved parts list (AVL) for a spec, or all
  help                     this menu

Order files land in ~/tmp/hendley_output/ (bom.csv + cpl.csv, nothing else).
Out-of-stock parts are flagged; DNP parts (DNP attribute = 1, or value = DNP) are left out; rotation
fixes in data/cpl-rotations.json apply automatically. After a run, click Fusion's
schematic tab before running again.
```

## The workflow — having a conversation about JLC parts

The point of Hendley: the user runs Claude in this repo, says something in plain
words about a JLC part, and you have the conversation — **you are the interpreter
of their words into the existing tooling.** Three standing rules for that role:

- **Everything you need to drive the tools is documented** — this file,
  `docs/cli.md` + `docs/app.md` (the README is a TL;DR pointing there), and
  the module docstrings named below. **Do not read the source to
  figure out how to use a tool.** If something genuinely isn't documented, say so;
  don't reverse-engineer it from the code.
- **Never modify Hendley's source to satisfy a request.** You translate the user's
  intent into calls to the tools *as they are*. If a request needs a capability a
  tool doesn't have, tell the user — don't add it.
- **Running the CLI:** prefer `hendley` if it's on PATH. On a fresh checkout where
  `pip install -e .` didn't land it on PATH (or the venv isn't active), run it as
  a module from the repo root — `PYTHONPATH=src python3 -m hendley.cli <cmd>` (or
  `python3 -m hendley <cmd>`; plain `python` is missing on some hosts), which
  needs only `requests`. Every `hendley <cmd>` below works identically that way.

**⭐ The one-prompt job — "Generate the files necessary for JLCPCB"** (or any
ask for the BOM/CPL/order files): run **`hendley pcba`**. One command, no
scratch scripts, no hand-built bridge pipeline — it reads the live design over
the HTTP bridge (schematic first, then the one-way `BOARD;` switch), applies
`data/cpl-rotations.json`, verifies stock against the live JLC API, and writes
**exactly two files** — `bom.csv` + `cpl.csv` — to `~/tmp/hendley_output/`.
Preconditions: Fusion open with the design's **schematic view active** (and the
port-forward up). Afterward: relay the stock report (nonzero exit = blockers),
remind the user the engine is left on the board context (click the schematic
tab before re-running), and if they mention having to hand-rotate a part in
JLC's order preview, add the correction to `data/cpl-rotations.json` (keyed by
LCSC/footprint) so it's automatic from then on.

Many conversations are a one-shot lookup — *"is C25768 in stock?"* → `hendley
detail`; *"check this BOM before I order"* → `hendley stock`. The main multi-step
job is **changing a part**, and there is **one** workflow for it; the only thing
that varies is *why* the part changes — it's **out of stock**, or you want a
**different package**, or a **different value**. (If the part lives in a Fusion
design, first read the live design over the bridge — see "Fusion access from WSL"
below — to get its designator and the exact package variant names.) Drive it as:

1. **Anchor on the target.** `hendley detail <code>` → read its category, exact
   `componentSpecification` (the package string), and key specs. The exact
   package string is what you pass as `--package` (see matching rules below).
   `detail` **already prints JSON** — there is **no `--json` flag**; don't pass one
   (it errors). Only `stock` and `alternates` take `--json` (see "CLI output" below).
2. **Translate the spoken constraint into flags** — *you* own the hard filter; it
   is NOT hardcoded. "same package" → `--package "<exact spec>"`; a category →
   `--category <slug>` (`hendley alternates --list-categories`); other constraints
   → `-p key=value`. Then run `hendley alternates <code> --category … [--package …]
   [-p …] --json`. The tool discovers candidates from jlcsearch and **verifies
   every one live** (stock/price/parameters) — it does the gather, not the pick.
3. **Apply any value/numeric hard filter yourself, over the verified `--json`.**
   Most categories have **no** jlcsearch query param for the spec you care about
   (e.g. `resistor_arrays` has no resistance param), and the `_min`/`_max` params
   are unreliable — so don't try to push it into the query. Instead filter the
   `candidates[]` on each part's verified `parameters[]` (the authoritative live
   specs). The recipe (here, keep only 330 Ω parts) — use it, don't re-invent it:

   ```bash
   hendley alternates C29719 --category resistor_arrays --package "0603x4" --json \
   | python3 -c 'import json,sys
   d=json.load(sys.stdin)
   def spec(c,name):
       return next((p["parameterValue"] for p in (c["parameters"] or [])
                    if p["parameterName"]==name), None)
   for c in d["candidates"]:
       if c["verified"] and (spec(c,"Resistance") or "").startswith("330"):
           print(c["code"], c["liveStock"], c["unitPrice1"], spec(c,"Resistance"))'
   ```
4. **Trade off and recommend (this is your job, not the tool's).** Weigh the
   *verified* data. User's bias: **high inventory = popular = supply-chain-safe,
   and they'll pay a bit more for it** — the opposite of "cheapest". **Same
   package is the top priority** (changing it changes the PCB layout); a different
   package can still win if the inventory/price payoff justifies a re-layout.
   Always **surface electrical caveats** — e.g. downsizing 0603→0402 drops the
   power/voltage rating, so check the part's actual dissipation first. Recommend
   one with reasoning the user can override.
5. **Build the swap and generate the `.scr`.** Do NOT read the `scr` module source for the
   input format — the swap-JSON contract is documented in **`docs/cli.md` →
   "The `.scr` file format"** and the `hendley.migration.fusion_script.scr` module docstring.
   Fields (only `designator` required), filled from data you already have:
   - `designator` — the schematic ref (e.g. `R6`). Find it in the BOM
     (`hendley fusion PARTS.json --no-enrich`, or grep the parts JSON) by matching
     the **old** JLC code; the parts-JSON contract is in `ingestion/fusion/parts_json.py`.
   - `package` — the library **variant name**: the *exact* library name read off
     the device, which carries a **leading hyphen** (e.g. `-0402`, not `0402` —
     `CHANGE PACKAGE '0402'` errors). OMIT for a same-package swap. Read the real
     variant name off the device rather than guessing.
   - `lcsc` / `mpn` → the `LCSC` / `MPN` attributes. Both are in hand: `lcsc` =
     the chosen alternate's `code`; `mpn` = its `componentModel` from `detail`
     (note: jlcsearch's row field literally named `mfr` is the **MPN**, e.g.
     `0603WAF2202T5E`, NOT the maker name).
   - `manufacturer` → the `MANUFACTURER` attribute. There is **no dedicated maker
     field** in `getComponentDetailByCode` or jlcsearch — but the API still
     yields it without scraping: **`getComponentDetailByCode`'s `dataManualUrl`
     filename embeds the LCSC brand slug**, shaped `<date>_<brand>-<MPN>_<Ccode>.pdf`
     (e.g. `2402281642_hongjiacheng-1SMA4744A_C19077482.pdf` → brand `hongjiacheng`,
     matching JLC's part page). This is now **implemented**: `JLCDataSource.verify`
     parses the slug into `PartFact.manufacturer` (strict, anchored on the known
     MPN and code — None on any mismatch), and every resolve backfills NULL makers
     in the parts DB (`update_verified` never overwrites a recorded name). Prefer
     it over a WebFetch of the LCSC product page, which can report a different
     brand (saw "R+O" for that same code). The slug gives the brand but not its
     casing/full legal name, so confirm the exact display string with the user if
     it matters. Do NOT fabricate it. If the swap keeps the same maker, the
     design's existing `MANUFACTURER` already holds it — set this only when it
     changes.
   - `attributes` — any extra attrs (e.g. `DESC`).

   Then `hendley scr swap.json -o changes.scr` (offline). The script carries the
   **package variant and the attributes** — `CHANGE PACKAGE` (when `package` is
   set), then the `ATTRIBUTE` lines.

   **Write artifacts to `~/tmp/hendley_output/`, never the repo root.** The swap
   JSON, the generated `.scr`, and any scratch output go there
   (`mkdir -p ~/tmp/hendley_output` first) — e.g.
   `hendley scr ~/tmp/hendley_output/swap.json -o ~/tmp/hendley_output/changes.scr`.
   Keep the working tree clean.
6. **Apply in Fusion, then reconcile.** Fusion is the write side (the Electronics
   *object* API is read-only). Two ways to apply the `.scr`:
   - **Manual** — the user runs it: *File > Execute Script*.
   - **Over the HTTP bridge (preferred when Fusion's endpoint is reachable)** — fire it from
     Python over HTTP: `executeTextCommand('Electron.run "script C:\\tmp\\changes.scr"')`
     via the `fusion_mcp_execute` tool (see "Fusion access from WSL → write side" below).
     This same channel can carry a **changed schematic VALUE** (e.g. 220 Ω →
     330 Ω) as `Electron.run "VALUE R6 330"`, so the whole change can be one
     scripted stream — no manual value-setting step required.

   Either way: if you apply manually, also set anything the `.scr` doesn't carry
   (notably the VALUE) in Fusion — do NOT hand-edit the `.scr` to fake a value.
   `Electron.run` returns no echo, so **verify** with a scoped
   `electronics.Attribute` read (live `part_object_id`) afterward, and remember
   bridge changes are **unsaved** until the user saves in Fusion. Then update the
   BOM record (the parts JSON) so the designator points to the new code and a
   later `hendley stock` reflects reality.

**jlcsearch matching rules (so your flags actually match):**
- `package` and other per-category **string** filters are **exact, case-
  sensitive, no wildcards** (`DFN-8` ≠ `DFN-8(3x3)`; `%`/`*`/substrings → 0 rows).
  Use the target's exact `componentSpecification`.
- Numeric `_min`/`_max` params are **unreliable** (sparse columns silently drop
  null rows). Apply numeric/spec filters yourself over the verified
  `parameters[]`, not via jlcsearch query params.
- Fuzzy / cross-package discovery: `--category components -p search="<tokens>"`
  (FTS, token + prefix; in-stock parts only).

**Do NOT** filter or rank on Basic vs. Extended — it's a fee attribute, not a
selection criterion (display it, don't select on it). That fee is the JLCPCB PCBA
**feeder/loading charge**, per *unique* part type and one-time per order (NOT per
unit): **Economic** tier ≈ **$3** per Extended part (Basic free); **Standard**
tier ≈ **$1.50** per part type for *both* Basic and Extended — so "Basic is
cheaper" really only holds on Economic, and the impact scales with BOM diversity
and amortizes over board count. The *unit-price* gap between a Basic and Extended
equivalent is negligible (often Extended is even cheaper per unit). The fee is
**not** returned by the component API (it's order-level) — which is exactly why
you surface Basic/Extended for the user's judgment rather than select on it.
(Source: jlcpcb.com/help/article/pcb-assembly-price — a policy figure that
changes; verify if it matters.) **Do NOT** download the whole catalog "for one
part" — jlcsearch is the discovery surface.

**CLI output (so you don't guess a flag that doesn't exist):**
- `detail`, `private`, `library`, `fusion` — **print JSON by default; no `--json`
  flag** (passing `--json` errors). Pipe their stdout to `python3`/`jq` to parse.
- `stock`, `alternates` — print a **human report by default**; add **`--json`**
  for structured output. These are the *only* two commands that accept `--json`.
- `ping` — prints a status line. `scr` — prints the `.scr` (or `-o FILE` to write).
- `pcba` — writes `bom.csv` + `cpl.csv` to `--outdir` (default
  `~/tmp/hendley_output/`), progress to stderr, the stock report to stdout;
  exits nonzero on stock blockers (same gate as `stock`). `--no-verify` skips
  the JLC check (offline, no credentials). No `--json` flag.
- `resolve` — resolution JSON to stdout (or `-o FILE`), escalation report to
  stderr, exit 1 on escalations; `--queue FILE` also writes the approval
  queue. `--provider pcbway` needs no credentials (nothing live-verifiable).
- `bom` — the upload CSV to stdout (or `-o FILE`, which also writes the
  release snapshot on a clean gate); blockers to stderr + exit 1. Offline.
- `db …` — local SQLite, offline, JSON to stdout — except `db refresh`,
  the one db action that hits the live API.
- `app` — starts the local web UI (127.0.0.1, default port 8341); needs no
  credentials to start (live actions construct the client lazily).
- Each command's flags are exactly those in `hendley <cmd> --help`; don't assume a
  flag exists because another command has it.

## Auth scheme (`JOP`)

`Authorization: JOP appid="..",accesskey="..",timestamp="..",nonce="..",signature=".."`

- `signature = Base64(HMAC_SHA256(secretKey, stringToSign))`
- `stringToSign = METHOD\nCANONICAL_URI\nTIMESTAMP\nNONCE\nPAYLOAD\n`
- `CANONICAL_URI` = raw request path; `PAYLOAD` = exact JSON body (empty for
  GET); `TIMESTAMP` = integer epoch seconds; `NONCE` = 32-char random token.

All component routes are `POST` with a JSON body, even getter-shaped names.
Null body fields are omitted to match the Java SDK's `toJSON()`.

## Fusion access from WSL (read side)

**Access is 100% plain HTTP — this project uses NO MCP connector or client.**
Hendley reads a live Fusion Electronics design by issuing JSON-RPC `POST`s
directly to Fusion's local HTTP endpoint with `curl`/`requests`. Do **not** use
Claude Desktop's "Autodesk Fusion" connector, an MCP client, or `claude mcp add`
— there is none in this project, and you don't need one. **All communication is
HTTP.** You call the **`fusion_mcp_electronics_read`** tool by `POST`ing a
`tools/call` request over HTTP (that's the tool's literal name — it is invoked
via HTTP, not through any MCP client).

The handshake is **not** "just POST initialize then tools/call": you must hit
the **Windows host IP, not `127.0.0.1`** (loopback isn't reachable from WSL) yet
still **send a `Host: 127.0.0.1:27182` header** (the server now validates `Host`
and 403s "Invalid Host header" on the gateway IP — connect to the gateway,
spoof the header to loopback), capture the **`MCP-Session-Id` HTTP response
header** and resend it on every request, and `POST` a
**`notifications/initialized`** message before any `tools/call` — skip any of
these and you get the confusing `Invalid Host header` / `Missing
MCP-Session-Id header` / `Session not initialized` errors that have made past
agents hand-write their own client. **Do not re-derive it or read source — copy
the complete, verified HTTP recipe (handshake + a Part→Attribute→`LCSC` worked
example) from `docs/fusion-notes.md` → "Talking to Fusion over HTTP — the full
recipe".** The JLC `Cxxxx` code is the part's **`LCSC`** attribute (read
`electronics.Attribute` filtered by `part_object_id`); MPN is `MPN`.

The one setup requirement is on the Fusion/Windows side: Fusion running with an
Electronics doc open and its endpoint enabled at **Preferences > General > API >
Fusion MCP Server** (this Autodesk toggle is the *only* thing called "MCP" — it
just publishes the HTTP endpoint Hendley then talks to).

⚠️ **Attribute reads are part-scoped, and `object_id`s aren't stable.** Filtering
`electronics.Attribute` by `name` alone (or unfiltered) returns **empty** — you
must pass the live `part_object_id`. And `object_id`s are reassigned on every
reload (R1 was `2812` one session, `11225` the next), so always re-read
`electronics.Part` for the current id in the same session. (This — not "the
reader can't see JLC attrs" — was the cause of earlier empty reads;
`LCSC`/`MPN`/`MANUFACTURER` do read back fine when scoped.)

## Fusion access from WSL (write side) — `Electron.run`

The Electronics **object** API is read-only, but the **EAGLE command interpreter
is reachable over the same HTTP endpoint** — the one thing we long thought
impossible. The trick (Autodesk forum, verified live):

```python
import adsk.core
app = adsk.core.Application.get()
app.executeTextCommand('Electron.run "script C:\\tmp\\changes.scr"')
```

Run that string through the `fusion_mcp_execute` tool (called over HTTP, same as
the read tool — args `featureType:"script"`, `object.script`=a Python source
string that defines `def run(_context):`; its `print()` output comes back in the
`{"message",...}` envelope — exact arg shape + copy-paste recipe in
`docs/fusion-notes.md`). A **bare**
`executeTextCommand("script …")` fails (`There is no command script`) because it
hits Fusion's *core* channel; wrapping in **`Electron.run "<eagle cmd>"`** routes
into the electronics interpreter. So Hendley can apply a `.scr` (or any `CHANGE` /
`ATTRIBUTE` / `VALUE` / `EXPORT` command) headlessly over the bridge. Rules:
- **No return value** — `Electron.run` yields `''` on success; verify out-of-band
  (scoped `electronics.Attribute` read, or an `EXPORT PARTLIST <file>` you read).
- **Fusion-host paths** — Fusion is on Windows; WSL `~/tmp/x.scr` ↔ `C:\tmp\x.scr`
  (`~/tmp` → `/mnt/c/tmp` on `hendrix`). Double the backslashes in the Python
  literal; nest the quotes (`'Electron.run "script C:\\tmp\\x.scr"'`).
- **`.scr` stops at the first failing command**; changes are **unsaved** until the
  user saves in Fusion (reopening reverts them).
- Full detail + the verification matrix: **`docs/fusion-notes.md` → "The WRITE
  path"**.

⚠️ **WSL port-forward gotcha (cost us a debugging session):** to reach Fusion's
Windows-loopback port from WSL2, forward it on Windows with
`listenaddress=<WSL gateway IP>` (e.g. `172.17.64.1`, from `ip route | grep
default`) — **never `listenaddress=0.0.0.0`**. A `0.0.0.0:27182` listener hijacks
the loopback that Fusion's server and the Claude Desktop connector use, so they
"connect then close unexpectedly" and Desktop stops connecting. Symptom check:
Windows `curl http://127.0.0.1:27182/mcp` returns `{"error":"Not Found"}` when
healthy; if it closes unexpectedly, delete any `0.0.0.0` portproxy rule
(`netsh interface portproxy delete v4tov4 listenaddress=0.0.0.0 listenport=27182`).
See `docs/fusion-notes.md` "Reaching Fusion from WSL2".

## Verified endpoint facts

- API host: **`https://open.jlcpcb.com`** (the default in `config.py`).
- `api.jlcpcb.com` is the developer **portal / console**, NOT the API host.
- Empirically verified: a **valid** signature → `HTTP 403 {"code":403,...
  insufficient permissions...}`; a **wrong** signature → `HTTP 401 {"code":401,
  ...signature verify failed}`. So signing is correct.
- **The earlier 403 was an account-under-review state, not a missing
  permission.** The account is no longer under review, and all four Parts
  component endpoints (`getComponentInfos`, `getComponentLibraryList`,
  `getPrivateComponentLibrary`, `getComponentDetailByCode`) now show **Enabled**
  in the JLC console (Manage Apps → App Setting → Service → Parts). The component
  API should now return `200`.

## Run / test

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .            # core (requests only)
pip install -e ".[dev]"     # pytest, ruff
hendley ping                 # verify credentials + signing
pytest                      # tests live in tests/ (run once present)
ruff check .                # line-length 100, target py310
```

**If the `hendley` command isn't found** (venv not activated, or `pip install -e .`
didn't land the script on PATH — happens on fresh boxes / old pip-setuptools),
run it without installing, from the repo root:
`PYTHONPATH=src python -m hendley.cli <cmd>` (or `python -m hendley <cmd>`). Tests
likewise: `PYTHONPATH=src python -m pytest -q`.

The `.keys` RSA "Tokenization Key" block (for order-placement field encryption)
is currently **unused** — `config.py` does not parse it and no code consumes it.
It would only be needed if/when order placement is implemented.

## Conventions

- Keep dependencies minimal — core install is `requests` only. Push anything
  heavier into an optional extra.
- **Never hardcode or commit secrets.** Credentials load at runtime from
  `.keys`, which is git-ignored (along with `*.pem`, `*.key`). Use placeholders
  in any docs or examples.
- The API contract lives in `docs/api-reference.md` — update it alongside any
  new endpoint wrapper.

## Git rules (standing)

- **Never** run `git add -A` or `git add .` — stage files individually by path.
- **Never** commit or push unless the user explicitly asks. "fix" / "update" /
  "merge" do not imply commit or push; each git operation needs its own
  explicit instruction.
