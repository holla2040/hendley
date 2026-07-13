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

The app serves `http://127.0.0.1:8341/` and opens your browser. The Windows
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

**5. Install Claude Code and log in** (inside WSL). Hendley uses Claude to
interpret part values and footprint names when it builds searches:

```bash
curl -fsSL https://claude.ai/install.sh | bash
claude    # run once and follow the login prompt
```

It rides your Claude subscription — no separate API key. Without it the app
still works, but asks you to confirm each interpretation by hand.

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

## Using it

Everything happens in the app: click **Refresh** to read the design and check
live stock, click any red part to search and approve an alternate, set the
board quantity, and **Export BOM/CPL** when every row is green. Before each
Refresh, make the schematic the current document in Fusion (click its tab) —
a Refresh leaves Fusion on the board view. The guide is
[`docs/app.md`](docs/app.md).

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
