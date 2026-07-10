# Handoff — `house-parts-bom` branch (written 2026-07-10)

For the next agent picking this up. Current state: **the ranked-AVL sourcing
design is fully implemented, self-reviewed, and green (86 tests). It awaits
Craig's review — nothing here is merged to `main`.**

## What this branch is

Hendley pivoted from a single-current-part house DB to the industry AVL model:
each spec (`kind, value, package, qualifier`) names a **House Part** carrying a
**ranked list of approved Part Choices**; orders resolve by rank-walking that
list against live stock at a **Production Quantity**, substituting silently
down the rank, and only escalating to a human when a whole list fails — one
batched approval queue per order. Emits write an immutable **release
snapshot** beside the CSV.

The authoritative documents, in reading order:

1. **`docs/hendley-sourcing-design.md`** — the AGREED design (six signed-off
   decisions, object model, workflow, scope boundaries). Do not re-litigate
   its decisions; Craig ratified them explicitly on 2026-07-09.
2. **`docs/overnight-decisions.md`** — the judgment calls made during the
   autonomous implementation run, ⚠️-marked items first. Some await Craig's
   ratification (see "Open items"). Craig may delete this file after review.
3. **`CLAUDE.md`** — updated for the new modules/commands; its standing rules
   all apply to you (see "Rules that bind you" below).
4. **`docs/Hendley Sidecar - Functional Spec.md`** — a reviewed/annotated
   historical document. Superseded by the design doc; kept as the review
   record. Don't build from it.

## The commit series (all on this branch, in order)

| Commit | Content |
|---|---|
| `3bddb3b` | design doc (AGREED) + annotated Sidecar spec |
| `ef8ec63` | partsdb schema v2: House Parts, ranked Part Choices, audit, v1→v2 migration |
| `ea52d6f` | `db` CLI: rank-aware lookup/record, new `rerank`/`remove` |
| `1d90376` | resolver (`resolve.py` + `hendley resolve`): batched verify, rank-walk, escalations |
| `094b7b4` | Production Quantity / requiredQty through the BOM report |
| `0b300eb` | BOM Checks gate the emit (error severity → exit 1) |
| `e9ec4fb` | release snapshots (`snapshot.py`) |
| `808f7dd` | `order-bom` skill rewritten for the AVL flow |
| `eaa9450` | README + CLAUDE.md docs |
| `cf3a73a` | self-review fixes (10 confirmed findings, incl. an atomic-migration data-loss fix) |

Each commit is independently revertible; that's deliberate — Craig reviews
per-commit.

## Rules that bind you (do not assume my authorizations)

- **Never commit or push without Craig's explicit instruction.** The
  overnight run's per-task commit authorization was one-run-only and is
  **expired**. Same for "best judgment on contested questions" — default back
  to asking.
- Standing CLAUDE.md rules: never edit the design for sourcing reasons; the
  agent supplies canonical spec keys (no normalization in Python); never
  order against cached stock; artifacts to `~/tmp/hendley_output/`, never the
  repo root; stage files individually (never `git add -A`).
- Craig's working style: goes with clear recommendations; insists on
  design-before-code ("we're coming up with the work to be done, not doing
  the work") — when he's in design mode, do not write code.

## Environment gotchas (this box, WSL2 `holla@…:~/hendley`)

- **No `.keys` file at the repo root** — every live-API command (`ping`,
  `detail`, `resolve`, `db refresh`) fails with a missing-keys error. The
  final live smoke test of the run was skipped for this reason. Ask Craig
  where the credentials live before exercising anything online.
- **No pip / no ruff** — system Python 3.12, apt-packaged pytest 7.4.4. Run
  tests as `PYTHONPATH=src python3 -m pytest -q`; run the CLI as
  `PYTHONPATH=src python3 -m hendley.cli <cmd>`. Lint was held manually
  (line-length 100, py310); run `ruff check .` once tooling exists.
- Craig's real DB (`~/.hendley/parts.db`) **migrates automatically to schema
  v2 on first open by the new code** — atomic, retryable, old table kept as
  `house_parts_v1` for rollback. Tests only ever touch temp DBs; keep it
  that way.

## Open items, in priority order

1. **Craig's review of the series** — pending. The ⚠️ items in the decision
   log he should ratify or reverse:
   - `spec` + `lcsc` on one resolve-request line is **rejected** (alternative:
     fall back to the explicit code when the AVL fails — small change in
     `ResolveLine.from_dict` / `_resolve_spec_line`).
   - `quantityPer < 1` is **rejected**; DNP is not modeled (design §2) —
     unmounted lines are omitted from the request. If Craig wants DNP
     modeling, that's a design addition, not a bugfix.
2. **Live end-to-end order** — the first real use: a design read over the
   Fusion bridge → resolve request → `hendley resolve` → approval queue →
   `hendley bom`. Needs `.keys`. The `order-bom` skill is the recipe. Expect
   first-order friction: every spec will escalate `no-part-choices` until the
   AVL populates.
3. **Deferred micro-efficiency** (deliberately skipped; all sub-millisecond
   on this data): `list_parts` N+1 query; per-code commit in the
   advisory-cache refresh loops (`resolve.py` + `_cmd_db_refresh` — an
   `update_verified_many()` would also dedup the two loops); COUNT query in
   `record`/`rerank`.
4. **Out of scope by design (§4)** — do not build without a new decision from
   Craig: feeder-fee/consolidation optimizer (the snapshot's per-line data is
   designed to feed it), voice intake, multi-supplier (Octopart/Nexar),
   lifecycle/EOL data, order-placement API.

## Verification recipe

```bash
PYTHONPATH=src python3 -m pytest -q          # 86 passed as of cf3a73a
PYTHONPATH=src python3 -m hendley.cli db record --db /tmp/t.db \
    --kind resistor --value 22k --package 0603 --lcsc C31850
PYTHONPATH=src python3 -m hendley.cli db lookup --db /tmp/t.db \
    --kind resistor --value 22k --package 0603   # → {housePart:{choices:[…]}, history:[…]}
# offline emit gate: hendley bom <resolution.json> --report  (exit 1 on blockers)
```

The resolver can be exercised offline only through the tests (it needs a live
client otherwise) — `tests/test_resolve.py` has a `FakeClient` pattern to copy.

## Memory

Session memories exist at the project memory dir (`user-working-style`,
`overnight-avl-run-authorization`) — the authorization one is historical
record, not a live grant.
