# Fusion add-in — SPIKE (throwaway)

Goal (ADR-0010): type "find me a 3.3V LDO" **without leaving Fusion**. The
cheapest shape: a Fusion add-in that opens the Hendley app in a docked
palette. The app's search box already plans + proves free-text searches
(`/api/search` with no design line = free catalog search).

Nobody has tried an add-in against the **Electronics** workspace. This spike
answers three questions before anything real is built:

1. Can an add-in put a button in the Electronics workspace toolbar?
2. Can a palette load `http://127.0.0.1:8341` (Hendley running in WSL)?
3. Does the palette stay usable while a schematic is the active document?

## Run it (Windows, Fusion open)

1. In WSL: `cd ~/hendley && ./hendley app` (serves `127.0.0.1:8341`).
2. Copy `fusion-addin/HendleyPalette/` to a Windows folder, e.g.
   `C:\tmp\HendleyPalette\`.
3. Fusion → **Utilities → Add-Ins → Scripts and Add-Ins → Add-Ins tab →
   green +** → pick that folder → **Run**.
4. A "Hendley" palette should open on the right. Switch to an Electronics
   schematic; look for a **Hendley** button in its toolbar.
5. Read `C:\tmp\HendleyPalette\hendley-addin.log`: it lists every workspace
   and its toolbar panels, and which ones accepted the button.

## Record the answers here

| Question | Answer | Evidence |
|---|---|---|
| 1. Button in Electronics workspace | | log line |
| 2. Palette loads the app | | |
| 3. Palette usable over a schematic | | |

If 2 fails, check WSL localhost forwarding (`curl http://127.0.0.1:8341` in
PowerShell). If 1 fails but 2 and 3 pass, the palette alone is enough: it can
be opened from the Design workspace and left docked.
