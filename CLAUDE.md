# CLAUDE.md — guidance for Claude Code in this repo

> **Picking this up fresh? Read [`HANDOFF.md`](HANDOFF.md).** It holds the current
> state, the open work in priority order, the measured facts you must not re-derive,
> and the two things that will otherwise waste your day: Fusion's MCP proxy can
> wedge on a board-to-schematic return (use the cached design or reset the MCP
> server once), and `pytest` cannot
> tell you the page never calls the API (use `scripts/ui_check.py`).

## Purpose

**Hendley** is a Python tool to query the JLCPCB parts inventory (LCSC / JLC
components) and, going forward, to consolidate part info pulled directly from
Autodesk Fusion Electronics — so the user can validate part availability and
speed up JLCPCB **PCBA** order submissions. It is a Python reimplementation of
JLCPCB's official Java OpenAPI SDK. (Named after James Garner's character
Hendley, "the Scrounger", in *The Great Escape*.)

## The product intent — the zero-touch flow (Craig, 2026-07-11)

**This is what Hendley is for. Measure every design decision against it.**

The tool opens the schematic, pulls the parts, and looks through the database for the
approved ones. Parts with no assignment → the tool finds the candidates and presents
them; the engineer picks a first choice plus a couple of backups; done. From then on,
**every re-pull of that BOM resolves automatically.**

**Never part of the workflow:** editing JSON by hand, typing part data into forms, or
any manual step for a part whose kind / value / package the schematic already states
(designator prefix + value + footprint). Inferring that is the TOOL's job, not the
user's. This rule exists because the tool once had Craig hand-editing requirement JSON
and typing a part into a record form; he called it out hard — *"what kind of workflow is
that?"* Manual forms are for deliberate curation only.

## Working with Craig (holla@solohm.com) — the project owner, a hardware designer

- **Keep responses SHORT.** His words: *"I don't want to read 10,000 pages of shit."* A
  few lines. No step-by-step essays unless he asks.
- **Lead with a recommendation.** He tends to take it. Present the real options, but say
  which one you'd pick and why.
- **Design before code.** *"We're coming up with the work to be done, not doing the
  work."* Do not start implementing while the conversation is in design mode; he will
  say when to switch.
- **Honest uncertainty beats hedged guessing.** "I'm not confident — let me verify" lands
  well. A confident guess does not.
- He is comfortable delegating **long autonomous runs** once a design is signed off, with
  per-task commits and a decision log to review afterwards.
- **Sourcing bias:** high inventory = popular = supply-chain-safe, and he will pay a
  little more for it — the opposite of "cheapest". **Same package is the top priority**
  (changing it changes the PCB).
- **⛔ No memory files.** He works on several machines and this is a team project.
  Anything worth remembering goes **in the repo** — `CLAUDE.md`, `HANDOFF.md`, an ADR, or
  a `docs/parts/` note. A note in `~/.claude/` is invisible to him everywhere else and to
  everyone else, always.

## Glossary — say these words, and only these

Agreed with Craig on 2026-07-13, because one loose word ("anchor") had already cost a
round-trip of confusion. **If you coin a new word for any of these, put it here or do
not use it.** Walked through a real part, `MB10S`:

