# Hendley

<img src="image/hendley.png" alt="Hendley — James Garner as Hendley, 'the Scrounger', in The Great Escape" width="160" align="right">

Hendley turns an Autodesk Fusion Electronics design into a ready-to-upload
JLCPCB PCBA order. It reads the open design, checks every part against live
JLC stock, helps you pick verified alternates when something is short —
remembering the parts you approve so the next order reuses them — and exports
`bom.csv` + `cpl.csv`, all from one page in your browser.

> Named after James Garner's character in *The Great Escape*: "the Scrounger",
> who finds what the team needs.

## Setup (Windows 11 + WSL)

Hendley runs in WSL and talks to Fusion running on Windows.

**1. Install WSL** (skip if you already have it). In PowerShell as
Administrator:

```powershell
wsl --install
```

Reboot when prompted and let Ubuntu finish creating your Linux user.

**2. Install the prerequisites** inside Ubuntu (Python 3.10+ is required;
Ubuntu 22.04 and later ship it):

```bash
sudo apt update && sudo apt install -y git python3 python3-venv
```

**3. Clone and run.** The `./hendley` launcher bootstraps everything else
itself on first run (~30 seconds); after that it starts immediately:

```bash
git clone https://github.com/holla2040/hendley.git
cd hendley
./hendley app
```

The app serves `http://127.0.0.1:8341/` and opens your browser. Codex is the
default agent interpreter; launch with `./hendley app --interpreter claude` to
use Claude for that run (or pass `--interpreter codex` explicitly). The Windows
browser reaches that address directly — no networking setup is needed for the
app itself.

**4. Add your JLCPCB credentials.** Create a git-ignored file named `.keys`
in the repo folder, using the OpenAPI keys from JLCPCB's developer portal:

```text
JLCAPI:
    AppID:     <your-app-id>
    Accesskey: <your-access-key>
    SecretKey: <your-secret-key>
```

The app starts without it, but live stock checks and searches need it. Never
commit `.keys` or any secret.

**5. Install Codex CLI and log in** (inside WSL). Hendley uses an ephemeral,
read-only `codex exec` when you open an uncached red/yellow part:

```bash
codex login
```

Install the CLI from the official Codex CLI instructions if `codex` is not yet
available. It rides your Codex login—no separate API key. Without it the app
still works, but leaves new ambiguous parts unresolved. Claude remains an
optional compatibility backend: set `HENDLEY_INTERPRETER=claude`.

**6. Connect Fusion** (needed for the Refresh button to read your design):

- In Fusion on Windows: open your Electronics document, enable
  **Preferences > General > API > Fusion MCP Server**, and keep the
  **schematic view active** with no dialog open.
- Forward Fusion's port so WSL can reach it. Get the gateway IP inside WSL —
  `ip route | grep default` (e.g. `172.17.64.1`) — then in PowerShell as
  Administrator:

  ```powershell
  netsh interface portproxy add v4tov4 listenaddress=172.17.64.1 listenport=27182 connectaddress=127.0.0.1 connectport=27182
  ```

  Substitute your gateway IP, and **never use `listenaddress=0.0.0.0`** (it
  breaks Fusion's own connections). The gateway IP can change after a WSL
  restart — re-check it if Refresh stops working. Details and troubleshooting:
  [`docs/fusion-notes.md`](docs/fusion-notes.md).

### Troubleshooting: Refresh can't reach Fusion

The app's **Refresh** reads the design over this bridge. When it fails (or a
manual check from WSL returns `000` / connection refused instead of `200`), work
this checklist top to bottom — it's ordered by how often each one is the cause.

Manual up/down check from WSL (`200` = up, `000` = down):

```bash
GW=$(ip route | grep default | awk '{print $3}')
curl -s -m5 -o /dev/null -w '%{http_code}\n' -H 'Host: 127.0.0.1:27182' \
  "http://$GW:27182/mcp" -X POST -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"ping","version":"0"}}}'
```

