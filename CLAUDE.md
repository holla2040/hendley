# CLAUDE.md — guidance for Claude Code in this repo

## Purpose

**Henley** is a Python tool to query the JLCPCB parts inventory (LCSC / JLC
components) and, going forward, to consolidate part info pulled directly from
Autodesk Fusion Electronics — so the user can validate part availability and
speed up JLCPCB **PCBA** order submissions. It is a Python reimplementation of
JLCPCB's official Java OpenAPI SDK. (Named after James Garner's character
Hendley, "the Scrounger", in *The Great Escape*.)

## Architecture / file map

- `src/henley/config.py` — loads credentials from the git-ignored `.keys` file;
  resolves endpoint. `Credentials`, `Settings`, `load_credentials`,
  `load_settings`. Path order: explicit arg → `HENLEY_KEYS` → `.keys` found by
  walking up from cwd. Endpoint order: `HENLEY_ENDPOINT` → default host.
- `src/henley/auth.py` — `JOP` request signing (HMAC-SHA256). Builds the
  `Authorization` header and the string-to-sign.
- `src/henley/client.py` — `JLCClient`: signed `_post` plumbing plus the
  read-only component endpoints; `JLCError` and the `{code, success, message,
  data}` envelope unwrap.
- `src/henley/cli.py` — argparse CLI; entry point `henley = henley.cli:main`.
  Commands: `ping`, `detail`, `private`, `library`, `fusion`.
- `src/henley/fusion.py` — Fusion Electronics bridge: the `DesignPart` model,
  `load_parts_json()` (ingest the parts-export contract), and
  `enrich_with_jlc()` (look up stock/price by JLC code). `extract_components()`
  is Fusion-side only (runs inside Fusion 360) — see HANDOFF.md.
- `src/henley/__init__.py` — public API exports (`JLCClient`, `JLCError`,
  config helpers).
- `docs/api-reference.md` — **the API contract** (reverse-engineered from the
  Java SDK). Source of truth for endpoints, request/response shapes, and the
  not-yet-wrapped PCB/TDP order routes.
- `sdk/` — reference JLCPCB Java SDK jars (Core + Business).
- `image/` — project avatar (`henley.png`, `henley_80x80.png`).
- `.keys` — credentials (git-ignored; never commit). `notes` — holds the
  developer-portal URL (not the API host).

- `tests/` — `test_auth.py` (signing, pinned to the Java SDK algorithm) and
  `test_fusion.py` (parts-export ingest contract).
- `HANDOFF.md` — the Fusion-integration work order for Claude running on the
  `hendrix` Windows box (which is localhost to Fusion and can use the Fusion
  API MCP server). Read it before touching the Fusion side.

## Auth scheme (`JOP`)

`Authorization: JOP appid="..",accesskey="..",timestamp="..",nonce="..",signature=".."`

- `signature = Base64(HMAC_SHA256(secretKey, stringToSign))`
- `stringToSign = METHOD\nCANONICAL_URI\nTIMESTAMP\nNONCE\nPAYLOAD\n`
- `CANONICAL_URI` = raw request path; `PAYLOAD` = exact JSON body (empty for
  GET); `TIMESTAMP` = integer epoch seconds; `NONCE` = 32-char random token.

All component routes are `POST` with a JSON body, even getter-shaped names.
Null body fields are omitted to match the Java SDK's `toJSON()`.

## Fusion access from WSL (read side)

Henley reads a live Fusion Electronics design over plain HTTP (JSON-RPC) at
`http://127.0.0.1:27182/mcp` — no MCP client needed; just `POST` `initialize`
then `tools/call` with `fusion_mcp_electronics_read`. The JLC `Cxxxx` code is the
part's **`LCSC`** attribute (read `electronics.Attribute` filtered by
`part_object_id`); MPN is `MPN`. Requires Fusion running with **Preferences >
General > API > Fusion MCP Server** enabled and an Electronics doc open.

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
henley ping                 # verify credentials + signing
pytest                      # tests live in tests/ (run once present)
ruff check .                # line-length 100, target py310
```

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
