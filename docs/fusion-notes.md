# Fusion Electronics — introspection notes (hendrix)

Recorded from a **live** Autodesk Fusion session, reached from WSL2 Claude Code
**over plain HTTP** (JSON-RPC `POST`s) through a Windows port-forward (see the
README "Reading from Fusion Electronics" section). Active design at capture:
**`comet`** (schematic-only — no board yet).

> **This project talks to Fusion over HTTP only — there is NO MCP connector or
> client involved.** Fusion publishes a local HTTP endpoint (you enable it with
> the **Preferences > General > API > "Fusion MCP Server"** toggle — that Autodesk
> setting is the *only* thing here named "MCP"). From that point on it is just an
> HTTP API: you `POST` JSON-RPC to it with `curl`/`requests` and call the
> **`fusion_mcp_electronics_read`** tool (its literal name) over HTTP. Do **not**
> use Claude Desktop's "Autodesk Fusion" connector, an MCP client library, or
> `claude mcp add` — none exists in this project and none is needed.

## Talking to Fusion over HTTP — the full recipe (copy-paste, verified)

Plain `curl` over HTTP is all you need — but the JSON-RPC handshake has steps
that, if skipped, fail with confusing errors. **This is the layer that isn't
written down anywhere else, so every agent re-derives it (or hand-writes a
`bridge.py`).** Here it is, end to end, exactly as verified live. Don't read
source or invent your own client — run this.

**The rules that bite (each one cost a debugging session to rediscover):**
- **Never `127.0.0.1` from WSL.** Fusion listens on the *Windows* loopback; from
  WSL2 you must hit the **Windows host IP = the default gateway**
  (`ip route | grep default | awk '{print $3}'`, e.g. `172.17.64.1`). Needs the
  Windows port-forward in place — see README "Reading from Fusion Electronics"
  and the `listenaddress=0.0.0.0` gotcha in CLAUDE.md.
- **Capture `MCP-Session-Id` from the `initialize` *response header*** and resend
  it on **every** later request. Omit it → `{"error":"Missing MCP-Session-Id
  header"}`.
- **Send the `notifications/initialized` message before any `tools/call`.** A
  `tools/list`/`tools/call` first → `Session not initialized. Call 'initialize'
  first.`
- **Initialize exactly once, then reuse that SID.** Re-initializing churns the
  server's session and invalidates the id you captured.
- Send `Accept: application/json, text/event-stream` on every request.
- Every read returns its rows as a **JSON string** in `result.content[0].text`
  → parse that → `{ "items": [...], "pagination": {...} }`.

```bash
GW=$(ip route | grep default | awk '{print $3}')   # Windows host IP, NOT localhost
B="http://$GW:27182/mcp"
CT='-H Content-Type:application/json'
ACC='-H Accept:application/json,text/event-stream'

# 1) initialize ONCE — capture the session id from the RESPONSE HEADER
SID=$(curl -s -D - -o /dev/null $CT $ACC -X POST "$B" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"hendley","version":"1.0"}}}' \
  | tr -d '\r' | awk -F': ' 'tolower($1)=="mcp-session-id"{print $2}')

# 2) say "initialized" (REQUIRED before any tools/call)
curl -s $CT $ACC -H "MCP-Session-Id: $SID" -X POST "$B" \
  -d '{"jsonrpc":"2.0","method":"notifications/initialized"}' >/dev/null

# 3) call the read tool — reuse $SID on every call. Arg = the tool's `arguments`.
read_elec(){ curl -s $CT $ACC -H "MCP-Session-Id: $SID" -X POST "$B" \
  -d "{\"jsonrpc\":\"2.0\",\"id\":9,\"method\":\"tools/call\",\"params\":{\"name\":\"fusion_mcp_electronics_read\",\"arguments\":$1}}"; }
```

### Worked example — a part's JLC code (Part → Attribute → `LCSC`)

The workflow that matters: designator → live `object_id` → `LCSC`/`MPN`. Look the
oid up **live** every time (they change on every reload — never paste one from a
transcript).

