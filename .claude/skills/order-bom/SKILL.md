---
name: order-bom
description: Resolve a Fusion design's BOM into a JLCPCB-upload-ready CSV. Use when the user wants to generate/prepare/submit a BOM for a PCBA order, resolve parts for an order, or check what a design will actually mount. Interprets each part's spec, resolves it against the ranked house AVL at the order's board count (silent substitution down the rank), batches every gap into one approval queue, records picks, and emits the CSV + release snapshot.
---

# order-bom — resolve a design's specs into an orderable JLCPCB BOM

> **The app is the primary interface for this flow** (`hendley app` — the
> single-page order workbench does everything below visually). Drive this
> skill when the user prefers the conversation, is headless, or asks you to.
> Same library, same documents, same results.

The user designs in **specifications** ("22k, 0603"), not part numbers. Each
spec maps to a **House Part** carrying a ranked list of approved **Part
Choices** (the AVL) in the house-parts DB (`hendley db`). Sourcing happens
*here*, at BOM time — never by editing the design. The metric this workflow
optimizes: **human interruptions between "design done" and "CSV uploaded"** —
zero on the happy path, one batched approval otherwise.

**You are the interpreter.** The tools are deterministic (exact-key DB, the
rank-walking resolver, live verify, constraint filter, candidate ranker, CSV
renderer); the judgment calls — reading a spec string, composing the
canonical key, weighing the ranked candidates, recommending a pick — are
yours. The resolver substitutes down the rank silently; **you never
interrupt for anything an approved rank-2 part covers.** The AVL rank is
deliberate (ADR-0001): you never rerank without the user saying so.

## 1. Get the BOM and the board count

- Read the live design over the HTTP bridge (recipe: `docs/fusion-notes.md`)
  or ingest a parts JSON (`hendley fusion PARTS.json --no-enrich`).
- **Ask the user for the Production Quantity (board count N) if they haven't
  said it.** Nothing resolves without it — required qty = designators ×
  per-designator qty × N. Fold the question into your first reply; it is not
  a separate interruption.

## 2. Compose the Requirements BOM (your judgment, not a parser's)

Write the request JSON per the canonical contract (`hendley.domain.model` —
`requirementsBomVersion: 1`). Per line, **exactly one selection mode**:

- `spec: {kind, value, package, qualifier}` — generic parts, resolved via
  the AVL. kind from the designator prefix (R→resistor, C→capacitor,
  L→inductor, D→diode, LED→led, F→fuse, SW→switch); value canonicalized
  (`22K`→`22k`, `0.1u`→`100n`); qualifier only for beyond-house-default
  needs (`"1%"`, `"100V"`) — empty means the house standard.
- `lcsc: "Cxxxx"` — the design pins an exact part: verify-only, never
  substituted.
- `mpn` (+ `manufacturer`) — manufacturer-constrained (JLC can't verify by
  MPN; these escalate under the jlcpcb provider).

Parts the design marks do-not-populate get `"dnp": true` — they are carried
and reported, excluded from resolution and the order files. Do NOT omit them.

Write artifacts to `~/tmp/hendley_output/`, never the repo root.

## 3. Resolve (one command, one batched verify)

```bash
hendley resolve ~/tmp/hendley_output/request.json \
  -o ~/tmp/hendley_output/resolution.json \
  --queue ~/tmp/hendley_output/queue.json
```

Exit 0 → everything resolved (substitutions are silent, reported on stderr —
relay them post-hoc). Exit 1 → escalations; `queue.json` already carries
**discovered, live-verified, constraint-filtered, ranked candidates** with
`why` lists for every escalated line (for kinds without an automatic
category mapping, run `hendley alternates` yourself — the entry's
`discovery.note` says so).

## 4. The ONE approval queue

Present every escalation in a single batch with a recommendation per line
(the ranker's order is a good default — user's bias: high inventory beats
cheapest, same package first, surface electrical caveats yourself). Record
each approved pick:

```bash
hendley db record --kind resistor --value 22k --package 0603 \
  --lcsc C_NEW --mpn 0603WAF2202T5E --design comet --note "C_OLD out of stock"
```

(`--mpn` is the neutral identity; `--lcsc` the JLC ref — give both when you
have both.) Then re-run step 3 — it must come back clean.

## 5. Emit

```bash
hendley bom ~/tmp/hendley_output/resolution.json \
  -o ~/tmp/hendley_output/order_bom.csv --report
```

Exit 0 → CSV + resolution report + **release snapshot** written (the
immutable what-was-ordered record). Exit 1 → blockers listed — do NOT
upload; fix and re-resolve. (`--provider pcbway` renders the MPN template
instead.) For the full pcba order files (BOM + CPL from the live design),
`hendley pcba` remains the one-command path.

## Rules

- Never edit the design to fix sourcing (no `.scr`, no VALUE — that's the
  part-change workflow, a design decision).
- Never trust cached/advisory stock (`lastStock`, jlcsearch numbers) for an
  order — only the resolver's live verify counts.
- Substitutions are reported, not asked about. One queue per order.
- Never rerank an AVL without an explicit user decision.
