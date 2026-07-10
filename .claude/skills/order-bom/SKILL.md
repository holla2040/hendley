---
name: order-bom
description: Resolve a Fusion design's BOM into a JLCPCB-upload-ready CSV. Use when the user wants to generate/prepare/submit a BOM for a PCBA order, resolve parts for an order, or check what a design will actually mount. Interprets each part's spec (value/package/qualifiers), resolves it via the house-parts DB, live-verifies stock, runs alternates for gaps, records picks, and emits the CSV + resolution report.
---

# order-bom — resolve a design's specs into an orderable JLCPCB BOM

The user designs in **specifications** ("22k, 0603"), not part numbers. Most
parts carry no LCSC/MPN in the design; the mapping from spec to concrete part
lives in the **house-parts database** (`hendley db`), and the sourcing decision
happens *here*, at BOM time — never by editing the design.

**You are the interpreter.** The Python tools are deterministic (exact-key DB,
live API verify, CSV renderer); every judgment call — reading a spec string,
constructing the canonical DB key, weighing alternates — is yours.

## 1. Get the BOM

Either ingest a parts JSON (`hendley fusion PARTS.json --no-enrich` — contract
in `hendley.fusion`), or read the live design over the HTTP bridge (recipe:
`docs/fusion-notes.md` → "Talking to Fusion over HTTP"). For generic parts you
only need the `electronics.Part` rows — designator, value, and package come
natively; **no per-part attribute reads needed**. Read attributes (scoped by
live `part_object_id`) only for parts that may carry explicit `LCSC`/`MPN`.

## 2. Interpret each part (your judgment, not a parser's)

For every BOM line, build the canonical spec key `(kind, value, package,
qualifier)`:

- **kind** — from the designator prefix: R→resistor, C→capacitor, L→inductor,
  D→diode, LED→led, U→ic, J→connector, Y/X→crystal, F→fuse, SW→switch.
- **value** — canonicalize the string: `22K` ≡ `22k` ≡ `22kΩ` → `22k`;
  `0.1u` ≡ `100nF` → `100n`. Pick one form and use it consistently — the DB
  matches exact strings only.
- **qualifier** — `''` (empty) means "the house default". Only when the part
  itself states a tighter requirement — in its value string (`100n/100V`) or an
  attribute (`TOLERANCE=0.1%`) — extract it into the qualifier (value `100n`,
  qualifier `100V`). That forms a *distinct* spec key.
- **Explicit parts short-circuit**: a part carrying an `LCSC` attribute (or an
  MPN the user deliberately chose — ICs, connectors) skips spec resolution.
  Tag its line `source: "explicit"` and just live-verify the code.

## 3. Resolve each spec

1. `hendley db lookup --kind resistor --value 22k --package 0603` (add
   `--qualifier` when set; `--db` to override the default
   `$HENDLEY_DB` / `~/.hendley/parts.db`). Prints `{current, history}` JSON.
2. **Live-verify everything in one batch** — collect every candidate code
   (house parts + explicit codes) into a single
   `hendley detail C1 C2 ...` or `hendley stock` call. Cached
   `lastStock`/`lastPrice` in the DB is advisory only: **never order against
   it**, regardless of age.
3. **Gaps** — spec not in the DB, or its house part is out of stock / low for
   the order quantity:
   - With a seed part: `hendley alternates <code> --category <slug>
     --package "<exact spec>" --json` (slugs: `--list-categories`; package
     match is exact, no wildcards; numeric filters go over the verified
     `parameters[]` yourself, not query params).
   - No seed: discover via `--category components -p search="<tokens>"` (FTS),
     or ask the user for a starting point.
   - Present the trade-off and let the user pick. Bias: high stock =
     supply-chain-safe beats cheapest; same package is top priority; surface
     electrical caveats (rating loss on downsizing, dielectric, tolerance).
     Basic/Extended is display-only — never select on it.
4. **Record every pick**: `hendley db record --kind ... --value ... --package
   ... [--qualifier ...] --lcsc <code> [--mpn ...] [--manufacturer ...]
   [--design ...] [--note "why"]`. Promotion is automatic — the new pick
   becomes the house part; the old one stays as history. MPN = the detail row's
   `componentModel`; manufacturer per the `dataManualUrl` brand-slug trick in
   CLAUDE.md (never fabricate it).

## 4. Emit the BOM

Write the resolution JSON to `~/tmp/hendley_output/` (never the repo; `mkdir
-p` first). Contract (full shape in `hendley.bom`): one line per unique part —
`designators` (grouped), `comment` (the value), `footprint`, `lcsc`, `source`
(`db` | `pick` | `explicit`), optional `note`. Then:

```bash
hendley bom ~/tmp/hendley_output/<design>_resolution.json \
    -o ~/tmp/hendley_output/<design>_bom.csv --report
```

CSV columns are JLC's PCBA upload set (`Comment, Designator, Footprint, LCSC
Part #`). The report goes to stderr. **Exit 1 means unresolved lines — do not
let the user upload that CSV.** Show the user the report and where the CSV is.

## Rules

- Never edit the design for sourcing reasons. A footprint change is a design
  change — that's the separate `.scr` workflow, not this one.
- Never trust cached stock; the one batched live verify is mandatory.
- The tools gather and verify; the **user** approves picks (you recommend with
  reasoning). Record every approved pick so it never has to be made twice.
- All artifacts (resolution JSON, CSV, scratch) → `~/tmp/hendley_output/`.
