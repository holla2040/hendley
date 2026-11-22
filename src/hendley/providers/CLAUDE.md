# `src/hendley/providers/` — notes for Claude

Moved from the root `CLAUDE.md` on 2026-11-22. The root's "Invariants — never break these" still apply here.

- `src/hendley/providers/` — strategies select, adapters format:
  - `jlcpcb/` — `strategy.py` (jlc-mounted, live-verified), `adapter.py`
    (validate = blocking gate; export = bom.csv + cpl.csv + rotations),
    `bom_csv.py` (resolution→CSV renderer + gate), `order_files.py`
    (BOM/CPL builders behind `hendley pcba`).
  - `pcbway/` — the anti-coupling proof: MPN-based strategy
    (`requires_live_stock=False`, facts honestly `unverified` — no PCBWay
    API, no scraping) + the MPN BOM template adapter.
