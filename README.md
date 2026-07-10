# Hendley

<img src="image/hendley.png" alt="Hendley — James Garner as Hendley, 'the Scrounger', in The Great Escape" width="160" align="right">

Hendley is a Python tool for querying JLCPCB/LCSC component data and integrating that information with Autodesk Fusion Electronics.

Today, Hendley can inspect live JLC component details, check BOM stock, discover and verify alternates, read a live Fusion Electronics design, and generate explicit Fusion migration scripts. The project is evolving toward an AI-assisted, provider-independent BOM Resolver that transforms engineering requirements into an approved manufacturing BOM.

> Hendley is named after James Garner's character in *The Great Escape*: "the Scrounger" who finds what the team needs.

## Project Status

### Available today

- JLCPCB OpenAPI authentication and component queries
- component detail, stock, pricing, parameters, and datasheet information
- assembly-library and private-inventory queries
- BOM stock checking
- alternate discovery with live JLC verification
- live Fusion Electronics reads over Fusion's local HTTP interface
- generation of Fusion `.scr` migration scripts
- optional, explicit execution of reviewed scripts through Fusion's command channel

### Target product

The target product is described in [`docs/PRD.md`](docs/PRD.md). It adds:

- a provider-independent Requirements BOM
- deterministic constraint validation
- ranked and explainable candidate recommendations
- engineer review and approval
- reusable project and user knowledge
- JLCPCB and PCBWay Provider Strategies
- provider-specific Manufacturing BOM adapters

The existing CLI is a working foundation, not yet the complete resolver defined by the PRD.

## Why Hendley

For generic components, the circuit usually requires engineering characteristics rather than one permanently fixed purchasable part.

For example:

```text
22 kΩ
±1%
0603
minimum 100 mW
```

The specific JLC/LCSC part depends on current stock, provider eligibility, lifecycle, cost, and build quantity. Manually searching and maintaining those identifiers can consume hours after the design is complete.

Hendley's long-term goal is to keep engineering intent stable and resolve procurement choices later:

```text
Fusion / ECAD design
        |
        v
Requirements BOM
        |
        v
Resolver + Provider Strategy
        |
        v
Engineer approval
        |
        v
Manufacturing BOM
```

> **Free engineers to do design.**

## Documentation

Read the design documents in this order:

1. [`docs/vision.md`](docs/vision.md) — why the project exists
2. [`docs/architecture-principles.md`](docs/architecture-principles.md) — rules the implementation must preserve
3. [`docs/PRD.md`](docs/PRD.md) — product scope, workflows, and acceptance criteria
4. [`docs/architecture.md`](docs/architecture.md) — target modules, interfaces, and migration from the current codebase

Additional repository documentation:

- [`docs/api-reference.md`](docs/api-reference.md) — reverse-engineered JLCPCB API contract
- [`docs/fusion-notes.md`](docs/fusion-notes.md) — Fusion HTTP integration details

## Install

Requires Python 3.10 or later.

```bash
git clone git@github.com:holla2040/hendley.git
cd hendley
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

Development dependencies:

```bash
pip install -e ".[dev]"
```

The core package depends on `requests`.

If the installed command is unavailable, run Hendley from the repository:

```bash
PYTHONPATH=src python -m hendley.cli ping
```

## Configure JLCPCB Credentials

Hendley reads JLCPCB OpenAPI credentials from a git-ignored `.keys` file.

```text
JLCAPI:
    AppID:     <your-app-id>
    Accesskey: <your-access-key>
    SecretKey: <your-secret-key>
