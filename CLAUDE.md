# CLAUDE.md — guidance for Claude Code in this repo

## Purpose

**Hendley** is a Python tool to query the JLCPCB parts inventory (LCSC / JLC
components) and, going forward, to consolidate part info pulled directly from
Autodesk Fusion Electronics — so the user can validate part availability and
speed up JLCPCB **PCBA** order submissions. It is a Python reimplementation of
JLCPCB's official Java OpenAPI SDK. (Named after James Garner's character
Hendley, "the Scrounger", in *The Great Escape*.)

## Architecture / file map

- `src/hendley/config.py` — loads credentials from the git-ignored `.keys` file;
  resolves endpoint. `Credentials`, `Settings`, `load_credentials`,
  `load_settings`. Path order: explicit arg → `HENDLEY_KEYS` → `.keys` found by
  walking up from cwd. Endpoint order: `HENDLEY_ENDPOINT` → default host.
- `src/hendley/auth.py` — `JOP` request signing (HMAC-SHA256). Builds the
  `Authorization` header and the string-to-sign.
- `src/hendley/client.py` — `JLCClient`: signed `_post` plumbing plus the
  read-only component endpoints; `JLCError` and the `{code, success, message,
  data}` envelope unwrap.
- `src/hendley/cli.py` — argparse CLI; entry point `hendley = hendley.cli:main`.
  Commands: `ping`, `detail`, `private`, `library`, `fusion`, `stock`, `scr`,
  `alternates`.
