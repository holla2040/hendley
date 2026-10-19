# ADR-0010 — Hendley as an MCP server, with US distributors as data sources

Status: accepted (2026-10-19, design agreed with Craig in conversation)
Builds on ADR-0007 (the agent plans, Python proves). Changes nothing in the app.

## Context

Hendley answers "can JLC build this BOM?" for a *finished* design. Craig's other
need is earlier: **while drawing the schematic**, with Claude Code open beside
Fusion, he wants to say "find me a 3.3V LDO in SOT-23" and get parts that JLC
stocks — and, for a later US PCBA run, know whether DigiKey and Mouser carry
the same MPN.

Options weighed:

- **Octopart / Nexar** — rejected. The free tier is 100 matched parts for the
  life of the account; lifecycle and lead time cost extra on paid plans.
- **LCSC's API** — not available. LCSC will not issue keys to a customer who
  buys through JLC. Not needed either: LCSC and JLC share C-codes and the JLC
  OpenAPI already serves the catalog (`getComponentDetailByCode`).
- **A separate repo** — rejected. It would duplicate the JLC client, the
  jlcsearch discovery, and the ADR-0007 sieve, which are the hard-won parts.

jlcsearch stays the discovery index. Hendley's own use showed it is valuable;
its known lies (ADR-0007) are already handled by the sieve.

## Decision

1. **`hendley mcp`** runs a stdio MCP server. Claude Code launches it per
   session; nothing runs in the background. It is registered once per machine
   at user scope so every project (comet, Trace-Comm-MSoM, …) gets the tools.
   The `mcp` SDK is an optional extra (`pip install -e ".[mcp]"`); the core
   install stays `requests` only.
2. **The MCP client is the agent of ADR-0007.** Claude writes the plan (net +
   sieve); `search_parts` fires it through the *existing* `run_search` and
   returns proven candidates and accounted-for misses. No new search logic.
3. **DigiKey and Mouser are `DataSource`s verified by MPN.** They answer one
   question — "can a US house buy this MPN?" — with stock, lifecycle, price
   breaks, lead time, datasheet and product URLs. They do not discover; JLC
   remains the discovery path. `PartFact` gains one optional field,
   `lifecycle`.
4. **Never writes Fusion; writes the parts DB only through `approve_part`.**
   The server never writes to Fusion (standing rule). Craig decided
   (2026-10-19) that a part approved during schematic capture is recorded as
   an approved choice, so `hendley pcba` resolves it later. `approve_part`
   takes a placed designator rather than an agent-written spec: the key is
   named from the live schematic line by the app's own path, because a key
   that differs from what Refresh derives would never be looked up.
5. **Python still does not rank or pick.** Candidates come back in index order
   with the facts; the agent recommends using Craig's bias (same package first,
   then high stock, then price).

## Consequences

- Distributor keys are optional. Without them `us_availability` reports
  "not configured" per source instead of failing.
- The in-Fusion path ("type the request without leaving Fusion") was tested
  as a Fusion add-in palette hosting the Hendley app (`fusion-addin/`). It
  works: a button in the schematic toolbar, the app in a docked palette,
  searchable over a schematic. **Shelved 2026-10-19:** it is the same web app
  in a panel that must be made very wide, taking about half the screen from
  the schematic, for nothing a browser beside Fusion lacks. Drawing-time search
  goes through this MCP server instead.
