# Henley

<img src="image/henley.png" alt="Henley — James Garner as Hendley, 'the Scrounger', in The Great Escape" width="160" align="right">

A small Python tool for querying the **JLCPCB** parts inventory (LCSC / JLC
components) and — going forward — for consolidating part information pulled
directly from **Autodesk Fusion Electronics**, so you can validate part
availability and speed up JLCPCB **PCB Assembly (PCBA)** order submissions.

> Named after James Garner's character Hendley, "the Scrounger", in the film
> *The Great Escape*.

Henley is a Python reimplementation of JLCPCB's official Java OpenAPI SDK. The
reverse-engineered API contract is documented in
[`docs/api-reference.md`](docs/api-reference.md).

> **Note:** the reference JLCPCB Java SDK jars are **not** distributed with this
> repo. You don't need them to run Henley — they were only used to reverse-
> engineer the contract. If you want to cross-check against them, download the
> Core + Business SDK jars from JLCPCB yourself and drop them in a local `sdk/`
> directory (git-ignored).

## Why Henley

In *The Great Escape*, Hendley is **"the Scrounger"** — the guy who quietly goes
out and comes back with whatever the team needs. That's the job here: Henley
scrounges JLCPCB so you don't have to sit on the JLC parts site hand-searching
for components, stock, and equivalents.

A concrete example. Say your schematic is full of **0603** resistors, each
already tagged with a JLC/LCSC part number, and you decide to move the whole
board to **0402** to save space. Now you need, for *every* resistor, the
equivalent **0402** part that:

- matches the electrical spec (resistance, tolerance, power rating, …),
- is actually **in stock** at JLCPCB, and
- ideally is a Basic/preferred assembly part to keep PCBA cost down.

Doing that by hand — one web search per part — is exactly the tedium Henley is
meant to remove. You point Henley at the design, and it goes and finds the
matching, in-stock parts for you.

**Where this is heading.** Today the Fusion Electronics API is read-only, so
Henley reads the design, looks up each part, and reports what it found. Once
Fusion Electronics gains **write** capability, Henley will close the loop: for
each 0603 part, query JLC for the equivalent 0402 part that has stock and
matching specs, then **write the new JLC part number straight back into the
schematic** at the new package size — turning a whole-board package migration
from a day of manual searching into a single query. That is the point of all
this: validate availability and source equivalents automatically, so JLCPCB
**PCBA** orders go out faster and with fewer surprises.

## What it does today

Read-only component (parts inventory) endpoints, signed with JLCPCB's `JOP`
authentication scheme, exposed through a `henley` CLI and a small Python API:

- Look up full component detail (price tiers, stock, parameters, datasheet).
- Browse the assembly component library.
- List your private / consigned JLC inventory.
- Verify that your credentials and request signing are working.

## Install

Requires **Python >= 3.10**. The core install depends only on `requests`.

```bash
git clone git@github.com:holla2040/henley.git
cd henley
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

Optional extras:

```bash
pip install -e ".[dev]"       # pytest, ruff
```

### Set your JLC API keys (required)

Henley authenticates every request with JLCPCB OpenAPI credentials. Without them
the CLI cannot reach the API. The credentials are **not** committed — they are
read at runtime from a **`.keys` file you create at the project root** (the
repo's `.gitignore` already excludes `.keys`, `*.pem`, and `*.key` so they can
never be committed).

1. Get your credentials from the JLCPCB developer console (`api.jlcpcb.com`):
   **AppID**, **Accesskey**, and **SecretKey**.
2. Create **`.keys`** in the repo root (same folder as `pyproject.toml`) with
   this exact layout (placeholders shown — substitute your own values):

   ```
   JLCAPI:
       AppID:     <your-app-id>
       Accesskey: <your-access-key>
       SecretKey: <your-secret-key>
   ```

   These three fields are all Henley uses. The JLCPCB `.keys` file may also
   contain an RSA "Tokenization Key" block — Henley **ignores it** (it would
   only matter for order placement, which is not implemented), so you can leave
   it in or strip it out.
3. Alternatively, point `HENLEY_KEYS` at a `.keys` file elsewhere
   (see [Environment variables](#environment-variables)).

See [Configuration](#configuration) for full details on the file format and
discovery order.

## Quickstart

1. Install and set your `.keys` file as above.
2. Verify credentials and signing:

```bash
henley ping
```

`ping` distinguishes the two states you might hit:

- **Signing OK, permission missing** — the request authenticated correctly but
  your app lacks the component API permission. Enable it for your app in the
  JLC developer console, then retry.
- **Signature rejected** — check the `AppID` / `Accesskey` / `SecretKey` in
  `.keys`.

## CLI command reference

```
henley [--keys PATH] <command> [options]
```

| Command | Description |
|---------|-------------|
| `henley ping` | Verify credentials + signing; reports whether signing works and whether the component API permission is enabled. |
| `henley detail C2040 [C... ...]` | Full component detail for one or more JLC component codes (price tiers, stock, parameters, datasheet). |
| `henley private [--page N] [--limit N]` | Your private / consigned JLC inventory. |
| `henley library [--limit N]` | Browse the assembly component library. |
| `henley fusion PARTS.json [--no-enrich]` | Ingest a Fusion parts-export JSON and enrich each part against JLC (stock, price tiers, basic/extended). `--no-enrich` validates the file offline without calling the API. |

`--keys PATH` overrides credential discovery for any command.

## Python usage

```python
from henley import JLCClient