- `src/hendley/alternates.py` — alternate-part discovery: `fetch_candidates()`
  (DISCOVER candidate codes from the third-party parametric index
  `jlcsearch.tscircuit.com` — the official API can't search), `discover_and_verify()`
  (VERIFY *every* hit in one batched `getComponentDetailByCode` call — jlcsearch
  stock is a stale snapshot), and `format_alternates_report()` (the trade-off
  table). It deliberately does **not** rank or pick (no stock/price sort, no
  Basic filter) — Claude/the user weighs the verified data. jlcsearch matches
  `package` (and other string filters) by **exact equality, no wildcards**; the
  fuzzy escape hatch is `--category components -p search=…` (FTS). `CATEGORIES`
  holds the 44 jlcsearch category slugs.
- `src/hendley/scr.py` — Fusion `.scr` migration-script generator: `PartSwap`,
  `load_swaps_json()`, `render_script()`. Turns a list of part swaps (designator
  + package variant + attributes) into the EAGLE command-line script the user
  runs in Fusion (`File > Execute Script`, or `neu_dev.run_text_command("SCRIPT
  …")` in the text-command Py mode). The write side: the Electronics **object**
  API is read-only, but the EAGLE command line **is** reachable from Python/MCP
  via `executeTextCommand('Electron.run "script C:\\path\\changes.scr"')` — so
  Hendley can either hand the user the `.scr` *or* fire it into Fusion over the
  bridge (see "Fusion access from WSL → write side" below). `CHANGE PACKAGE`
  precedes `ATTRIBUTE` per part
  (variant switch can reset variant-default attrs); injection chars are rejected.
- `src/hendley/fusion.py` — Fusion Electronics bridge: the `DesignPart` model,
  `load_parts_json()` (ingest the parts-export contract), `enrich_with_jlc()`
  (look up stock/price by JLC code), and the inventory check —
  `check_stock()`/`format_stock_report()` (classify each part out/low/not_found/
  no_code/ok via one `getComponentDetailByCode` call). `extract_components()`
  is Fusion-side only (runs *inside* Fusion 360's embedded Python) and is still a
  **stub** — the live read is currently done interactively over the HTTP bridge
  (see "Fusion access from WSL"); wrapping it into a committed extractor is the one
  open Fusion-side task.
- `src/hendley/__init__.py` — public API exports (`JLCClient`, `JLCError`,
  config helpers).
- `docs/api-reference.md` — **the API contract** (reverse-engineered from the
  Java SDK). Source of truth for endpoints, request/response shapes, and the
  not-yet-wrapped PCB/TDP order routes.
- `sdk/` — reference JLCPCB Java SDK jars (Core + Business).
- `image/` — project avatar (`hendley.png`, `hendley_80x80.png`).
- `.keys` — credentials (git-ignored; never commit). `notes` — holds the
  developer-portal URL (not the API host).

- `tests/` — `test_auth.py` (signing, pinned to the Java SDK algorithm) and
  `test_fusion.py` (parts-export ingest contract).

## The workflow — having a conversation about JLC parts

The point of Hendley: the user runs Claude in this repo, says something in plain
words about a JLC part, and you have the conversation — **you are the interpreter
of their words into the existing tooling.** Three standing rules for that role:

- **Everything you need to drive the tools is documented** — this file, the
  `README`, and the module docstrings named below. **Do not read the source to
  figure out how to use a tool.** If something genuinely isn't documented, say so;
  don't reverse-engineer it from the code.
- **Never modify Hendley's source to satisfy a request.** You translate the user's
  intent into calls to the tools *as they are*. If a request needs a capability a
  tool doesn't have, tell the user — don't add it.
- **Running the CLI:** prefer `hendley` if it's on PATH. On a fresh checkout where
  `pip install -e .` didn't land it on PATH (or the venv isn't active), run it as
  a module from the repo root — `PYTHONPATH=src python -m hendley.cli <cmd>` (or
  `python -m hendley <cmd>`), which needs only `requests`. Every `hendley <cmd>`
  below works identically that way.

Many conversations are a one-shot lookup — *"is C25768 in stock?"* → `hendley
detail`; *"check this BOM before I order"* → `hendley stock`. The main multi-step
job is **changing a part**, and there is **one** workflow for it; the only thing
that varies is *why* the part changes — it's **out of stock**, or you want a
**different package**, or a **different value**. (If the part lives in a Fusion
design, first read the live design over the bridge — see "Fusion access from WSL"
below — to get its designator and the exact package variant names.) Drive it as:

1. **Anchor on the target.** `hendley detail <code>` → read its category, exact
   `componentSpecification` (the package string), and key specs. The exact
   package string is what you pass as `--package` (see matching rules below).
   `detail` **already prints JSON** — there is **no `--json` flag**; don't pass one
   (it errors). Only `stock` and `alternates` take `--json` (see "CLI output" below).
2. **Translate the spoken constraint into flags** — *you* own the hard filter; it
   is NOT hardcoded. "same package" → `--package "<exact spec>"`; a category →
   `--category <slug>` (`hendley alternates --list-categories`); other constraints
   → `-p key=value`. Then run `hendley alternates <code> --category … [--package …]
   [-p …] --json`. The tool discovers candidates from jlcsearch and **verifies
   every one live** (stock/price/parameters) — it does the gather, not the pick.
3. **Apply any value/numeric hard filter yourself, over the verified `--json`.**
   Most categories have **no** jlcsearch query param for the spec you care about
   (e.g. `resistor_arrays` has no resistance param), and the `_min`/`_max` params
   are unreliable — so don't try to push it into the query. Instead filter the
   `candidates[]` on each part's verified `parameters[]` (the authoritative live
   specs). The recipe (here, keep only 330 Ω parts) — use it, don't re-invent it:

   ```bash
   hendley alternates C29719 --category resistor_arrays --package "0603x4" --json \
   | python3 -c 'import json,sys
   d=json.load(sys.stdin)
   def spec(c,name):
       return next((p["parameterValue"] for p in (c["parameters"] or [])
                    if p["parameterName"]==name), None)
   for c in d["candidates"]:
       if c["verified"] and (spec(c,"Resistance") or "").startswith("330"):
           print(c["code"], c["liveStock"], c["unitPrice1"], spec(c,"Resistance"))'
   ```
