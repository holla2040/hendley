# `src/hendley/resolver/` — notes for Claude

Moved from the root `CLAUDE.md` on 2026-11-22. The root's "Invariants — never break these" still apply here.

- `src/hendley/resolver/orchestration/search.py` — **the search executor
  (ADR-0007): a coarse net, then an honest sieve.** jlcsearch honours only
  `package` + one value param (`resistance`/`capacitance`) and **silently
  ignores every other param** — ask it for X7R/25V and it returns a 100n/50V
  X5R part with no complaint, so a query proves NOTHING. (Measured 2026-07-13:
  the keyword table `components` honours **`search` + `package` + `is_basic`**,
  and **silently ignores `stock_min`** — `stock_min=999999999` still returns
  every row. That `package` is what makes a FAMILY searchable: `search=ULN2003`
  gives 64 rows across five packages, `&package=SOIC-16` gives the 11 that fit
  the land.) **Both bugs that made an FTS search prove nothing are fixed**:
  `_query()` dropped every net param but `search`, and `_full_sieve()` returned
  early unless the mode was `parametric`, so the package was never re-asserted.
  `run_search()` fires
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
