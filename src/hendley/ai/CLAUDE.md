# `src/hendley/ai/` — notes for Claude

Moved from the root `CLAUDE.md` on 2026-11-22. The root's "Invariants — never break these" still apply here.

- `src/hendley/ai/` — the interpretation tier (ADR-0005/0006/0007):
  `Interpreter` protocol + `codex_cli.py` (default: ephemeral, read-only
  `codex exec`, rides the user's Codex login; `HENDLEY_CODEX_BIN` and optional
  `HENDLEY_CODEX_MODEL` overrides). `HENDLEY_INTERPRETER=claude` retains the
  `claude_cli.py` compatibility backend. **Refresh is cache-only:** it
  reads Fusion, applies exact/deterministic/cached knowledge, and never launches
  an agent process. An uncached unresolved part is judged only when the engineer
  opens its red/yellow panel; that one lazy read supplies the SpecKey and is
  cached for every later Refresh. Family panels go directly to their bounded
  family discovery instead of generic interpretation. Judgments, all cached:
  `interpret_part` (ad-hoc values: `47u/50V` → value `47u`, qualifier `50V`),
  `interpret_footprint` (**normalize to catalog packages**: `D-SOD323` →
  `SOD-323`, `C-0603` → `0603`; verbatim only when nothing standard is
  recognizable, e.g. `C-E-5`. **It is given the footprint's GEOMETRY, not just
  its name** — `SO16` cannot say whether the body is 3.9 mm or 7.5 mm, and those
  are different catalog packages holding different parts; the library's own
  headline, `Small Outline package 150 mil`, says it outright),
  **`read_family`** (ADR-0008 — **the only judgment allowed the WEB**, via
  WebSearch (`--allowedTools WebSearch` on the claude backend; `--search` on the
  default codex backend): a family + the footprint under it → the complete
  part numbers that fit THIS land (the datasheet's suffix decoder: ULN2003 `D` =
  3.9 mm SOIC, `NS` = 5.3 mm SOP), the class (a LABEL, never a filter), and the
  **traps** — the lookalikes that fit the same land and are not the same part:
  `PCF8574A` is a different I²C address, `MB6S` is 600 V where `MB10S` is 1000 V,
  `MAX485` is a +5 V part on the identical SOIC-8 pinout. Cached per
  (family, footprint): what a suffix MEANS does not change. Empty `partNumbers`
  is an honest answer — the catalog sweep still finds the parts, including the
  house brands the web never names),
  **`plan_search`** (the engineer's words → a
  catalog query plan: `net` + `sieve` + `say`; the prompt carries the MEASURED
  index facts — which params actually filter, and **ONE TERM PER FIELD**, since
  an index column and a catalog parameter differing only in case are the same
  field — because a hallucinated param is silently ignored and looks like a
  filter, and a duplicated one rejects every part alive),
  and **`derive_key`** (the AVL's SpecKey for a pick, from the design line +
  search words + the picked part's verified facts; leaves `value` empty when
  the part has none — never invents one).
  Interpretation cache identity includes meaningful schematic attributes, so
  `VALUE=10V, TYPE=Zener` cannot reuse the reading for bare `VALUE=10V`.
  Administrative/import attributes (`LCSC`, `MP`, `MF`, etc.) do not invalidate
  electrical meaning. Every judgment is
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
  agent will believe it. Written so far (`ls docs/parts/`): aluminium electrolytics
  (`aluminium-electrolytic-capacitors.md`) and chip resistors
  (`chip-resistors.md` — the `Resistance` name collision, `tolerance_fraction`
  is a FRACTION and wants `lte`, and **never sieve on power**), ordinary,
  Schottky/TVS and zener diodes, transistors, and ICs by family MPN.