4. **Trade off and recommend (this is your job, not the tool's).** Weigh the
   *verified* data. User's bias: **high inventory = popular = supply-chain-safe,
   and they'll pay a bit more for it** — the opposite of "cheapest". **Same
   package is the top priority** (changing it changes the PCB layout); a different
   package can still win if the inventory/price payoff justifies a re-layout.
   Always **surface electrical caveats** — e.g. downsizing 0603→0402 drops the
   power/voltage rating, so check the part's actual dissipation first. Recommend
   one with reasoning the user can override.
5. **Build the swap and generate the `.scr`.** Do NOT read `scr.py` source for the
   input format — the swap-JSON contract is documented in **README → "The
   workflow" (the `.scr` file format)** and the `hendley.scr` module docstring.
   Fields (only `designator` required), filled from data you already have:
   - `designator` — the schematic ref (e.g. `R6`). Find it in the BOM
     (`hendley fusion PARTS.json --no-enrich`, or grep the parts JSON) by matching
     the **old** JLC code; the parts-JSON contract is in `fusion.py`.
   - `package` — the library **variant name**: the *exact* library name read off
     the device, which carries a **leading hyphen** (e.g. `-0402`, not `0402` —
     `CHANGE PACKAGE '0402'` errors). OMIT for a same-package swap. Read the real
     variant name off the device rather than guessing.
   - `lcsc` / `mpn` → the `LCSC` / `MPN` attributes. Both are in hand: `lcsc` =
     the chosen alternate's `code`; `mpn` = its `componentModel` from `detail`
     (note: jlcsearch's row field literally named `mfr` is the **MPN**, e.g.
     `0603WAF2202T5E`, NOT the maker name).
   - `manufacturer` → the `MANUFACTURER` attribute. **The maker name is NOT
     returned by `getComponentDetailByCode` or jlcsearch** — the API gives only the
     MPN. Do NOT fabricate it. Get it from the part's LCSC/JLC page (or the MPN's
     known series), or ask the user. If the swap keeps the same maker, the design's
     existing `MANUFACTURER` already holds it — set this only when it changes.
   - `attributes` — any extra attrs (e.g. `DESC`).

   Then `hendley scr swap.json -o changes.scr` (offline). The script carries the
   **package variant and the attributes** — `CHANGE PACKAGE` (when `package` is
   set), then the `ATTRIBUTE` lines.

   **Write artifacts to `~/tmp/hendley_output/`, never the repo root.** The swap
   JSON, the generated `.scr`, and any scratch output go there
   (`mkdir -p ~/tmp/hendley_output` first) — e.g.
   `hendley scr ~/tmp/hendley_output/swap.json -o ~/tmp/hendley_output/changes.scr`.
   Keep the working tree clean.
6. **Apply in Fusion, then reconcile.** Fusion is the write side (the Electronics
   *object* API is read-only). Two ways to apply the `.scr`:
   - **Manual** — the user runs it: *File > Execute Script*.
   - **Over the bridge (preferred when Fusion+MCP are reachable)** — fire it from
     Python/MCP: `executeTextCommand('Electron.run "script C:\\tmp\\changes.scr"')`
     via `fusion_mcp_execute` (see "Fusion access from WSL → write side" below).
     This same channel can carry a **changed schematic VALUE** (e.g. 220 Ω →
     330 Ω) as `Electron.run "VALUE R6 330"`, so the whole change can be one
     scripted stream — no manual value-setting step required.

   Either way: if you apply manually, also set anything the `.scr` doesn't carry
   (notably the VALUE) in Fusion — do NOT hand-edit the `.scr` to fake a value.
   `Electron.run` returns no echo, so **verify** with a scoped
   `electronics.Attribute` read (live `part_object_id`) afterward, and remember
   bridge changes are **unsaved** until the user saves in Fusion. Then update the
   BOM record (the parts JSON) so the designator points to the new code and a
   later `hendley stock` reflects reality.

**jlcsearch matching rules (so your flags actually match):**
- `package` and other per-category **string** filters are **exact, case-
  sensitive, no wildcards** (`DFN-8` ≠ `DFN-8(3x3)`; `%`/`*`/substrings → 0 rows).
  Use the target's exact `componentSpecification`.
- Numeric `_min`/`_max` params are **unreliable** (sparse columns silently drop
  null rows). Apply numeric/spec filters yourself over the verified
  `parameters[]`, not via jlcsearch query params.
- Fuzzy / cross-package discovery: `--category components -p search="<tokens>"`
  (FTS, token + prefix; in-stock parts only).

