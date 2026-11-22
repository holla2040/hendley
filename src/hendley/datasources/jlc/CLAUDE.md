# `src/hendley/datasources/jlc/` — notes for Claude

Moved from the root `CLAUDE.md` on 2026-11-22. The root's "Invariants — never break these" still apply here.

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
  **`UNPROVABLE_COLUMNS` — the 48 columns the index publishes that are a
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
  **`components.category` and `components.subcategory` joined the list on
  2026-07-13** — the index's own CLASS columns, and they disagree with the
  catalog on the very parts in front of us. The catalog files BOTH SP3485s as
  `RS-485 / RS-422 ICs` and BOTH MB10S parts as `Bridge Rectifiers`; the index
  calls C2692302 a `Buffers / Drivers` and **C2886577 a `Diodes - General
  Purpose` — and C2886577 is an MB10S mounted on a real board here**. A plan
  sieving on `subcategory` would have rejected the part already on the board.
  Note which side is wrong: the CATALOG is consistent, the INDEX is not. That
  is exactly why the class comes from `secondTypeName` and never from a column.
  **The index's listing cap is a hard 100 rows and `limit=` will not raise it**
  (measured: `1N4148`, `LM358`, `AMS1117` all return exactly 100 with
  `limit=500`) — so never widen a net to a bare family name; keep the `package`
  on it and fire one request per package spelling.
  ⚠️ **A column is dead IN A CATEGORY, not everywhere.** `color` proves nothing
  on a 7-segment display and proves plenty on an LED; `has_i2c` is a lie on an
  accelerometer and is the whole point of an `io_expander`. `Server._stale_plan()`
  once tested a plan against a FLAT UNION of every category's dead columns and
  so condemned **16 categories' honest columns** — every `leds`, `ldos`,
  `microcontrollers`, `adcs`, `io_expanders` plan was discarded on sight and the
  agent re-asked from scratch on every search, for ever. It is **scoped to the
  plan's own category** now. Keep it that way.
