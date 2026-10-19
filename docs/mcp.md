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
| `approve_part(designator, code, alternates?)` | record a part approved while drawing: reads the placed line from the live schematic, names its requirement the way Refresh does, live-verifies every code and its package, then records it through the app's approval path |

No Fusion writes and no ranking in Python. The one DB write is
`approve_part`, and only on the engineer's say-so (Craig, 2026-10-19). The
part must already be placed: the key is named from the schematic line
exactly as Refresh names it, so the next Refresh and `hendley pcba` look up
the list it wrote. The first code becomes the chosen part of a new list;
on an existing list it joins as an alternate. It answers
`resolvesOnRefresh` by re-running Refresh's own lookup on the same parts.
Verified live on Comet (R8, U2) against a copy of the parts DB.

Known limits: alternates must share the first code's catalog package, so
one land spelled two ways (SOIC-8 / SOP-8) is refused (add it in the app);
the first code's package is taken from the requirement the app names, as in
the app; a part marked not-populated only on the board is not caught (the
board is not read); from the board view it switches Fusion to the schematic.

## Verified 2026-10-19 (Linux)

- stdio round trip from `/tmp`: tools listed, calls answered.
- DigiKey live: `AP2112K-3.3TRG1` → found, Active, stock, tiers, lead time.
- Mouser live: same MPN → found, stock, tiers, lead time, links.
  `LifecycleStatus` is **null for ordinary active parts**; Mouser fills it only
  for flagged ones (New Product / NRND / Obsolete).
- jlcsearch reachable without keys (`ldos`, `package=SOT-23`).
## Verified 2026-10-19 (WSL, all three key blocks)

Driven over real stdio (`cwd=/tmp`, `HENDLEY_KEYS` set), asking for a 3.3 V LDO
in a 3-pin SOT-23 land, Basic preferred:

- `search_parts` live: `ldos`, net = `SOT-23` / `SOT-23-3` / `SOT-23-3L`, sieve
  `output_voltage_min ≤ 3.3`, `output_voltage_max ≥ 3.3` → 25 scanned, 5 proven
  (BCT2036EUR33-TR C2887764, CL9906A33L3M C2961113, …; all Extended), 20 misses
  with the failed term and the value (e.g. `C19284 output_voltage_max is 2.5`).
- `part_detail` live: `C5446` XC6206P332MR-G → SOT-23-3L, Basic, 426,662 stock,
  6 price tiers, 12 parameters, datasheet.
- `us_availability`: XC6206P332MR-G found on DigiKey (8,358, Active, 16 weeks)
  and Mouser (11,844, 86 days). The JLC house brands (BCT…, CL…) are on neither.

**Does not work well — discovery coverage:**

- The jlcsearch `ldos` table is **sparse**: only 25 rows across the three
  SOT-23 spellings, and it lacks C5446, the obvious Basic 3.3 V SOT-23 LDO
  (426 k stock). A category search alone missed the best answer.
- `components?search=` (mode `fts`) returns **unrelated parts**: `XC6206P332`
  → 16 rows of TVS/BJT/FFC parts; `XC6206` → 85 rows, none an XC6206. With an
  empty sieve every one "proves". Keyword discovery cannot fill the gap today.
- Until fixed, an agent that already knows an MPN/C-code should go straight to
  `part_detail` rather than trust a category net as exhaustive.

**Comet BOM (live design, 2026-10-19):** `part_detail` on all 19 populated
C-codes → all found; `us_availability` on their MPNs → no errors. Only
CC0603KRX7R9BB104, SS34 and SMF7.0A are stocked at both US houses; most lines
are JLC house brands neither carries. D1 SMF7.0A (C123794) has **7** at JLC
(DigiKey 2,997, Mouser 6,992).

**Fixed: DigiKey stock read as `None`.** DigiKey often omits
`QuantityAvailable` — at 0 (CL10A105KB8NNNC, STM8S003F3P6TR) and also for
stocked parts (DSS34 23,243; 1SMA4744A 17,803; BZT52C4V7S 1,622). Stock now
falls back to the largest `ProductVariations[].QuantityAvailableforPackageType`.

**Open: same MPN is not the same part.** `us_availability` matches the MPN
only. For generic numbers the US house sells a different maker: DSS34 is
FUXINSEMI at JLC and Slkor at DigiKey; SS34 is JSMSEMI vs onsemi; BZT52C4V7S
is hongjiacheng vs Good-Ark (DigiKey) / Rectron (Mouser). Compare the
`manufacturer` fields before calling it the same part. Also, `part_detail`
returns `manufacturer: null` for some codes (Samsung, ST, YAGEO, Littelfuse
lines on Comet).

**JLC IP allowlist:** a new machine gets `403 The request client ip is not
allowed` until its public IP is added in the JLC console (App Setting).
`hendley ping` misreports every 403 as "lacks the component API permission";
`hendley detail <code>` shows the real message.
