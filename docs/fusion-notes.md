# Fusion Electronics — introspection notes (hendrix)

## Library identity carried into requirements

The live reader preserves device-set URN, library version, device/package
variant, footprint name/headline, value, and meaningful electrical attributes
as `libraryIdentity`. Fusion object ids, designators, and design names are never
global identity. Missing URNs, local modifications, version differences, and
mixed grouped identities are suggestion-only.

Recorded from **live** Autodesk Fusion sessions, reached from WSL2 Claude Code
**over plain HTTP** (JSON-RPC `POST`s) through a Windows port-forward (see
"Reaching Fusion from WSL2" below). Reference design: **`comet`**
(schematic-only at first capture; a board was added later — see the BOARD
section). Part values quoted below are session-specific examples — the design
has changed across captures, so read them as shapes, not current data.

> **This project talks to Fusion over HTTP only — there is NO MCP connector or
> client involved.** Fusion publishes a local HTTP endpoint (you enable it with
> the **Preferences > General > API > "Fusion MCP Server"** toggle — that Autodesk
> setting is the *only* thing here named "MCP"). From that point on it is just an
> HTTP API: you `POST` JSON-RPC to it with `curl`/`requests` and call the
> **`fusion_mcp_electronics_read`** tool (its literal name) over HTTP. Do **not**
> use Claude Desktop's "Autodesk Fusion" connector, an MCP client library, or
> `claude mcp add` — none exists in this project and none is needed.

## Reaching Fusion from WSL2 — the Windows port-forward

If you run Hendley on the same Windows machine as Fusion, `http://127.0.0.1:27182`
just works. If you run it under **WSL2**, Windows loopback isn't reachable across
the NAT boundary, so forward the port on the **Windows** side (elevated
PowerShell).

> ⚠️ **Use the WSL gateway IP as `listenaddress`, NOT `0.0.0.0`.** A `0.0.0.0`
> listener on `27182` sits in front of the *same* loopback port Fusion's server
> and the Claude Desktop "Autodesk Fusion" connector use, and hijacks their
> `127.0.0.1:27182` traffic — Fusion appears to "connect then close
> unexpectedly" and **Claude Desktop stops connecting**. Bind the WSL-facing
> gateway address specifically so loopback is never intercepted.

First get the WSL→Windows gateway IP **from inside WSL** (it is also the address
WSL uses to reach Windows):

```bash
ip route | grep default | awk '{print $3}'   # e.g. 172.17.64.1
```

Then, on Windows (elevated), forward that address only — substitute your gateway
IP for `172.17.64.1`:

```powershell
netsh interface portproxy add v4tov4 listenaddress=172.17.64.1 listenport=27182 connectaddress=127.0.0.1 connectport=27182
```

From WSL, reach Fusion at `http://172.17.64.1:27182/mcp`. The gateway IP can
change across WSL restarts — re-check it with the `ip route` line above and
re-add the rule if Fusion becomes unreachable.

**Health check / troubleshooting.** On Windows, `curl http://127.0.0.1:27182/mcp`
should return an instant JSON error when Fusion's server is healthy —
`{"error": "Not Found"}` on older builds, `{"error": "Server does not offer an
SSE stream at this endpoint"}` on newer ones (observed 2026-07-10). Either body
means healthy; only a hang or "connection closed unexpectedly" is bad. (In
PowerShell, `curl` is `Invoke-WebRequest` and paints non-2xx responses as red
exceptions — read the body, not the color.)
If it (or Claude Desktop) "closes the connection unexpectedly," a bad `0.0.0.0`
forward is almost certainly hijacking loopback — delete it and the symptom
clears:

```powershell
netsh interface portproxy show all     # look for a 0.0.0.0 ... 27182 entry
netsh interface portproxy delete v4tov4 listenaddress=0.0.0.0 listenport=27182
```

> ⚠️ **Tailscale hijacks loopback the same way (verified 2026-07-15).** With
> Tailscale running, the gateway forward accepts nothing — WSL connects and gets
> `000`, and everything else (rule, firewall, Fusion listener) looks correct.
> Same failure mode as a stray `0.0.0.0` rule: Tailscale sits in front of the
> Windows loopback the forward relies on. Turn it off on Windows and the bridge
> comes straight back:
>
> ```powershell
> tailscale down
> ```

