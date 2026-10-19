# SPIKE — throwaway. Answers three questions (fusion-addin/README.md):
#   1. Can an add-in put a button in the ELECTRONICS workspace?
#   2. Can a palette load the Hendley app over http://127.0.0.1:8341?
#   3. Does the palette stay usable while a schematic is the active document?
# Everything it learns goes to hendley-addin.log beside this file.

import os
import traceback

import adsk.core

APP_URL = "http://127.0.0.1:8341/"
CMD_ID = "hendleyPaletteCmd"
PALETTE_ID = "hendleyPalette"
LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hendley-addin.log")

_handlers = []
_buttons = []


def log(msg):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


def show_palette(ui):
    palette = ui.palettes.itemById(PALETTE_ID)
    if palette is None:
        palette = ui.palettes.add(PALETTE_ID, "Hendley", APP_URL, True, True, True, 480, 760)
        palette.dockingState = adsk.core.PaletteDockingStates.PaletteDockStateRight
        log(f"palette created -> {APP_URL}")
    palette.isVisible = True


class _Created(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        try:
            on_exec = _Execute()
            args.command.execute.add(on_exec)
            _handlers.append(on_exec)
        except Exception:
            log(traceback.format_exc())


class _Execute(adsk.core.CommandEventHandler):
    def notify(self, args):
        try:
            app = adsk.core.Application.get()
            ws = app.userInterface.activeWorkspace
            log(f"button clicked in workspace {ws.id if ws else None}")
            show_palette(app.userInterface)
        except Exception:
            log(traceback.format_exc())


def run(context):
    app = adsk.core.Application.get()
    ui = app.userInterface
    try:
        log("=== run ===")
        log(f"active workspace: {ui.activeWorkspace.id if ui.activeWorkspace else None}")
        log(f"active product: {app.activeProduct.productType if app.activeProduct else None}")

        cmd = ui.commandDefinitions.itemById(CMD_ID) or ui.commandDefinitions.addButtonDefinition(
            CMD_ID, "Hendley", "Open the Hendley part search palette", "")
        created = _Created()
        cmd.commandCreated.add(created)
        _handlers.append(created)

        # Question 1: try to put the button in the first toolbar panel of every
        # workspace. ui.workspaces includes some with no product type yet, whose
        # toolbarPanels raise; Fusion says to fetch them by product type instead,
        # so the Electronics product is asked for explicitly. The log says which
        # ones took the button.
        workspaces = [ui.workspaces.item(i) for i in range(ui.workspaces.count)]
        try:
            ecad = ui.workspacesByProductType("EcadDesignProductType")
            workspaces += [ecad.item(i) for i in range(ecad.count)]
        except Exception as exc:
            log(f"workspacesByProductType(EcadDesignProductType) FAILED: {exc}")
        for ws in workspaces:
            try:
                panels = [ws.toolbarPanels.item(j).id for j in range(ws.toolbarPanels.count)]
            except Exception as exc:
                log(f"workspace {ws.id}: no toolbarPanels ({exc})")
                continue
            log(f"workspace {ws.id} product={ws.productType} panels={panels}")
            if not panels:
                continue
            panel = ws.toolbarPanels.item(0)
            try:
                ctrl = panel.controls.itemById(CMD_ID) or panel.controls.addCommand(cmd)
                _buttons.append(ctrl)
                log(f"  button added to {ws.id}/{panel.id}")
            except Exception as exc:
                log(f"  button FAILED in {ws.id}/{panel.id}: {exc}")

        # Questions 2 and 3: open the palette now, so it exists even if no
        # Electronics toolbar accepted the button.
        show_palette(ui)
    except Exception:
        log(traceback.format_exc())
        ui.messageBox("Hendley spike failed; see hendley-addin.log")


def stop(context):
    ui = adsk.core.Application.get().userInterface
    try:
        for ctrl in _buttons:
            if ctrl.isValid:
                ctrl.deleteMe()
        cmd = ui.commandDefinitions.itemById(CMD_ID)
        if cmd:
            cmd.deleteMe()
        palette = ui.palettes.itemById(PALETTE_ID)
        if palette:
            palette.deleteMe()
        log("=== stop ===")
    except Exception:
        log(traceback.format_exc())