client = JLCClient()

# Full detail by component code
detail = client.get_component_detail_by_code(["C2040"])

# One page of the assembly component library
page = client.get_component_library_list(page_size=30)

# Iterate the entire library (follows the lastKey cursor)
for row in client.iter_component_library():
    print(row["componentCode"], row["componentModel"])

# Your private / consigned inventory
private = client.get_private_component_library(current_page=1, page_size=30)
```

## Configuration

### `.keys` file

Credentials are loaded at runtime from a **git-ignored** `.keys` file at the
project root (it is parsed by `src/henley/config.py`). They are never hardcoded
and never committed. The file is the one issued by JLCPCB and uses this format
(placeholders shown — substitute your own values):

```
JLCAPI:
    AppID:     <your-app-id>
    Accesskey: <your-access-key>
    SecretKey: <your-secret-key>
```

Henley reads only the `AppID`, `Accesskey`, and `SecretKey` fields. The JLCPCB
`.keys` file as issued also includes an RSA "Tokenization Key" block (for
encrypting order-placement fields such as shipping addresses); Henley does not
implement order placement and **ignores that block entirely**, so it is optional
and may be omitted.

### Environment variables

| Variable | Effect |
|----------|--------|
| `HENLEY_KEYS` | Path to the `.keys` file (overrides discovery). |
| `HENLEY_ENDPOINT` | Override the API host. |

Path resolution order for credentials: the `--keys` / explicit argument, then
`HENLEY_KEYS`, then a `.keys` file discovered by walking up from the current
working directory.

## Endpoint and permissions

- **API host:** `https://open.jlcpcb.com` (the default).
  Note: `api.jlcpcb.com` is the developer **portal / console**, not the API
  host.
- **Auth scheme `JOP`:** every request carries
  `Authorization: JOP appid="..",accesskey="..",timestamp="..",nonce="..",signature=".."`,
  where `signature = Base64(HMAC_SHA256(secretKey, stringToSign))` and
  `stringToSign = METHOD\nCANONICAL_URI\nTIMESTAMP\nNONCE\nPAYLOAD\n`.

Signing has been verified empirically against the live API:

- A **valid** signature returns `HTTP 403 {"code":403,"message":"API
  insufficient permissions, access denied"}` for this account.
- A **wrong** signature returns `HTTP 401 {"code":401,"message":"The request
  signature verify failed"}`.

So signing is proven correct — the account just needs the component API
permission enabled in the JLC console.

## Reading from Fusion Electronics (no MCP client required)

Henley reads a live Autodesk Fusion design over **plain HTTP** — it issues
JSON-RPC `POST`s directly to the local endpoint Fusion exposes at
`http://127.0.0.1:27182/mcp`. **You do not need any MCP client or middleware**
to use it: no Claude Desktop "Autodesk Fusion" extension, no MCP connector, and
no `claude mcp add` registration. The endpoint speaks the MCP wire protocol, but
from Henley's side it is just an HTTP API you `POST` to with `curl` / `requests`
(`initialize` → `tools/call` with `fusion_mcp_electronics_read`). See
[`docs/fusion-notes.md`](docs/fusion-notes.md) for the request shapes and where
each part's JLC `Cxxxx` code lives (the part's `LCSC` attribute).

The only requirement on the **Windows / Fusion side** is that Fusion is running
with its built-in server enabled — **Preferences > General > API > Fusion MCP
Server** — and an Electronics document open. That is what publishes the HTTP
endpoint; nothing else needs to be installed.

### Reaching it from WSL2 (networking note)

