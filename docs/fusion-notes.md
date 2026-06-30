# Fusion Electronics — introspection notes (hendrix)

Recorded from a **live** Autodesk Fusion session via the Fusion MCP server,
reached from WSL2 Claude Code over a Windows port-forward (see the README
"Fusion MCP from WSL" section). Active design at capture: **`comet`**
(schematic-only — no board yet).

## How the design is read

The Fusion MCP exposes one read tool for Electronics:

- `fusion_mcp_electronics_read(entity_type, object?)`
  - `entity_type`: one of `electronics.<Class>` (e.g. `electronics.Part`,
    `electronics.Attribute`, `electronics.Device`, `electronics.Schematic`).
  - `object`: optional `{ fields[], filters[{property,op,value}], pagination{limit,offset} }`.
  - Per-class field/filter schema lives at
    `resource://mcp.electronics_schema_<snake_class>` (e.g.
    `..._schema_part`, `..._schema_attribute`). `tools/list` advertises
    `fusion_mcp_electronics_read`, `fusion_mcp_execute`, `fusion_mcp_read`,
    `fusion_mcp_update`.

Requires an active Electronics document. Read returns rows as a JSON string in
`result.content[0].text` → `{ "items": [...], "pagination": {...} }`.

## Object model (what we walk)

- `electronics.Part` = a placed component **instance** on the schematic.
  Columns: `object_id`, `name` (designator, e.g. `U1`/`R1`), `value`
  (e.g. `22k`, or a supply-net name like `GND` for power symbols),
  `module_object_id`, `deviceset_object_id`, `device_object_id`,
  `package3d_object_id`. **No part-number columns inline** — those are
  attributes (below). `comet` has 50 Part rows, many of which are GND/supply
  pseudo-parts (`value` = `GND`, `package3d_object_id` = 0).
- `electronics.Attribute` = name/value metadata attached to a part. Filter by
  **`part_object_id`** (`{property:"part_object_id", op:"eq", value:<Part.object_id>}`)
  to get a part's metadata, including library-defined defaults. Columns:
  `name`, `value`, `part_object_id`, `element_object_id`, `instance_object_id`,
  `constant`, `default_value`, `display`.
  - ⚠️ **The reader is part-scoped — you MUST pass a `part_object_id` filter.**
    A `name`-only filter (e.g. `name=LCSC`) or an unfiltered read returns
    **`{"items":[]}`** — empty, not an error. So "the attribute reader doesn't
    surface JLC attrs" is a **myth**: `LCSC`/`MPN`/`MANUFACTURER` read back fine
    once you scope to the live part. Verified on `comet` R1:
    `LCSC=C31850`, `MPN=0603WAF2202T5E`, `MANUFACTURER=UNI-ROYAL`.
  - ⚠️ **`object_id`s are NOT stable across sessions.** They are reassigned every
    time the design reloads (R1 was `2812` one session, `11225` the next). Always
    re-read `electronics.Part` for the *current* `object_id` in the same session
    you use it — never reuse an ID from a transcript or a prior run.

## ⭐ Where the JLCPCB code lives (the open question — RESOLVED)

The JLCPCB / LCSC `Cxxxx` code is a **part attribute named `LCSC`**.
The manufacturer part number is the **`MPN`** attribute. Observed on `comet`:

| Designator | `LCSC` (→ jlcCode) | `MPN` (→ manufacturerPart) | `MANUFACTURER` |
|-----------|--------------------|----------------------------|----------------|
| U1 | `C52717` | `STM8S003F3P6TR` | STMicroelectronics |
| U2 | `C84817` | `MT3608` | XI'AN Aerosemi Tech |
| R1 | `C2907015` | `FRC0603F2202TS` | FOJAN |

So **parts carry the real `Cxxxx` LCSC code directly** — Hendley's
code-based enrichment (`getComponentDetailByCode`) works with no MPN→code
mapping step. (If a part ever lacks `LCSC` but has `MPN`, that part would need
an MPN search path, which is not yet wrapped — see `docs/api-reference.md`.)

### Attribute-name mapping to the Hendley contract

| Fusion attribute | Hendley `DesignPart` field |
|------------------|---------------------------|
| `LCSC`           | `jlc_code` (`jlcCode`)    |
| `MPN` (or `MP`)  | `manufacturer_part` (`manufacturerPart`) |
| `MANUFACTURER` (or `MF`) | kept in `attributes`  |
| `PACKAGE`        | `package`                 |
| Part `value`     | `value`                   |
| Part `name`      | `designator`              |