1. **Is Tailscale running? Turn it off.** This is the one that bites most often.
   Tailscale hijacks the Windows loopback the port-forward relies on, so the
   forward accepts nothing even though every rule looks correct (same failure
   mode as a `0.0.0.0` portproxy rule). In PowerShell:

   ```powershell
   tailscale down
   ```

2. **Is Fusion's server actually up?** On Windows:

   ```powershell
   curl http://127.0.0.1:27182/mcp
   ```

   Any error *response* (e.g. "Server does not offer an SSE stream" /
   `{"error": "Not Found"}`) means it's **up**. A connection refused / closed
   means it's down — enable **Preferences > General > API > Fusion MCP Server**
   and make sure an Electronics document is open.

3. **Is the port-forward actually listening?** On Windows:

   ```powershell
   netstat -ano | findstr :27182
   ```

   You need **two** `LISTENING` lines: `127.0.0.1:27182` (Fusion) **and**
   `<gateway>:27182` (the proxy). If only the `127.0.0.1` line shows, the proxy
   rule exists in the registry but its socket never bound — continue to 4 and 5.

4. **Does the rule's `listenaddress` match the *current* gateway?** The WSL
   gateway can change after a reboot. In WSL, `ip route | grep default` gives the
   live gateway; on Windows, `netsh interface portproxy show v4tov4` shows what
   the rule points at. If they differ, re-add the rule with the right address
   (and delete any stale one). Never use `listenaddress=0.0.0.0`.

5. **Force the proxy to bind.** If the rule is correct but step 3 still shows one
   listener, restart the IP Helper service so it re-reads the store:

   ```powershell
   Restart-Service iphlpsvc -Force
   ```

6. **Firewall.** If the Windows listener responds locally (step 2) but WSL still
   can't reach `<gateway>:27182`, allow the inbound port once:

   ```powershell
   New-NetFirewallRule -DisplayName "WSL Fusion MCP 27182" -Direction Inbound -LocalPort 27182 -Protocol TCP -Action Allow
   ```

After any fix, re-run the WSL check above (or just hit Refresh).

## Using it

Everything happens in the app: click **Refresh** to read the design and check
live stock, click any red part to search and approve an alternate, set the
board quantity, and **Export BOM/CPL** when every row is green. Before each
Refresh, make the schematic the current document in Fusion (click its tab) —
a Refresh leaves Fusion on the board view. The guide is
[`docs/app.md`](docs/app.md).

## A representative Hendley validation design

Hendley is best tested with several small circuits on one schematic, not with a
random bag of symbols. The fixture below is an electrically plausible controller
board, but each block deliberately presents a different sourcing question:
exact provider part, complete MPN, incomplete family, functional label, local
shop convention, ordinary specification, custom footprint, DNP, and genuinely
missing information.

The goal is **not** for every line to turn green automatically. A legitimate
test includes lines Hendley must refuse until an engineer supplies the missing
electrical intent. Do the first Refresh before adding Hendley-specific metadata
or changing prompts; preserve that first-pass result as the generalization test.

### Fixture conventions

- Use the named reference designators, schematic `VALUE`, and footprint shape.
- Where the table says **no LCSC**, omit the `LCSC` attribute deliberately.
- Where it says **VALUE family**, put the text in the displayed VALUE and leave
  `MPN` empty. Where it says **MPN family**, put it in `MPN` as well; Hendley
  must still recognize that it is not necessarily an orderable part.
- For an **exact control**, choose a real part you already use and populate its
  `LCSC`, `MPN`, and `MANUFACTURER` attributes. The code itself is not prescribed
  here because stock and catalog choices change.
- Give custom footprints meaningful geometry/headlines where Fusion permits it.
  Hendley should reason from measured pitch/body/span, not a convenient name.
- These blocks may be laid out independently and joined only by `+12V`, `+5V`,
  `+3V3`, and ground. Test points make the electrical intent reviewable.