**Do NOT** filter or rank on Basic vs. Extended — it's a fee attribute, not a
selection criterion (display it, don't select on it). That fee is the JLCPCB PCBA
**feeder/loading charge**, per *unique* part type and one-time per order (NOT per
unit): **Economic** tier ≈ **$3** per Extended part (Basic free); **Standard**
tier ≈ **$1.50** per part type for *both* Basic and Extended — so "Basic is
cheaper" really only holds on Economic, and the impact scales with BOM diversity
and amortizes over board count. The *unit-price* gap between a Basic and Extended
equivalent is negligible (often Extended is even cheaper per unit). The fee is
**not** returned by the component API (it's order-level) — which is exactly why
you surface Basic/Extended for the user's judgment rather than select on it.
(Source: jlcpcb.com/help/article/pcb-assembly-price — a policy figure that
changes; verify if it matters.) **Do NOT** download the whole catalog "for one
part" — jlcsearch is the discovery surface.

**CLI output (so you don't guess a flag that doesn't exist):**
- `detail`, `private`, `library`, `fusion` — **print JSON by default; no `--json`
  flag** (passing `--json` errors). Pipe their stdout to `python3`/`jq` to parse.
- `stock`, `alternates` — print a **human report by default**; add **`--json`**
  for structured output. These are the *only* two commands that accept `--json`.
- `ping` — prints a status line. `scr` — prints the `.scr` (or `-o FILE` to write).
- Each command's flags are exactly those in `hendley <cmd> --help`; don't assume a
  flag exists because another command has it.

## Auth scheme (`JOP`)

`Authorization: JOP appid="..",accesskey="..",timestamp="..",nonce="..",signature=".."`

- `signature = Base64(HMAC_SHA256(secretKey, stringToSign))`
- `stringToSign = METHOD\nCANONICAL_URI\nTIMESTAMP\nNONCE\nPAYLOAD\n`
- `CANONICAL_URI` = raw request path; `PAYLOAD` = exact JSON body (empty for
  GET); `TIMESTAMP` = integer epoch seconds; `NONCE` = 32-char random token.

All component routes are `POST` with a JSON body, even getter-shaped names.
Null body fields are omitted to match the Java SDK's `toJSON()`.

## Fusion access from WSL (read side)

Hendley reads a live Fusion Electronics design over plain HTTP (an MCP
Streamable-HTTP / JSON-RPC server) — no MCP client needed, plain `curl` works.
But the handshake is **not** "just POST initialize then tools/call": you must hit
the **Windows host IP, not `127.0.0.1`** (loopback isn't reachable from WSL),
capture the **`MCP-Session-Id` response header** and resend it on every call, and
send a **`notifications/initialized`** message before any `tools/call` — skip any
of these and you get the confusing `Missing MCP-Session-Id header` /
`Session not initialized` errors that have made past agents hand-write their own
client. **Do not re-derive it or read source — copy the complete, verified
recipe (handshake + a Part→Attribute→`LCSC` worked example) from
`docs/fusion-notes.md` → "Connecting from WSL — the full handshake".** The JLC
`Cxxxx` code is the part's **`LCSC`** attribute (read `electronics.Attribute`
filtered by `part_object_id`); MPN is `MPN`. Requires Fusion running with
**Preferences > General > API > Fusion MCP Server** enabled and an Electronics
doc open.

⚠️ **Attribute reads are part-scoped, and `object_id`s aren't stable.** Filtering
`electronics.Attribute` by `name` alone (or unfiltered) returns **empty** — you
must pass the live `part_object_id`. And `object_id`s are reassigned on every
reload (R1 was `2812` one session, `11225` the next), so always re-read
`electronics.Part` for the current id in the same session. (This — not "the
reader can't see JLC attrs" — was the cause of earlier empty reads;
`LCSC`/`MPN`/`MANUFACTURER` do read back fine when scoped.)

## Fusion access from WSL (write side) — `Electron.run`

The Electronics **object** API is read-only, but the **EAGLE command interpreter
is reachable from Python/MCP** — the one thing we long thought impossible. The
trick (Autodesk forum, verified live):

```python
import adsk.core
app = adsk.core.Application.get()
app.executeTextCommand('Electron.run "script C:\\tmp\\changes.scr"')
```

Run that string through `fusion_mcp_execute` (`featureType:"script"`). A **bare**
`executeTextCommand("script …")` fails (`There is no command script`) because it
hits Fusion's *core* channel; wrapping in **`Electron.run "<eagle cmd>"`** routes
into the electronics interpreter. So Hendley can apply a `.scr` (or any `CHANGE` /
`ATTRIBUTE` / `VALUE` / `EXPORT` command) headlessly over the bridge. Rules:
- **No return value** — `Electron.run` yields `''` on success; verify out-of-band
  (scoped `electronics.Attribute` read, or an `EXPORT PARTLIST <file>` you read).
- **Fusion-host paths** — Fusion is on Windows; WSL `~/tmp/x.scr` ↔ `C:\tmp\x.scr`
  (`~/tmp` → `/mnt/c/tmp` on `hendrix`). Double the backslashes in the Python
  literal; nest the quotes (`'Electron.run "script C:\\tmp\\x.scr"'`).
- **`.scr` stops at the first failing command**; changes are **unsaved** until the
  user saves in Fusion (reopening reverts them).
- Full detail + the verification matrix: **`docs/fusion-notes.md` → "The WRITE
  path"**.

⚠️ **WSL port-forward gotcha (cost us a debugging session):** to reach Fusion's
Windows-loopback port from WSL2, forward it on Windows with
`listenaddress=<WSL gateway IP>` (e.g. `172.17.64.1`, from `ip route | grep
default`) — **never `listenaddress=0.0.0.0`**. A `0.0.0.0:27182` listener hijacks
the loopback that Fusion's server and the Claude Desktop connector use, so they
"connect then close unexpectedly" and Desktop stops connecting. Symptom check:
Windows `curl http://127.0.0.1:27182/mcp` returns `{"error":"Not Found"}` when
healthy; if it closes unexpectedly, delete any `0.0.0.0` portproxy rule
(`netsh interface portproxy delete v4tov4 listenaddress=0.0.0.0 listenport=27182`).
See README "Reading from Fusion Electronics".

## Verified endpoint facts

- API host: **`https://open.jlcpcb.com`** (the default in `config.py`).
- `api.jlcpcb.com` is the developer **portal / console**, NOT the API host.
- Empirically verified: a **valid** signature → `HTTP 403 {"code":403,...
  insufficient permissions...}`; a **wrong** signature → `HTTP 401 {"code":401,
  ...signature verify failed}`. So signing is correct.
- **The earlier 403 was an account-under-review state, not a missing
  permission.** The account is no longer under review, and all four Parts
  component endpoints (`getComponentInfos`, `getComponentLibraryList`,
  `getPrivateComponentLibrary`, `getComponentDetailByCode`) now show **Enabled**
  in the JLC console (Manage Apps → App Setting → Service → Parts). The component
  API should now return `200`.

## Run / test

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .            # core (requests only)
pip install -e ".[dev]"     # pytest, ruff
hendley ping                 # verify credentials + signing
pytest                      # tests live in tests/ (run once present)
ruff check .                # line-length 100, target py310
```

**If the `hendley` command isn't found** (venv not activated, or `pip install -e .`
didn't land the script on PATH — happens on fresh boxes / old pip-setuptools),
run it without installing, from the repo root:
`PYTHONPATH=src python -m hendley.cli <cmd>` (or `python -m hendley <cmd>`). Tests
likewise: `PYTHONPATH=src python -m pytest -q`.

The `.keys` RSA "Tokenization Key" block (for order-placement field encryption)
is currently **unused** — `config.py` does not parse it and no code consumes it.
It would only be needed if/when order placement is implemented.

## Conventions

- Keep dependencies minimal — core install is `requests` only. Push anything
  heavier into an optional extra.
- **Never hardcode or commit secrets.** Credentials load at runtime from
  `.keys`, which is git-ignored (along with `*.pem`, `*.key`). Use placeholders
  in any docs or examples.
- The API contract lives in `docs/api-reference.md` — update it alongside any
  new endpoint wrapper.

## Git rules (standing)

- **Never** run `git add -A` or `git add .` — stage files individually by path.
- **Never** commit or push unless the user explicitly asks. "fix" / "update" /
  "merge" do not imply commit or push; each git operation needs its own
  explicit instruction.