**When `add` "succeeds" but nothing binds.** `netsh ... add` writes the rule to
the registry, but the listener socket only binds if IP Helper is running and the
`listenaddress` is a live interface address. Verify with:

```powershell
netstat -ano | findstr :27182
```

Healthy shows **two** `LISTENING` lines — `127.0.0.1:27182` (Fusion) and
`<gateway>:27182` (the proxy). Only the `127.0.0.1` line means the proxy never
bound: confirm the rule's `listenaddress` matches the *current* WSL gateway
(`ip route | grep default`), then force IP Helper to re-read the store with
`Restart-Service iphlpsvc -Force`. If the Windows listener answers locally but
WSL still can't reach `<gateway>:27182`, open the inbound port once with
`New-NetFirewallRule -DisplayName "WSL Fusion MCP 27182" -Direction Inbound -LocalPort 27182 -Protocol TCP -Action Allow`.

Remove the (correct) gateway forward when you're done with:

```powershell
netsh interface portproxy delete v4tov4 listenaddress=172.17.64.1 listenport=27182
```

## Talking to Fusion over HTTP — the full recipe (copy-paste, verified)

Plain `curl` over HTTP is all you need — but the JSON-RPC handshake has steps
that, if skipped, fail with confusing errors. The committed client —
`FusionBridge` in `src/hendley/ingestion/fusion/bridge.py` — implements this
handshake end to end, so from Python use it (or just run `hendley pcba` /
`hendley app`). The raw recipe below is the reference for debugging or for
working outside the package. Don't invent another client — run this.

**The rules that bite (each one cost a debugging session to rediscover):**
- **Never `127.0.0.1` from WSL.** Fusion listens on the *Windows* loopback; from
  WSL2 you must hit the **Windows host IP = the default gateway**
  (`ip route | grep default | awk '{print $3}'`, e.g. `172.17.64.1`). Needs the
  Windows port-forward in place — see "Reaching Fusion from WSL2" above,
  including the `listenaddress=0.0.0.0` gotcha.
- **…but spoof the `Host` header to loopback.** The server now **validates the
  `Host` header**: hitting the gateway IP makes `Host` read `172.17.64.1:27182`,
  which it rejects with **`HTTP 403 {"error":"Invalid Host header"}`** *before*
  the handshake even starts. Send **`-H 'Host: 127.0.0.1:27182'`** on every
  request — you still *connect* to the gateway IP (that's the URL), but the
  `Host` header must read as loopback. (Observed 2026-07-04; older sessions
  didn't need it, so this is a newer server build — if you get a 403 "Invalid
  Host header", this is why.)
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
HOST='-H Host:127.0.0.1:27182'                     # server validates Host — must read as loopback

# 1) initialize ONCE — capture the session id from the RESPONSE HEADER
SID=$(curl -s -D - -o /dev/null $CT $ACC $HOST -X POST "$B" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"hendley","version":"1.0"}}}' \
  | tr -d '\r' | awk -F': ' 'tolower($1)=="mcp-session-id"{print $2}')

# 2) say "initialized" (REQUIRED before any tools/call)
curl -s $CT $ACC $HOST -H "MCP-Session-Id: $SID" -X POST "$B" \
  -d '{"jsonrpc":"2.0","method":"notifications/initialized"}' >/dev/null