| word | for `MB10S` | what it is |
|---|---|---|
| **value** | `MB10S` | the schematic VALUE field the designer typed |
| **family** | `MB10S` | the **incomplete** part number: whatever is in **value**, or in the **MPN attribute** if they filled that instead — **the MPN attribute wins**. `MP`/`MF` are NEVER a family (stale SnapEDA imports; `MP` once said `MB6S`, a 600 V part, where the value said `MB10S`, a 1000 V one). |
| **land** | the 4 pads under it | the **physical** copper the part solders to. The thing that actually constrains what may be ordered. It has TWO names — one in the library, one in the catalog — and telling them apart is most of this job. |
| **footprint** | `SOIC-4` | the **library's** name for the land, *plus its geometry* from the library's own headline (`"150 mil"`, `"10.30 X 7.50"`). A local convention: it cannot tell a 3.9 mm body from a 7.5 mm one. The geometry can. |
| **package** | `MBS` | the **catalog's** name for that same land. What jlcsearch filters on. **Never guess it** — the library says `SOIC-4` and the catalog says `MBS`; ask the catalog for its own list. One land can have SEVERAL package words (`SOIC-8` *and* `SOP-8`), and they hold different parts, so take them all. |
| **class** | `Bridge Rectifiers` | the **catalog's** `secondTypeName`. What the part *is*. **A label — never a search term, never a sieve term.** The catalog's class is consistent; the *index's* `subcategory` is NOT (it files C2886577, an MB10S on a real board here, as `Diodes - General Purpose`), which is why it lives in `UNPROVABLE_COLUMNS`. |
| **trap** | `MB6S` | a part that **fits the same land and is NOT the same part**. It solders down perfectly and ruins the board. `MB6S` is 600 V where `MB10S` is 1000 V; `PCF8574A` is a different I²C address; `MAX485` is the +5 V part on the identical SOIC-8 pinout. Only the datasheet knows — the catalog never will. Traps are **shown, never silently substituted**. |
| **part** | `C2886577` | a full MPN + LCSC code you can actually **order** |

**The sentence: family + footprint → package → the parts.** The class tells you which
traps to watch; it finds nothing and rejects nothing.

A **family is not a part** and must never be pinned as one — that is ADR-0008, and it
is the bug that shipped `ULN2003` to the resolver as if you could order it.

(Pre-existing and unchanged, from ADR-0007: the **net** is the coarse query the index
actually honours; the **sieve** is every constraint, proven per part over data we hold.
A **house brand** is a JLC-only clone — `PCF8574DWR(UMW)`, `ULN2003ADTR(XBLW)` — which
the web will never name and which is frequently the better buy.)

## Architecture

Layering follows `docs/architecture.md` §13: ingestion → domain → resolver/knowledge → providers, with the CLI and the app as thin consumers. Nothing under `resolver/`, `knowledge/`, or `domain/` may import concrete `providers/*` or `datasources/jlc` — only the base protocols. Package-specific gotchas live in that package's own `CLAUDE.md` (`app/`, `ai/`, `resolver/`, `datasources/jlc/`, `ingestion/fusion/`, `requirements/`, `knowledge/`, `domain/`, `providers/` under `src/hendley/`); they load when you work there.

### Invariants — never break these
- **Python never composes searches, invents filters, or parses names** (ADR-0006). Judgment belongs to the agent and the engineer. The one authorized exception: a family fires `search=<family>&package=<package>` (ADR-0008).
- **A family is not a part** — never pin it as `line.mpn` (ADR-0008).
- **Never re-add an `UNPROVABLE_COLUMNS` column** to `CATEGORY_COLUMNS`. A part's class comes from the catalog's `secondTypeName`, never from an index column.
- **Never guess a catalog package from a footprint name** — ask the catalog for its own list.
- **Traps are shown, never silently substituted.**
- **Never order against the cached stock/price** in `choice_provider_ids` — advisory only.
- **Never show the word "rank" in the UI.**
- `hendley scr` / `migration/fusion_script/` are **retired** (2026-07-13): code and tests remain; never invoke them.
- Tests never touch `~/.hendley`: fixtures pass tmp `db_path`, `draft_path`, and `cache_path`.

