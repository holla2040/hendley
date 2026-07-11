---
description: Generate JLCPCB order files (bom.csv + cpl.csv) from the open Fusion design and check stock
---

Run `hendley pcba` (if `hendley` isn't on PATH, run `PYTHONPATH=src python3 -m hendley.cli pcba` from the repo root). Do not ping first, do not ask questions — just run it.

Then:
- Relay the stock report. A nonzero exit means blockers — name each blocked part and offer to find verified alternates.
- Confirm the two files: `~/tmp/hendley_output/bom.csv` and `cpl.csv`.
- Remind the user Fusion's engine is left on the board context — click the schematic tab before running again.
- If it errors "no schematic parts readable": the schematic view isn't active in Fusion (or a modal dialog is open). If it errors "cannot reach the Fusion bridge": Fusion isn't running with the MCP Server enabled, or the Windows portproxy doesn't match the current WSL gateway IP (`ip route | grep default`) — see README "Reading from Fusion Electronics".