Caveats seen in real data:
- Attribute names are **not fully standardized** across library parts. U2
  (MT3608) uses `MP`/`MF` **in addition to** `MPN`/`MANUFACTURER`, plus extra
  SnapEDA/DigiKey fields (`CHECK_PRICES`, `SNAPEDA_LINK`, `DIGIKEY_PART_NUMBER`,
  `PRICE`, `AVAILABILITY`, `DESCRIPTION`). The extractor reads `LCSC` for the
  code and falls back `MPN`→`MP` for the MPN.
- `PACKAGE` is sometimes a placeholder (`"Package "`); treat as best-effort.
- GND / supply symbols and the title-block/logo part (`U$1`, value `v1.0`)
  have no `LCSC`/`MPN` and are excluded from the BOM extraction.

## Design name

`electronics.Schematic` row `name` is a temp path ending in `comet sch.sch`;
the design/document name is taken as **`comet`**.

## ⭐ The WRITE path — driving the EAGLE command line from Python/MCP (RESOLVED)

**Background / the old wrong conclusion.** The Fusion *Electronics object API*
(`adsk` / `fusion_mcp_electronics_read` / `…_update`) is read-only for our
purposes — you can read the design but not mutate part attributes/packages
through it. The only write channel is the **EAGLE-style command interpreter**
(the schematic command line, `.scr` scripts, ULPs). An earlier investigation
concluded the MCP bridge **couldn't** reach that interpreter, because a bare

```python
app.executeTextCommand("script C:\\tmp\\my.scr")   # ❌ RuntimeError: There is no command script
```

routes to Fusion's **core** text-command channel (where `GRID`, `UPDATE`,
`SCRIPT`, … don't exist), not the electronics one. That left a manual
*File → Execute Script* as the only way to apply changes — breaking headless
automation.

**The fix (from an Autodesk forum reply, verified here).** Wrap the electronics
command in **`Electron.run "…"`**. `Electron.run` *is* a core text command, and
it dispatches its string argument into the **electronics** command interpreter:

```python
import adsk.core
app = adsk.core.Application.get()
app.executeTextCommand('Electron.run "script C:\\tmp\\changes.scr"')
```

Run it via the MCP `fusion_mcp_execute` tool (`featureType:"script"`, a
`def run(_context):` that calls `executeTextCommand`). This makes the **entire
write path scriptable from Python/MCP over the WSL bridge** — Hendley can generate
a `.scr` and fire it into Fusion with no manual step.

**What we verified (live, on `comet sch`):**

| Call | Result |
|------|--------|
| `executeTextCommand('script C:\\tmp\\my.scr')` (bare) | ❌ `RuntimeError: There is no command script` (core channel) |
| `executeTextCommand('WINDOW FIT')` (bare) | matched **core** "Window" help — wrong channel |
| `executeTextCommand('GRID')` (bare) | ❌ `There is no command GRID` (core channel) |
| `executeTextCommand('Electron.run "WINDOW FIT"')` | ✅ `''` — accepted, no error |
| `executeTextCommand('Electron.run "script C:\\tmp\\my.scr"')` | ✅ ran the `.scr`; `ATTRIBUTE R1 MPN 'TEST'` landed (seen in UI + on read-back) |
| `executeTextCommand('Electron.run "EXPORT PARTLIST C:\\tmp\\partlist.txt"')` | ✅ wrote a real 3982-byte file — proves side effects land |

**Gotchas / rules for future agents:**

- **`Electron.run "…"` returns `''` on success — there is NO echo / return value.**
  You cannot read the result of the command back through `executeTextCommand`.
  Verify out-of-band: re-read with `electronics.Attribute`
  (scoped by the live `part_object_id`, see above), or have the `.scr` do an
  `EXPORT PARTLIST <file>` you read from disk.
- **Quote/escape carefully.** The whole thing is one string with nested quotes.
  In a Python literal: outer single quotes, inner escaped double quotes, and
  doubled backslashes for the Windows path —
  `'Electron.run "script C:\\tmp\\changes.scr"'`.
- **Paths are Fusion-host paths.** Fusion runs on Windows; the `.scr` must be a
  path Fusion can read. WSL `~/tmp/x.scr` ↔ Windows `C:\tmp\x.scr` because
  `~/tmp` is a symlink to `/mnt/c/tmp` on this box (`hendrix`). Write the file
  from WSL, pass the `C:\…` form to `Electron.run`.
- **A `.scr` stops at the first failing command** — if one designator name is
  wrong, everything after it silently doesn't run. Keep scripts small / verify.
- **Unsaved by default.** Changes applied this way are *not* saved to the cloud
  doc automatically — reopening the design reverts them (this is how the `TEST`
  write self-cleaned). Save in Fusion to persist.
- The **schematic `value`** (e.g. 220 Ω → 330 Ω) is also settable this way —
  `Electron.run "VALUE R6 330"` — so even the value change Hendley used to defer
  to a manual step can now go in the `.scr`/command stream.
