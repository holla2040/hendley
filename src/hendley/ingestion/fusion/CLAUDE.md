# `src/hendley/ingestion/fusion/` — notes for Claude

Moved from the root `CLAUDE.md` on 2026-11-22. The root's "Invariants — never break these" still apply here.

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
    `electronics.Element`, fires `BOARD;` when needed; `EDIT .S1;` can request
    schematic context but may require an MCP reset after board context),
    joins `electronics.Package` for footprint names), `is_dnp()`, `Placement`,
    `natural_key()`.
  - `visual.py` — best-effort Refresh-time image evidence with no model call:
    enumerated schematic sheets plus populated-region details, clean board
    export, and dimensioned unresolved placement crops. Fusion dispatch is
    deferred, so capture settles the view,
    deletes stale output, and waits for a fresh PNG. `EXPORT IMAGE` omits the
    visible grid; crop bounds provide physical scale.
  - `parts_json.py` — the `DesignPart` model and `load_parts_json()` (the
    parts-export ingest contract); `extract_components()` is a **stub** kept
    for an eventual in-Fusion add-in.