If you run Henley on the same Windows machine as Fusion, `http://127.0.0.1:27182`
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
should return `{"error": "Not Found"}` instantly when Fusion's server is healthy.
If it (or Claude Desktop) "closes the connection unexpectedly," a bad `0.0.0.0`
forward is almost certainly hijacking loopback — delete it and the symptom
clears:

```powershell
netsh interface portproxy show all     # look for a 0.0.0.0 ... 27182 entry
netsh interface portproxy delete v4tov4 listenaddress=0.0.0.0 listenport=27182
```

Remove the (correct) gateway forward when you're done with:

```powershell
netsh interface portproxy delete v4tov4 listenaddress=172.17.64.1 listenport=27182
```

## Security

- `.keys` holds your AppID, access key, and secret key. It is listed in
  `.gitignore` and must **never** be committed.
- Credentials are loaded only at runtime; nothing is hardcoded in the source.
- `*.pem` and `*.key` files are also git-ignored.

## Project history — how this was built

Henley exists because JLCPCB ships an official **Java** OpenAPI SDK but no Python
one. Rather than wrap the Java SDK, the contract was **reverse-engineered from
the JLCPCB Java SDK jars** (the Core SDK + Business SDK) and reimplemented as a
small, dependency-light Python package.

1. **Recover the contract from the jars.** The decompiled Java SDK was read to
   recover: the component (parts inventory) endpoints and their request/response
   value objects; the response envelope (`{ code, message, data }`); and the
   serialization rules (fields emitted as **camelCase**, null fields **omitted**)
   that the wire format depends on. The result is captured as the source of
   truth in [`docs/api-reference.md`](docs/api-reference.md).
2. **Pin the auth scheme.** JLCPCB's `JOP` authentication
   (`Authorization: JOP appid=..,accesskey=..,timestamp=..,nonce=..,signature=..`)
   was reproduced exactly from the SDK's signer: `signature =
   Base64(HMAC_SHA256(secretKey, METHOD\nURI\nTIMESTAMP\nNONCE\nPAYLOAD\n))`.
   `tests/test_auth.py` pins the Python implementation to the Java algorithm so
   it can't drift.
3. **Reimplement in pure Python.** `auth.py` (signing), `client.py` (signed
   `POST` plumbing + the read-only component endpoints + envelope unwrap),
   `config.py` (runtime `.keys` loading), and a `henley` CLI — core install
   depends only on `requests`.
4. **Verify against the live API.** Signing was confirmed empirically: a *valid*
   signature returns `HTTP 403` (insufficient permissions) while a *wrong*
   signature returns `HTTP 401` (signature verify failed) — proving the signing
   is correct and that the remaining gate is account-side permission, not code.
   It also confirmed the real API host is `https://open.jlcpcb.com`
   (`api.jlcpcb.com` is the developer portal).

That JLC reverse-engineering and Python reimplementation was done in Claude Code
on **horton** (the Linux dev box), session
`fd5ea0ac-6e74-4f38-8b3e-8435fc6f1512`.

5. **Add the Fusion Electronics bridge.** On **hendrix** (the Windows box
   running Autodesk Fusion), Henley was extended to read a live electronics
   design over plain HTTP (see
   [Reading from Fusion Electronics](#reading-from-fusion-electronics-no-mcp-client-required)).
   Introspecting a real design answered the key open question — the JLCPCB
   `Cxxxx` code is stored as each part's **`LCSC`** attribute — which lets the
   extractor produce `henley_parts.json` and feed those codes straight into the
   JLC query layer for stock/price enrichment. Details in
   [`docs/fusion-notes.md`](docs/fusion-notes.md).

## Roadmap

1. **Fusion Electronics integration.** Henley will read designs **directly**
   via the Autodesk Fusion API (currently read-only for electronics) — *not* by
   exporting a BOM. A Fusion add-in / script will enumerate the electronic
   design's components and their MPN / LCSC part attributes, then feed those
   part numbers into Henley's JLC query layer to report availability, stock,
   price tiers, and basic/extended (assembly) status — so you know what is
   available before submitting a PCBA order. A stub module is planned at
   `src/henley/fusion.py`.

2. **PCBA order automation.** The JLC SDK also exposes PCB order endpoints
   (`uploadGerber`, calculate price, create order), where address and other
   sensitive fields must be RSA-tokenized with the `.keys` RSA key. These
   endpoints are mapped in [`docs/api-reference.md`](docs/api-reference.md) but
   not yet wrapped — when they are, this is where the RSA tokenization key (and
   a `cryptography` dependency) would come back in.

## License

Proprietary.