```bash
# find R6's current object_id
OID=$(read_elec '{"entity_type":"electronics.Part","object":{"fields":["name","object_id"]}}' \
  | python3 -c 'import json,sys; d=json.loads(json.loads(sys.stdin.read())["result"]["content"][0]["text"]); print(next(i["object_id"] for i in d["items"] if i["name"]=="R6"))')

# read its attributes — MUST filter by part_object_id (unfiltered ⇒ empty, not an error)
read_elec "{\"entity_type\":\"electronics.Attribute\",\"object\":{\"filters\":[{\"property\":\"part_object_id\",\"op\":\"eq\",\"value\":$OID}]}}" \
  | python3 -c 'import json,sys; d=json.loads(json.loads(sys.stdin.read())["result"]["content"][0]["text"]); [print(i["name"],"=",i["value"]) for i in d["items"]]'
# → LCSC = C29719 ; MPN = 4D03WGJ0221T5E ; MANUFACTURER = UNI-ROYAL   (verified live)
```

To enumerate the whole BOM, drop the `name==R6` filter: read all `electronics.Part`
rows, then one `electronics.Attribute` read per `object_id`. Feed the `LCSC`
codes to `hendley detail`/`hendley stock` for live JLC stock/price.

## How the design is read

Fusion's HTTP endpoint exposes one read tool for Electronics (called over HTTP
via a `tools/call` `POST`):

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

## ⭐ The WRITE path — driving the EAGLE command line over HTTP (RESOLVED)

**Background / the old wrong conclusion.** The Fusion *Electronics object API*
(`adsk` / `fusion_mcp_electronics_read` / `…_update`) is read-only for our
purposes — you can read the design but not mutate part attributes/packages
through it. The only write channel is the **EAGLE-style command interpreter**
(the schematic command line, `.scr` scripts, ULPs). An earlier investigation
concluded the HTTP bridge **couldn't** reach that interpreter, because a bare

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

Run it via the `fusion_mcp_execute` tool (called over HTTP, same handshake as the
read recipe above). This makes the **entire write path scriptable from Python
over HTTP** — Hendley can generate a `.scr` and fire it into Fusion with no
manual step.

### `fusion_mcp_execute` — exact arguments (from the tool's live schema)

`tools/call` `name: "fusion_mcp_execute"`, `arguments`:

```jsonc
{
  "featureType": "script",          // required; enum: "script" | "document"
  "object": {                        // required
    "script": "<python source>"      // required for featureType=script
  }
}
```

- The `script` string **must define `def run(_context):`** — that function is the
  entry point Fusion calls. Anything it `print()`s becomes the tool's output;
  any exception it raises becomes the tool's error (so **don't** catch
  exceptions — you'd hide the failure).
- **Response envelope differs from the read tool.** `result.content[0].text` is a
  JSON string `{"message": "<script stdout>", "success": <bool>}` (the read tool
  returns `{"items":[...]}`). Verified live: a `print(app.version)` script
  returned `{"message":"2704.0.74\n","success":true}`.
- To fire an EAGLE command / `.scr`, the `run` body calls `executeTextCommand`
  with the `Electron.run "…"` wrapper (see above). `Electron.run` itself prints
  nothing, so `message` is empty on success — verify out-of-band (below).

**Copy-paste — fire a `.scr` over HTTP** (reuses `$B`/`$SID` from the read recipe;
builds the request in Python to avoid nested-quote escaping):

```bash
python3 - "$B" "$SID" <<'PY'
import json, sys, urllib.request
B, SID = sys.argv[1], sys.argv[2]
# the Electron.run wrapper is what routes into the electronics command interpreter
run = ('import adsk.core\n'
       'def run(_context):\n'
       '    app = adsk.core.Application.get()\n'
       '    app.executeTextCommand(\'Electron.run "script C:\\\\tmp\\\\changes.scr"\')\n')
payload = {"jsonrpc":"2.0","id":9,"method":"tools/call",
           "params":{"name":"fusion_mcp_execute",
                     "arguments":{"featureType":"script","object":{"script":run}}}}
req = urllib.request.Request(B, data=json.dumps(payload).encode(),
        headers={"Content-Type":"application/json",
                 "Accept":"application/json, text/event-stream",
                 "MCP-Session-Id":SID}, method="POST")
print(urllib.request.urlopen(req, timeout=30).read().decode())
PY
```

`featureType:"document"` also exists (`object.operation` enum
`open`/`close`/`save`, plus `fileId`, `userConfirmedSaveAndClose`,
`userConfirmedCloseWithoutSave`). `operation:"save"` would persist the doc over
HTTP — **not verified here, and it writes to the user's live design, so confirm
before using** (this is the "unsaved by default" caveat below).

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
