---
name: order-bom
description: Resolve a Fusion design's BOM into a JLCPCB-upload-ready CSV. Use when the user wants to generate/prepare/submit a BOM for a PCBA order, resolve parts for an order, or check what a design will actually mount. Interprets each part's spec, resolves it against the ranked house AVL at the order's board count (silent substitution down the rank), batches every gap into one approval queue, records picks, and emits the CSV + release snapshot.
---

# order-bom — resolve a design's specs into an orderable JLCPCB BOM

The user designs in **specifications** ("22k, 0603"), not part numbers. Each
spec maps to a **House Part** carrying a ranked list of approved **Part
Choices** (the AVL) in the house-parts DB (`hendley db`). Sourcing happens
*here*, at BOM time — never by editing the design. The metric this workflow
optimizes: **human interruptions between "design done" and "CSV uploaded"** —
zero on the happy path, one batched approval otherwise.

**You are the interpreter.** The tools are deterministic (exact-key DB, the
rank-walking resolver, live verify, CSV renderer); every judgment call —
reading a spec string, composing the canonical key, weighing alternates,
recommending a pick — is yours. The resolver substitutes down the rank
silently; **you never interrupt for anything an approved rank-2 part covers.**

## 1. Get the BOM and the board count

- Ingest a parts JSON (`hendley fusion PARTS.json --no-enrich` — contract in
  `hendley.fusion`) or read the live design over the HTTP bridge (recipe:
  `docs/fusion-notes.md` → "Talking to Fusion over HTTP"). For generic parts
  the `electronics.Part` rows suffice (designator, value, package); read
  attributes (scoped by live `part_object_id`) only for parts that may carry
  explicit `LCSC`/`MPN`.
- **Ask the user for the Production Quantity (board count N) if they haven't
  said it.** Nothing resolves without it — "in stock" is undefined until
  required qty = designators × per-designator qty × N. Fold the question into
  your first reply; it is not a separate interruption.

## 2. Interpret each part (your judgment, not a parser's)

For every BOM line, build the canonical spec key `(kind, value, package,
qualifier)`:

- **kind** — from the designator prefix: R→resistor, C→capacitor, L→inductor,
  D→diode, LED→led, U→ic, J→connector, Y/X→crystal, F→fuse, SW→switch.
- **value** — canonicalize the string: `22K` ≡ `22k` ≡ `22kΩ` → `22k`;
  `0.1u` ≡ `100nF` → `100n`. Pick one form and use it consistently — the DB
  matches exact strings only.
- **qualifier** — `''` (empty) means "the house default". Only when the part
  itself states a tighter requirement — in its value string (`100n/100V`) or
  an attribute (`TOLERANCE=0.1%`) — extract it into the qualifier (value
  `100n`, qualifier `100V`). That forms a *distinct* spec key.
- **Explicit parts short-circuit**: a part carrying an `LCSC` attribute (or an
  MPN the user deliberately chose — ICs, connectors) skips spec resolution.
  Give its line `lcsc` instead of `spec`; the resolver verifies it live.

## 3. Resolve — one command, one batched live verify

Compose the resolve request (contract in `hendley.resolve`; artifacts to
`~/tmp/hendley_output/`, `mkdir -p` first): `design`, `productionQuantity`,
and one line per unique part — `designators` (grouped), `comment`,
`footprint`, `quantityPer` (default 1), and `spec` *or* `lcsc`. Then:

```bash
hendley resolve ~/tmp/hendley_output/<design>_request.json \
    -o ~/tmp/hendley_output/<design>_resolution.json
```

The resolver looks up each spec's AVL, live-verifies **every** candidate code
in one batched call (refreshing the advisory cache), and rank-walks each line:
first active choice with live stock ≥ required qty wins. Rank > 1 selections
are **substitutions — silent, self-noted, reported later; do not stop for
them.** The escalation report lands on stderr.

- **Exit 0** — all lines resolved. Go to step 5.
- **Exit 1** — some lines escalated. Go to step 4 (once).

## 4. The batched approval queue (the one interruption)

Handle **all** escalations in a single sitting — never one at a time. For
each escalation (its `reason` and per-choice live stock are in the resolution
JSON's `escalations`):

- **`no-part-choices`** (first use of a spec) — discover candidates:
  `hendley alternates <seed> --category <slug> --package "<exact spec>"
  --json`. The positional seed code is **required** (it only anchors the
  report's reference row — candidates come from the category/filters), so
  when the spec has no known part, seed with any similar code already in
  hand (another spec's house part, an explicit part from this design) plus
  `--category components -p search="<tokens>"` (FTS) — or ask the user for
  a starting point. Package match is exact, no wildcards; numeric filters
  go over the verified `parameters[]` yourself, not query params.
- **`avl-exhausted`** — same, seeded from the escalation's best-known choice
  (its live stocks are already in hand).
- **`insufficient-stock` / `not-in-catalog`** (explicit parts) — the user
  chose these deliberately; present the problem and let them decide (wait,
  substitute, or consign).

Present **one combined queue**: per spec, the verified trade-off and your
recommendation. Bias: high stock = supply-chain-safe beats cheapest; same
package is top priority; surface electrical caveats (rating loss on
downsizing, dielectric, tolerance). Basic/Extended is display-only — never
select on it.

**Record every approved pick** (promotion to rank 1 is the default; existing
choices shift down and stay approved — that is the AVL deepening):

```bash
hendley db record --kind resistor --value 22k --package 0603 --lcsc C4190 \
    [--rank N] [--mpn ...] [--manufacturer ...] [--design ...] [--note "why"]
```

MPN = the detail row's `componentModel`; manufacturer per the `dataManualUrl`
brand-slug trick in CLAUDE.md (never fabricate it). Then **re-run step 3** —
it must exit 0 now.

AVL maintenance verbs when the user asks for them: `hendley db rerank`
(reorder preferences) and `hendley db remove` (pull a part off the list;
audited, never deleted). `hendley db lookup` prints `{housePart, history}` —
the ranked choices plus the audit trail.

## 5. Emit — CSV, report, release snapshot

```bash
hendley bom ~/tmp/hendley_output/<design>_resolution.json \
    -o ~/tmp/hendley_output/<design>_bom.csv --report
```

CSV columns are JLC's PCBA upload set (`Comment, Designator, Footprint, LCSC
Part #`). The report (stderr) lists sources, required quantities, and every
check — **show the user the substitutions**; they were resolved silently and
this is where they surface. **Exit 1 means blockers (unresolved lines or
error-severity checks) — do not let the user upload that CSV.**

A clean `-o` emit also writes `<design>_bom.<UTC>.snapshot.json` beside the
CSV — the immutable record of what was actually ordered (rank used, live
stock, prices, N). Tell the user where it is; suggest keeping it with the
order records. It is the answer to "what did we mount in this rev?" months
later — the DB will have moved on.

## Rules

- Never edit the design for sourcing reasons. A footprint change is a design
  change — that's the separate `.scr` workflow, not this one.
- Never trust cached stock (`lastStock`/`lastPrice` are advisory); the
  resolver's one batched live verify is the truth this order stands on.
- Substitutions within the approved AVL are silent by design — report them
  post-hoc, don't ask permission. **New approvals are the user's call**: you
  gather, verify, and recommend; they pick; you record it so the question is
  never asked twice.
- One approval queue per order, not one question per part.
- All artifacts (request, resolution, CSV, snapshot) → `~/tmp/hendley_output/`.