# 3) call the read tool — reuse $SID on every call. Arg = the tool's `arguments`.
read_elec(){ curl -s $CT $ACC $HOST -H "MCP-Session-Id: $SID" -X POST "$B" \
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
An unpaginated read caps at 100 rows — pass `pagination{limit,offset}` for
more. `FusionBridge.read_all()` pages at `limit` 1000 per batch (with a
100-batch runaway guard), stopping on the first empty batch.

## Object model (what we walk)

- `electronics.Sheet` = every existing top-level schematic sheet. Columns
  include `number`, `name`, `description`, `headline`, bounds (`x1`…`y2`) and
  `module_object_id`. Read this before issuing `EDIT .S<number>`; `EDIT` creates
  a sheet when the number does not exist. Verified on the seven-sheet
  `hendley test` fixture, 2026-07-15.
- `electronics.Part` = a placed component **instance** on the schematic.
  Columns: `object_id`, `name` (designator, e.g. `U1`/`R1`), `value`
  (e.g. `22k`, or a supply-net name like `GND` for power symbols),
  `module_object_id`, `deviceset_object_id`, `device_object_id`,
  `package3d_object_id`. **No part-number columns inline** — those are
  attributes (below). `comet` has 50 Part rows, many of which are GND/supply
  pseudo-parts. ⚠️ Do NOT use `package3d_object_id == 0` to spot them — a
  real part whose library device lacks a 3D model also reads 0 (bit us with
  R10, 2026-07-10). The honest discriminator is the device's 2D footprint:
  join `electronics.Device` on `device_object_id` and check
  `package_object_id != 0` (supply symbols have none). 3D models are
  irrelevant to this tool.
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
    `LCSC=C31850`, `MPN=0603WAF2202T5E`, `MANUFACTURER=UNI-ROYAL`. (A later
    capture, after part swaps, reads different values for R1 — see the table
    below; both snapshots are real, from different sessions.)
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
| `MPN` **only**   | `manufacturer_part` (`manufacturerPart`) — ⚠️ **`MP` is NOT a fallback** |
| `MANUFACTURER` (or `MF`) | kept in `attributes`  |
| `PACKAGE`        | `package`                 |
| Part `value`     | `value`                   |
| Part `name`      | `designator`              |

Caveats seen in real data:
- Attribute names are **not fully standardized** across library parts. U2
  (MT3608) uses `MP`/`MF` **in addition to** `MPN`/`MANUFACTURER`, plus extra
  SnapEDA/DigiKey fields (`CHECK_PRICES`, `SNAPEDA_LINK`, `DIGIKEY_PART_NUMBER`,
  `PRICE`, `AVAILABILITY`, `DESCRIPTION`). The extractor reads `LCSC` for the
  code and **`MPN` and only `MPN`** for the MPN.
- ⚠️ **`MP` is NOT a fallback for `MPN`, and `MF` is not one for `MANUFACTURER`.**
  They are stale SnapEDA imports and they LIE: on a real board `MP` read `MB6S`
  — a 600 V bridge rectifier — on a part whose schematic VALUE said `MB10S`, a
  1000 V one. A stale import must not decide what gets soldered down. They are
  still carried in `attributes` (nothing is thrown away); they are simply never
  obeyed. (Craig, 2026-07-13: `MP` is being retired.)
- `PACKAGE` (the attribute) is sometimes a placeholder (`"Package "`); treat as
  best-effort. The real library footprint comes from the
  `electronics.Device` → `electronics.Package` join, along with its `headline` —
  the geometry, which is the only honest way to tell a 150-mil `SO16` from a
  300-mil one. Both are read schematic-side; no `BOARD;` switch is needed.
- GND / supply symbols and the title-block/logo part (`U$1`, value `v1.0`)
  have no `LCSC`/`MPN` and are excluded from the BOM extraction.

## Design name

`electronics.Schematic` row `name` is a temp path ending in `comet sch.sch`;
the design/document name is taken as **`comet`**. Some valid Electronics
contexts publish Part rows while `electronics.Schematic` itself is empty. In
that case Hendley reads Fusion's `activeDocument.name` through the read-only
execute channel. It must not collapse multiple designs into a shared `unknown`
draft namespace.

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
                 "Host":"127.0.0.1:27182",   # server validates Host — must read as loopback
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

## ⭐ Board/schematic context, sheets, and MCP proxy limits

Board-side entities (`electronics.Element` etc.) read **empty** while the
*schematic* view is active — `{"items":[]}`, not an error (same failure shape as
the unscoped-attribute gotcha). To read placements, switch the active view to the
board layout over the same channel:

```python
app.executeTextCommand('Electron.run "BOARD;"')   # via fusion_mcp_execute
```

In a healthy proxy session, this command requests schematic sheet 1:

```python
app.executeTextCommand('Electron.run "EDIT .S1;"')
```

One complete live round trip succeeded on `hendley test`, 2026-07-15:
`EDIT .S1;` exposed 36 `electronics.Part` rows and zero Element rows;
`BOARD;` exposed 30 `electronics.Element` rows and zero Part rows; returning
with `EDIT .S1;` restored the same 36 Part rows and zero Element rows. Later
live runs established an important operational limit: this Fusion MCP build can
wedge its script proxy on the board-to-schematic return, producing empty entity
reads and recursive proxy stack errors. Therefore Refresh captures every
schematic sheet first and treats its subsequent `BOARD;` as one-way for the
remainder of that run. If the proxy is wedged, toggle the MCP server or restart
Fusion once; repeated `EDIT .S1;` retries do not heal it.
`EDIT .S2;`, etc. activate other schematic sheets. **Never probe upward until one fails:** Autodesk's `EDIT`
semantics create a missing sheet. Enumerate first:

```python
bridge.read_all("electronics.Sheet")
```

The live `hendley test` design returned exactly sheet numbers 1–7 with
`pagination.hasMore=false` on 2026-07-15.

### Image evidence: settle, export fresh, and crop to scale

Electronics commands dispatched through `Electron.run` can finish after the
bridge request returns. Do not issue `WINDOW` and immediately trust an existing
PNG: that produced identical sheet files and full-board images under crop
filenames. The visual capture path now:

1. changes context and window;
2. waits briefly for Fusion to settle;
3. removes the previous output file;
4. fires `EXPORT IMAGE`;
5. waits for a non-empty new PNG.

Sparse schematic pages also receive a lossless crop around the populated
drawing region, preserving small diode bars and transistor arrows during model
transport. The clean board export brackets capture with `DISPLAY -UNROUTED;` and
`DISPLAY UNROUTED;`. Airwires are routing state, not package evidence. Each
unresolved placement also gets a 12 mm square window centered on its board
coordinates. The manifest records that exact span, allowing image analysis to
measure a can diameter or pad span.

`GRID MM 1.0` was tested live. It changes the visible Fusion canvas, but native
`EXPORT IMAGE` omits display-grid overlays; the Electronics workspace also has
no `app.activeViewport` for `saveAsImageFile`. Dimensioned crop bounds are the
reliable automated scale mechanism.

⚠️ **The switch does NOT visibly raise the board window** (maintainer-observed,
live): the schematic can stay the front window throughout while `BOARD;` flips
the electronics **engine's current-drawing context** — which is what the bridge
queries. The context later reverts to the schematic on its own (observed after
the user next interacts with the schematic window), after which Element reads
are empty again. Treat "which entity reads non-empty"—not the visible
window—as the source of truth. Hendley may try `EDIT .S1;` when schematic
entities are empty, but callers must recognize the wedged-proxy failure above
and reset once rather than looping.

After the switch (verified live on `comet`, 2026-07-10):

- `electronics.Element` = one row per placed package. Columns: `object_id`,
  `name` (designator), `value`, `x`, `y` (**mm**, board origin — may be negative),
  `angle` (deg), `mirror` (1 = bottom side), `spin`, `smashed`, `populate`,
  `locked`, `package_object_id`, `package3d_object_id`.
- `electronics.Package` — join `package_object_id` → `name` for the **library
  footprint name** (e.g. `DO-214AC(SMA)`, `R-0603`). This is the footprint
  identity used by `data/cpl-rotations.json` (below).
- Element count matched the schematic's real (non-pseudo) part count exactly.

### CPL generation + `data/cpl-rotations.json`

This whole flow is committed as **`hendley pcba`** (bridge:
`src/hendley/ingestion/fusion/bridge.py`; live read:
`src/hendley/ingestion/fusion/live_design.py`; BOM/CPL + rotation
corrections: `src/hendley/providers/jlcpcb/order_files.py`; command:
`src/hendley/cli/manufacturing.py`) — schematic read (`EDIT .S1;` when the
layout is current), `BOARD;` placement read, rotation corrections, live JLC stock check, and
exactly two output files (`bom.csv` + `cpl.csv`). Do-not-populate parts — a
schematic `DNP` attribute set to anything but empty/`0`, or a board element
whose `populate` flag is off — are excluded from both files and from the
stock check. **Run the command; don't rebuild this pipeline by hand.** One standing data file supports it: **`data/cpl-rotations.json`**
records per-footprint rotation corrections — some library footprints are drawn
with a zero-orientation that differs from JLC's feeder expectation, so those
parts need the same hand-rotate in JLC's order preview on *every* submission.
Corrections are keyed by **LCSC code or library footprint name** (never
designator — the error is a property of the library model and follows the part
across designs); `rotationOffsetDeg` is **positive = counterclockwise** (JLC's
convention); applied as `(angle + offset) % 360`. When the user reports a part
needed rotating in the preview, add an entry.
