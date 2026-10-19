# `hendley mcp` — part search for Claude Code, from any project

Why: [ADR-0010](adr/0010-mcp-server-and-us-distributors.md). While drawing a
schematic, with Claude Code beside Fusion, say "find me a 3.3V LDO in SOT-23
that JLC has as a Basic part, and check DigiKey/Mouser" — from **any** repo,
not just this one.

Claude Code starts the server itself (stdio) when a session opens and stops it
when the session ends. Nothing to run by hand; no port.

## Setup (once per machine)

```bash
cd ~/hendley
uv venv .venv && uv pip install -p .venv -e ".[mcp]"     # or pip, same extras
claude mcp add -s user hendley -e HENDLEY_KEYS="$HOME/hendley/.keys" \
  -- "$HOME/hendley/.venv/bin/hendley" mcp
```

`HENDLEY_KEYS` matters: the server is launched from whatever project you are
in, so it cannot find `.keys` by walking up from the cwd.

## Keys (`.keys`, git-ignored)

The JLC block (see README) plus, optionally:

```text
DIGIKEY:
    DigiKeyClientId:     <client id>
    DigiKeyClientSecret: <client secret>
MOUSER:
    MouserApiKey:        <search api key>
```

Env vars `DIGIKEY_CLIENT_ID`, `DIGIKEY_CLIENT_SECRET`, `MOUSER_API_KEY`
override. A distributor without keys reports `not configured`; nothing fails.
DigiKey: developer.digikey.com → Organization → Production App with
**ProductInformation V4** (free: 1000 req/day). Mouser: mouser.com/api-search
→ Sign Up (free: 1000 calls/day, 30/min).

## Tools

| Tool | What it does |
|---|---|
| `list_categories` | jlcsearch tables and the typed columns a sieve term can prove |
| `search_parts(plan)` | ADR-0007 plan → jlcsearch net → live JLC verify → proven `candidates` + `misses` with reasons |
| `part_detail(codes)` | live JLC facts for C-codes: MPN, package, Basic/Extended, stock, tiers, parameters, datasheet |
| `us_availability(mpns)` | DigiKey + Mouser per exact MPN: stock, lifecycle, price breaks, lead time, links |
| `approved_parts(kind?)` | the house-parts DB (approved ranked choices) — read only |

Read-only throughout: no Fusion writes, no DB writes, no ranking in Python.

## Verified 2026-10-19 (Linux)

- stdio round trip from `/tmp`: tools listed, calls answered.
- DigiKey live: `AP2112K-3.3TRG1` → found, Active, stock, tiers, lead time.
- Mouser live: same MPN → found, stock, tiers, lead time, links.
  `LifecycleStatus` is **null for ordinary active parts**; Mouser fills it only
  for flagged ones (New Product / NRND / Obsolete).
- jlcsearch reachable without keys (`ldos`, `package=SOT-23`).
- **Not yet verified live:** `search_parts` / `part_detail` (need the JLC keys).