### 1. Input power, protection, and diode identity

This block exercises ordinary passives, MOSFET specifications, regulator
families, four diode classes, and the shop's Zener aliases.

| Ref | Circuit role and connection | Fusion VALUE | Footprint | Identity setup | Hendley must demonstrate |
|---|---|---|---|---|---|
| J1 | 12 V input, pins `VIN`/`GND` | `POWER IN` | 2-pin terminal block | no LCSC acceptable | unmatched connector remains visible, not invented |
| F1 | series input fuse | `750mA` | `1206` | no LCSC | specification interpretation and approval |
| Q1 | P-channel reverse-polarity device | `P-CH:40V` | `TO-252` | no LCSC | local transistor spec, not a literal family search |
| D1 | input TVS from protected 12 V to ground | `SMBJ18A` | `DO-214AA(SMB)` | exact MPN, no LCSC | complete MPN versus provider identity |
| U1 | 12 V to 5 V regulator module | `R-78E5.0-1.0` | 3-pin SIP, 2.54 mm pitch | VALUE family, no LCSC | same-land voltage/current traps and package vocabulary |
| U2 | 5 V to 3.3 V LDO | `AP2112K-3.3` | `SOT-23-5` | MPN family, no LCSC | suffix/package interpretation on an unseen regulator |
| C1,C2 | input/output bulk capacitors | `10u/25V` | radial or SMD can with dimensions | no LCSC | voltage “or better” and physical envelope |
| C3,C4 | regulator bypass | `1u` | `0603` | no LCSC | deterministic passive spec |
| FB1 | 3.3 V rail bead | `600` | `0603` | no LCSC | ferrite classification rather than inductor guess |
| D2 | 10 V Zener test, fed from +12 V through R1 | `VZ10` | `SOD-323` | no MPN/LCSC | shop alias becomes a proposed Zener spec |
| D3 | identical independent Zener test | `10Z0` | `SOD-323` | no MPN/LCSC | second explicit-Z spelling reaches the same reviewed requirement |
| D4 | ambiguous reverse-voltage test | `1000V` | `SOD-323` | no MPN/LCSC | voltage alone does not invent Zener class |
| D5 | small-signal clamp from a test input to +3V3 | `1N4148` | `SOD-323` | VALUE family, no LCSC | small-signal diode separated from Zener/Schottky |
| D6 | reverse-polarity/load Schottky | `SS14` | `SMA` | VALUE family, no LCSC | Schottky catalog class, not the broken index flag |
| R1,R2,R3 | Zener current limit, one per alias | `2.2k` | `0603` | no LCSC | grouping of identical specifications |
| TP1-TP4 | protected input, +5 V, +3V3, ground | blank | local test-pad footprint | DNP attribute | intentional DNP stays out of BOM/CPL |

Do not tie the diode tests to one node; give each its own resistor and test
point so the schematic records the distinct VALUE conventions without making
the circuit depend on their tolerance.

### 2. MCU, clocks, USB, I²C, and RS-485

This is the central identity test: one exact mounted part, several real
families, and one intentionally underspecified functional label.