### Files worth knowing
- `data/cpl-rotations.json` — per-footprint CPL rotation corrections. Some
  library footprints are drawn rotated vs. what JLC's feeders expect; each fix
  is recorded ONCE, keyed by **LCSC code or library footprint name — never
  designator** (the flaw belongs to the library model and follows the part
  across designs). `rotationOffsetDeg` is positive = CCW (JLC's convention).
  When the user reports hand-rotating a part in JLC's order preview, add an
  entry here (lcsc, mpn, footprint, offset, verified date/design).
- Docs: `docs/cli.md` (CLI guide), `docs/app.md` (app guide), `docs/api-reference.md` (the API contract — source of truth), `docs/fusion-notes.md` (Fusion HTTP recipe), `docs/parts/` (part-class notes the agent reads; `README.md` has the format), `docs/writing-a-provider.md`, `docs/mcp.md` (`hendley mcp`), `docs/adr/`.
- `.keys` — credentials (git-ignored; never commit). `notes` — the developer-portal URL (not the API host).

## `help` — the plain-speak menu (READ THIS FIRST)

The user must never need the README or the source to use this project, and
never need to guess magic words. Match their message against this table
**before anything else**:

- **`help`** (bare word, or "what can you do", "commands", "menu") → print the
  menu below **verbatim**. Run nothing. Ask nothing. Add nothing.
- **`jlc`**, **`hendley jlc`**, **`pcba`**, "order files", "generate files for
  JLC/JLCPCB", "bom and cpl", or any ask for the JLC order files → run
  **`hendley pcba`** immediately. Do NOT ping first, do NOT present options, do
  NOT ask what they want — run it, then relay the stock report and flag
  blockers. (`hendley jlc` is a real alias of `pcba` — if they typed it, run it.)
- **`app`**, "start the app", "open hendley" → run **`hendley app`** (the
  primary UI: the single-page order workbench at http://127.0.0.1:8341).
- "resolve the BOM", "order N boards", "prepare a PCBA order from specs" →
  the **order-bom skill** (`.claude/skills/order-bom/SKILL.md`): Requirements
  BOM → `hendley resolve --queue` → one approval batch → `hendley bom`.
- "is `<Cxxxx>` in stock", "check `<Cxxxx>`" → `hendley detail <code>`,
  summarize stock/price/package.
- "find a replacement/alternate for `<part>`" → the `find-alternate` skill (`.claude/skills/find-alternate/SKILL.md`).
- "check stock on the design/BOM" → `hendley pcba --no-verify` is NOT it — run
  the full `hendley pcba` (its stock report is the check), or `hendley stock
  PARTS.json` if they point at a parts JSON.
- "what parts do we use for `<spec>`", "house parts", "the AVL" →
  `hendley db lookup/list` (local SQLite, no credentials needed).

### The menu (print verbatim on `help`)

```
Hendley — say any of these:

  app                      open the Hendley app (the single-page order workbench)
                           in your browser — the main way to drive everything below
  jlc                      generate bom.csv + cpl.csv from the open Fusion design
                           and check JLC stock (= hendley pcba). Fusion must be
                           open with the SCHEMATIC view active.
  order 25 boards          resolve the design against your approved house parts
                           (the AVL) at that quantity, one approval batch for any
                           gaps, then emit the upload CSV + release snapshot
  is C25804 in stock?      live stock / price / specs for one part
  find a replacement for R8 (out of stock / different package / different value)
                           discover + verify alternates and recommend one. You make
                           the change in Fusion — Hendley never edits the design.
  check stock              stock-check every part in the open design before ordering
  house parts              show the approved parts list (AVL) for a spec, or all
  help                     this menu

Order files land in ~/tmp/hendley_output/ (bom.csv + cpl.csv, nothing else).
Out-of-stock parts are flagged; DNP parts (DNP attribute = 1, or value = DNP) are left out; rotation
fixes in data/cpl-rotations.json apply automatically. After a run, click Fusion's
schematic tab before running again.
```

## The workflow — having a conversation about JLC parts

The point of Hendley: the user runs Claude in this repo, says something in plain
words about a JLC part, and you have the conversation — **you are the interpreter
of their words into the existing tooling.** Four standing rules for that role:

- **⛔ Hendley READS the design. It does NOT write to it.** (Standing rule,
  2026-07-13.) Hendley is the tool that produces **the BOM** — it is not a tool for
  modifying the circuit. **Do not generate a `.scr`, do not run `hendley scr`, and
  do not fire `Electron.run` / `fusion_mcp_execute` to change a design.** No
  `CHANGE PACKAGE`, no `ATTRIBUTE`, no `VALUE` writes over the bridge. When a part
  needs to change, you **recommend** it — the designer makes the edit in Fusion
  themselves, then you re-read. The bridge is read-only in practice, whatever it is
  capable of. (The `.scr` machinery and the `Electron.run` write path still exist in
  the tree and are documented below for history; they are **retired** and must not
  be used.)
- **Everything you need to drive the tools is documented** — this file,
  `docs/cli.md` + `docs/app.md` (the README is a TL;DR pointing there), and
  the module docstrings (each `src/hendley/<pkg>/CLAUDE.md` names them). **Do not read the source to
  figure out how to use a tool.** If something genuinely isn't documented, say so;
  don't reverse-engineer it from the code.
- **Never modify Hendley's source to satisfy a request.** You translate the user's
  intent into calls to the tools *as they are*. If a request needs a capability a
  tool doesn't have, tell the user — don't add it.
- **Running the CLI:** prefer `hendley` if it's on PATH. On a fresh checkout where
  `pip install -e .` didn't land it on PATH (or the venv isn't active), run it as
  a module from the repo root — `PYTHONPATH=src python3 -m hendley.cli <cmd>` (or
  `python3 -m hendley <cmd>`; plain `python` is missing on some hosts), which
  needs only `requests`. Every `hendley <cmd>` below works identically that way.

**⭐ The one-prompt job — "Generate the files necessary for JLCPCB"** (or any
ask for the BOM/CPL/order files): run **`hendley pcba`**. One command, no
scratch scripts, no hand-built bridge pipeline — it reads the live design over
the HTTP bridge (schematic first, then a deliberate `BOARD;` transition), applies
`data/cpl-rotations.json`, verifies stock against the live JLC API, and writes
**exactly two files** — `bom.csv` + `cpl.csv` — to `~/tmp/hendley_output/`.
Preconditions: Fusion open with the Electronics design active and no modal
dialog (and the port-forward up). Afterward: relay the stock report (nonzero
exit = blockers), and if they mention having to hand-rotate a part in
JLC's order preview, add the correction to `data/cpl-rotations.json` (keyed by
LCSC/footprint) so it's automatic from then on.

