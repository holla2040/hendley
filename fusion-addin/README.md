# Fusion add-in — SPIKE (throwaway) — SHELVED 2026-10-19

**Decision (Craig, 2026-10-19): shelved.** All three questions came back yes,
but the palette is only the existing web app shown inside Fusion. To be usable
it has to be made very wide, which takes about half the screen from the
schematic, and it adds nothing a browser window beside Fusion doesn't already
do (`./hendley app` must still run in WSL). The drawing-time path is Claude
Code beside Fusion with the `hendley` MCP tools (`docs/mcp.md`). Revisit only
if an add-in can do something a browser cannot. Kept as a record of what the
Fusion API allows.

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
| 1. Button in Electronics workspace | **Yes** (2026-10-19, WSL) | `button added to SchEditorEnvironement/EagleSchScriptsAddinsPanel`; also `BoardLayoutEnvironement/EaglePcbScriptsAddinsPanel`, `PCBDesignEnvironement/EagleScriptsAddinsPanel`, and the five `Electron*` library editors |
| 2. Palette loads the app | **Yes** | palette showed the full app over WSL `127.0.0.1:8341`, cached design "Pendant 2 I_O Schematic" loaded |
| 3. Palette usable over a schematic | **Yes** | docked right over a blank schematic; typed `3.3V LDO SOT-23`, Search ran and rendered results. The palette's close button hides it; the Hendley button reopens it |

Findings from running it in the palette (2026-10-19):

- **Search found nothing usable.** The plan for `3.3V LDO SOT-23` asked only
  the package word `SOT-23` (9 rows, none 3.3 V). The 3.3 V parts are filed
  under `SOT-23-3` / `SOT-23-3L`, and C5446 (XC6206P332MR-G, Basic, 426 k)
  is not in the index at all (`docs/mcp.md` → Verified, WSL). A free search
  has no footprint, so nothing widens the package word to the land's spellings.
- **Refresh on a blank schematic looks like a no-op.** The read fails ("no
  schematic parts readable") and the page keeps showing the cached July
  design ("read 7/16/2026"), so stale data stays on screen as if current.
- **Narrow layout.** At palette width the header overlaps (title, tagline,
  JLCPCB selector).

**Gap: no search box without a design.** `/api/search` with no `lineIndex`
works as a free catalog search (verified 2026-10-19), but the page only draws
the box at the bottom of the Design Overview, and `renderMain()` returns early
when no design is loaded. With an empty schematic, Refresh fails ("no schematic
parts readable") and there is nowhere to type. The drawing-time use case starts
from exactly that state.

Gotcha found on the first run: `ui.workspaces` includes some workspaces
(`DebugEnvironment`, `ExploreEnvironment`, …) whose `toolbarPanels` raise
`No product type is associated to this workspace object yet`. The first run
crashed there before reaching any Electronics workspace; each workspace is now
probed in its own `try`.

If 2 fails, check WSL localhost forwarding (`curl http://127.0.0.1:8341` in
PowerShell). If 1 fails but 2 and 3 pass, the palette alone is enough: it can
be opened from the Design workspace and left docked.