| Ref | Circuit role | Fusion VALUE | Footprint | Identity setup | Expected behavior |
|---|---|---|---|---|---|
| U10 | controller | `STM32F103RET6` | `LQFP-64` | populate real LCSC/MPN/manufacturer | exact provider control; no discovery needed |
| Y1 | MCU crystal | `8MHz-20pF` | 4-pad 5.0 × 3.2 mm crystal | real LCSC control | exact part and placement path |
| C10,C11 | crystal loading | `20p` | `0603` | no LCSC | grouped passive spec |
| U11 | USB-to-UART bridge connected to MCU UART | `FT232RL` | `SSOP-28` | VALUE family, no LCSC | family/package suffix and FT232RNL migration warning |
| J10 | USB connector for U11 | `USB` | USB Mini-B or USB-C footprint | exact control if available | connector identity and CPL placement |
| U12 | I²C GPIO expander with A0-A2 straps | `PCF8574` | wide `SOIC-16-300mil` | VALUE family, no LCSC | PCF8574A address trap and body-width proof |
| U13 | precise 3.3 V half-duplex transceiver | `SP3485` | narrow `SOIC-8` | VALUE family, no LCSC | valid family search and 5 V/temperature traps |
| U14 | second half-duplex transceiver channel | `RS485` | same narrow `SOIC-8` | functional VALUE only | **must remain unresolved** until voltage/speed are stated |
| J11,J12 | A/B/GND bus connectors | `RS485 PORT` | 3-pin terminal block | no LCSC acceptable | manually fitted connector remains explicit |
| R10,R11 | RS-485 termination, one per channel | `120` | `0603` | no LCSC | ordinary grouped spec |
| R12-R15 | bus bias resistors | `680` | `0603` | no LCSC | quantity/grouping and stock resolution |
| U15 | I²C EEPROM on the same bus | `24LC256` | `SOIC-8` | MPN family, no LCSC | unseen memory-family handling |
| R16,R17 | I²C pull-ups | `4.7k` | `0603` | no LCSC | shared house part reuse |

`U13` and `U14` are intentionally similar. Hendley should find candidates for
`SP3485`; it should not pretend that the word `RS485` establishes 3.3 V versus
5 V, slew rate, duplex mode, unit load, or temperature grade.

### 3. Analog measurement block

This block adds op-amps, a reference, a sensor, tolerance/rating constraints,
and an exact-MPN-without-provider case.

| Ref | Circuit role | Fusion VALUE | Footprint | Identity setup | Expected behavior |
|---|---|---|---|---|---|
| U20 | dual op-amp: one divider buffer, one low-pass buffer | `LM358` | `SOIC-8` | VALUE family, no LCSC | popular 100-row family without truncation lies |
| U21 | 2.5 V reference feeding ADC test point | `MCP1525` | `SOT-23-3` | complete MPN in `MPN`, no LCSC | distinguish complete MPN from family/default |
| U22 | I²C temperature sensor | `TMP102` | `SOT-563` or the exact land you choose | VALUE family, no LCSC | new sensor family and exact geometry requirement |
| R20,R21 | 12 V divider into U20 | `100k`, `27k` | `0603` | no LCSC | distinct resistor house parts |
| R22,C20 | ADC low-pass | `10k`, `100n` | `0603` | no LCSC | mixed R/C deterministic inference |
| C21 | reference bypass | `1u` | `0603` | no LCSC | reuse existing approved capacitor |
| TP20,TP21 | buffered divider and 2.5 V reference | blank | local test pad | DNP attribute | DNP handling |

Use the actual package variant you intend for `TMP102`; do not rename a
different land to make the example convenient. A safe refusal is a valid test.

### 4. Drivers, isolation, and load outputs

This block tests same-land functional traps that package checking cannot catch.

| Ref | Circuit role | Fusion VALUE | Footprint | Identity setup | Expected behavior |
|---|---|---|---|---|---|
| U30 | seven-channel low-side driver from MCU GPIO | `ULN2003` | narrow `SOIC-16` | MPN family, no LCSC | suffix decoder excludes wide/TSSOP/DIP lands |
| D30-D32 | indicator LEDs on three driver outputs | `RED`, `GRN`, `AMBER` | `0603` | no LCSC | LED specs, not families |
| R30-R32 | LED series resistors | `1k` | `0603` | no LCSC | grouped approved choice |
| U31 | high-CTR optocoupler into an MCU input | `LTV-352T` | `SOP-4-2.54mm` land | VALUE family, no LCSC | CTR trap versus LTV-357T/EL357N |
| R33 | optocoupler LED resistor from +5 V | `1k` | `0603` | no LCSC | house-part reuse |
| R34 | optocoupler output pull-up | `10k` | `0603` | no LCSC | house-part reuse |
| U32 | digital isolator between two logic headers | `ISO7721DR` | `SOIC-8` | exact MPN text, no LCSC | complete orderable name without provider code |
| Q30 | low-side open-drain load output | `AO3400A` | `SOT-23` | VALUE family, no LCSC | MOSFET note gap and safe review |
| D33 | flyback diode across external inductive load | `SS14` | `SMA` | reuse D6 family | cross-designator family consistency |
| J30 | external load connector | `LOAD` | 2-pin terminal block | no LCSC acceptable | unmatched connector behavior |
| U33 | bridge rectifier feeding a lightly loaded test node | `MB10S` | physical MBS land named locally `SOIC-4` | VALUE family, no LCSC | library/catalog package vocabulary mismatch; MB6S trap |