**Changing a part** (out of stock / different package / different value) has one workflow: the **`find-alternate` skill** (`.claude/skills/find-alternate/SKILL.md`). ⛔ It ends at a recommendation — **you do not apply the change** (standing rule, 2026-07-13). Give the user the designator, the chosen `Cxxxx`, the MPN, the manufacturer, the exact package, and the caveats; **they** edit Fusion; then re-read the design over the bridge to confirm. **Do NOT** run `hendley scr`, write a swap JSON, generate a `.scr`, or fire `Electron.run` / `fusion_mcp_execute` at the design. Do not offer to. If the user asks for a `.scr`, tell them that path is retired and confirm before doing anything.

**Do NOT** filter or rank on Basic vs. Extended — it is a fee attribute: display it, never select on it (fee detail in the `find-alternate` skill). **Do NOT** download the whole catalog "for one part" — jlcsearch is the discovery surface.

**CLI output:** only `stock` and `alternates` accept `--json`; `detail`, `private`, `library`, `fusion` already print JSON and error on `--json`. `pcba`, `resolve`, `bom` exit nonzero on blockers. Flags are exactly those in `hendley <cmd> --help`; full reference in `docs/cli.md`.

## ⚠️ Before ANY Fusion read

Ensure the Electronics design is active and no modal dialog is open. Hendley
tries `EDIT .S1;` when schematic entities are unavailable, but this Fusion MCP
build can wedge its proxy when returning from board context. If reads remain
empty and `EDIT .S1;` reports recursive proxy failure, toggle the Fusion MCP
server or restart Fusion once; do not keep retrying it.

An open dialog still silently blocks reads—they come back **empty, not
erroring**. Do not discover sheets by incrementing `EDIT .S<N>`: Fusion creates
a missing sheet. Read `electronics.Sheet` first, then switch only to returned
sheet numbers.

A full Refresh captures every schematic sheet before its one-way-for-that-run
`BOARD;` transition and caches the whole design to
`~/.hendley/design-cache.json`; use that cache for repeatable UI work
(`scripts/ui_check.py --live` does exactly this). See `HANDOFF.md`.

## Fusion access from WSL (read side)