```

Credential lookup order:

1. `--keys PATH`
2. `HENDLEY_KEYS`
3. `.keys` discovered by walking up from the current directory

Optional endpoint override:

```text
HENDLEY_ENDPOINT
```

Do not commit `.keys`, PEM files, private keys, or secrets.

## Quickstart

Verify request signing and API access:

```bash
hendley ping
```

Inspect one or more components:

```bash
hendley detail C2040
hendley detail C2040 C25879
```

Check a Fusion parts export or BOM for stock:

```bash
hendley stock PARTS.json --min-stock 100
```

Find and live-verify alternate candidates:

```bash
hendley alternates --list-categories
hendley alternates C315567   --category mosfets   --package "DFN-8(3x3)"   --top 10
```

Generate a Fusion migration script from reviewed changes:

```bash
hendley scr swaps.json -o changes.scr
```

## Commands

| Command | Purpose |
|---|---|
| `hendley ping` | Verify JLC credentials, signing, and permissions. |
| `hendley detail CODE...` | Retrieve component detail, stock, price tiers, parameters, and datasheet data. |
| `hendley private` | List private or consigned JLC inventory. |
| `hendley library` | Browse the JLC assembly component library. |
| `hendley fusion PARTS.json` | Validate and optionally enrich Fusion parts-export data. |
| `hendley stock PARTS.json` | Check BOM inventory and return nonzero on blocking stock problems. |
| `hendley alternates CODE ...` | Discover candidates and verify each against live JLC data. |
| `hendley scr SWAPS.json ...` | Generate Fusion `.scr` migration commands from explicit reviewed swaps. |

Use `hendley <command> --help` for the authoritative option list.

## Alternate Discovery

The JLC component detail API verifies known component codes but does not provide the parametric search needed to discover unknown alternatives.

Hendley therefore uses two stages:

1. **Discover** candidate codes using the configured parametric index.
2. **Verify** every candidate against the live JLC API for authoritative stock, price, and parameter data.

Discovery-index stock must not be treated as current. The displayed result should be based on the live verification response.

The current `alternates` command gathers and verifies candidates. It does not perform the full PRD ranking and approval workflow.

## Fusion Electronics Integration

Hendley communicates with Fusion's local Electronics interface over HTTP. No separate MCP client library is required by Hendley.

Fusion must be running with an Electronics document open and its local server enabled. See [`docs/fusion-notes.md`](docs/fusion-notes.md) for the verified handshake, WSL networking, read operations, and command execution details.

### Design writes are explicit

The Fusion Electronics object interface is read-only, but reviewed EAGLE/Fusion commands can be executed through Fusion's command channel.

Hendley can generate a `.scr` file containing package and attribute changes. Execution is an explicit engineering action and is separate from automatic BOM resolution.

A typical reviewed swap file is:

```json
{
  "design": "comet",
  "swaps": [
    {
      "designator": "R1",
      "package": "-0402",
      "lcsc": "C25768",
      "manufacturer": "UNI-ROYAL",
      "mpn": "0402WGF2202TCE",
      "attributes": {
        "DESC": "1%"
      }
    }
  ]
}
```

Generate the script:

```bash
hendley scr swaps.json -o changes.scr
```

After execution, re-read the design and verify every change. Fusion changes remain unsaved until the engineer saves the design.

## Python API

```python
from hendley import JLCClient

client = JLCClient()

detail = client.get_component_detail_by_code(["C2040"])
library_page = client.get_component_library_list(page_size=30)
private_inventory = client.get_private_component_library(
    current_page=1,
    page_size=30,
)
```

See the package source and API reference for the current public surface.

## Architecture Boundaries

The target resolver keeps these responsibilities separate:

- Fusion and other ECAD integrations capture engineering requirements.
- Data-source connectors retrieve sourced component facts.
- The Resolver Core applies deterministic constraints.
- Provider Strategies express sourcing policy.
- Ranking orders valid candidates.
- AI explains and assists with ambiguity.
- Engineers approve.
- Provider Adapters generate manufacturing files.
- Fusion migration tools remain explicit ancillary utilities.

## Roadmap

Near-term development should proceed from the PRD and architecture rather than expanding the CLI opportunistically.

Priority areas:

1. Canonical Requirements BOM schema
2. Live Fusion-to-Requirements-BOM ingestion
3. Deterministic passive-component constraints
4. JLCPCB/LCSC Provider Strategy
5. ranking and explanation
6. engineer approval and decision persistence
7. JLCPCB Manufacturing BOM Adapter
8. PCBWay strategy and adapter to validate provider independence

PCBA order placement and website-loop automation are useful future ideas but are outside the Version 1 resolver scope.

## Security

- Never commit `.keys`, private keys, PEM files, or provider credentials.
- External AI use must be explicit and configurable.
- Do not log secrets.
- Use the minimum provider permissions required.
- Treat BOM and design data as potentially proprietary.

## License

The repository currently states that it is **Proprietary**.

The product vision calls for an open and community-extensible architecture, but the repository must not be described as open source until an explicit license change is made.