The `MB10S` local footprint name should remain the library's natural name. Do
not rename it `MBS` merely to help Hendley—the mismatch is the test.

### 5. Negative controls and workflow edges

Add these last. They verify that Hendley reports uncertainty instead of making
the fixture artificially green.

| Ref | Setup | Expected behavior |
|---|---|---|
| D40 | blank VALUE, `SOD-323`, no attributes | asks what diode requirement this is; never invents a voltage/class |
| U40 | a real 144-pin FPGA in a custom footprint whose name omits body/pitch; include an accurate Fusion package headline or dimensions | proves geometry or refuses; never accepts a name-only alias |
| J40 | populated custom connector with no LCSC | remains visible as an intentionally unmatched/manual item |
| J41 | same connector with `DNP=1` | excluded from order files |
| R40 | `DNP` as the literal VALUE | excluded from order files |
| U41 | any known exact part with valid `LCSC`, but intentionally zero/insufficient live stock when available | exercises stock escalation without changing identity |
| U42 | exact MPN plus a deliberately stale legacy `MP` attribute naming a different part | `MPN` wins; `MP` is carried but never used as identity |
| TP40 | odd local test-pad footprint, DNP | pseudo/mechanical handling without catalog search |

### What to record from the first run

Before fixing anything, save the intake cache and classify every populated line:

1. **Correctly exact** — Hendley used the stated provider part or complete MPN.
2. **Correctly discovered** — family plus land produced relevant orderable rows.
3. **Safely unresolved** — information was genuinely missing or geometry unproved.
4. **Wrong candidate offered** — the dangerous category; capture query, package,
   catalog class, failed terms, and prompt/cache provenance.
5. **Local knowledge required** — a real shop convention that belongs in
   `docs/parts/`, scoped narrowly and confirmed by an engineer.

The fixture succeeds when Hendley distinguishes those five outcomes honestly.
“Every row green” is not the acceptance criterion.

## Documentation (for developers)

- [`docs/app.md`](docs/app.md) — the app: the single-page order workbench
- [`docs/cli.md`](docs/cli.md) — the CLI: commands, order files, the
  design-change workflow, the `.scr` format, the Python API
- [`docs/vision.md`](docs/vision.md) — why the project exists
- [`docs/PRD.md`](docs/PRD.md) — product scope, workflows, acceptance criteria
- [`docs/architecture.md`](docs/architecture.md) — modules, interfaces, and
  open decisions (with [`docs/architecture-principles.md`](docs/architecture-principles.md))
- [`docs/writing-a-provider.md`](docs/writing-a-provider.md) — adding a board
  house (strategy + adapter, PCBWay as the reference)
- [`docs/api-reference.md`](docs/api-reference.md) — the JLCPCB OpenAPI contract
- [`docs/fusion-notes.md`](docs/fusion-notes.md) — Fusion HTTP integration
  (handshake, reads, writes, WSL2 networking)
- [`docs/adr/`](docs/adr/) — architecture decision records

## License

Proprietary. The vision calls for an eventual community-extensible
architecture, but the repository is not open source unless the license is
explicitly changed.