**Access is 100% plain HTTP — this project uses NO MCP connector or client.**
Hendley reads a live Fusion Electronics design by issuing JSON-RPC `POST`s
directly to Fusion's local HTTP endpoint with `curl`/`requests`. Do **not** use
Claude Desktop's "Autodesk Fusion" connector, an MCP client, or `claude mcp add`
— there is none in this project, and you don't need one. **All communication is
HTTP.** You call the **`fusion_mcp_electronics_read`** tool by `POST`ing a
`tools/call` request over HTTP (that's the tool's literal name — it is invoked
via HTTP, not through any MCP client).

The handshake is **not** "just POST initialize then tools/call": you must hit
the **Windows host IP, not `127.0.0.1`** (loopback isn't reachable from WSL) yet
still **send a `Host: 127.0.0.1:27182` header** (the server now validates `Host`
and 403s "Invalid Host header" on the gateway IP — connect to the gateway,
spoof the header to loopback), capture the **`MCP-Session-Id` HTTP response
header** and resend it on every request, and `POST` a
**`notifications/initialized`** message before any `tools/call` — skip any of
these and you get the confusing `Invalid Host header` / `Missing
MCP-Session-Id header` / `Session not initialized` errors that have made past
agents hand-write their own client. **Do not re-derive it or read source — copy
the complete, verified HTTP recipe (handshake + a Part→Attribute→`LCSC` worked
example) from `docs/fusion-notes.md` → "Talking to Fusion over HTTP — the full
recipe".** The JLC `Cxxxx` code is the part's **`LCSC`** attribute (read
`electronics.Attribute` filtered by `part_object_id`); MPN is `MPN`.

The one setup requirement is on the Fusion/Windows side: Fusion running with an
Electronics doc open and its endpoint enabled at **Preferences > General > API >
Fusion MCP Server** (this Autodesk toggle is the *only* thing called "MCP" — it
just publishes the HTTP endpoint Hendley then talks to).

⚠️ **Attribute reads are part-scoped, and `object_id`s aren't stable.** Filtering
`electronics.Attribute` by `name` alone (or unfiltered) returns **empty** — you
must pass the live `part_object_id`. And `object_id`s are reassigned on every
reload (R1 was `2812` one session, `11225` the next), so always re-read
`electronics.Part` for the current id in the same session. (This — not "the
reader can't see JLC attrs" — was the cause of earlier empty reads;
`LCSC`/`MPN`/`MANUFACTURER` do read back fine when scoped.)

## ⛔ RETIRED — Fusion write side (`Electron.run`). DO NOT USE.

> **Retired 2026-07-13.** Hendley is the tool that builds **the BOM**. It is **not**
> the tool that modifies the circuit. Everything in this section still *works* — that
> is exactly why the prohibition is written down. **Do not fire `Electron.run`, do not
> use `fusion_mcp_execute` to change a design, do not generate or run a `.scr`.** The
> designer edits the schematic in Fusion; you read it back. Kept below only so nobody
> re-discovers it and assumes it is sanctioned.

The mechanics (and why they still work) are in `docs/fusion-notes.md` → "The WRITE path". Do not follow them.

⚠️ **WSL port-forward gotcha (cost us a debugging session):** to reach Fusion's
Windows-loopback port from WSL2, forward it on Windows with
`listenaddress=<WSL gateway IP>` (e.g. `172.17.64.1`, from `ip route | grep
default`) — **never `listenaddress=0.0.0.0`**. A `0.0.0.0:27182` listener hijacks
the loopback that Fusion's server and the Claude Desktop connector use, so they
"connect then close unexpectedly" and Desktop stops connecting. Symptom check:
Windows `curl http://127.0.0.1:27182/mcp` returns `{"error":"Not Found"}` when
healthy; if it closes unexpectedly, delete any `0.0.0.0` portproxy rule
(`netsh interface portproxy delete v4tov4 listenaddress=0.0.0.0 listenport=27182`).
See `docs/fusion-notes.md` "Reaching Fusion from WSL2".

## Verified endpoint facts

- API host: **`https://open.jlcpcb.com`** (the default in `config.py`).
- `api.jlcpcb.com` is the developer **portal / console**, NOT the API host.

## Run / test

`./hendley <cmd>` is the zero-setup launcher (builds `.venv` on first run). Dev: `pip install -e ".[dev]"`, then `pytest` and `ruff check .`. `hendley ping` verifies credentials + signing.

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
