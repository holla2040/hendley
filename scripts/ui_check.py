#!/usr/bin/env python3
"""Drive the real page in a real browser. The only thing that catches UI bugs.

`pytest` tests the JSON API. It cannot tell you that the page never CALLS the
API, which is exactly what happened: the family engine was finished, tested and
completely unreachable, and no test in the suite noticed. Two more bugs only
showed up here — an infinite retry loop against a live API, and the agent
slandering a good part in a warning nobody could have seen without looking.

    ~/.venvs/pw/bin/python scripts/ui_check.py            # fake backend (fast)
    ~/.venvs/pw/bin/python scripts/ui_check.py --live     # real catalog + agent

Setup (once):
    python3 -m venv ~/.venvs/pw && ~/.venvs/pw/bin/pip install playwright requests
    sudo ~/.venvs/pw/bin/playwright install-deps chromium
    ~/.venvs/pw/bin/playwright install chromium

--live needs NO FUSION: it replays the design from ~/.hendley/design-cache.json,
which the app writes on every Refresh. Fusion's BOARD; switch is one-way, so you
usually get ONE read per session — spend it, then work from the cache for ever.

Screenshots land in /tmp/hendley-ui/. Look at them. A page that renders wrong
raises no exception.
"""
from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import threading
from http.server import ThreadingHTTPServer

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from hendley.app.server import HendleyApp, make_handler  # noqa: E402
from hendley.datasources.base import PartFact  # noqa: E402

OUT = pathlib.Path("/tmp/hendley-ui")

# A family part, and the catalog's real rows for it. The wide body and the DIP
# answer to the name "ULN2003" and neither can go on a 150-mil land.
ULN = [{"code": "C7512", "package": "SOIC-16"},
       {"code": "C94832", "package": "SOIC-16"},
       {"code": "C2859910", "package": "SO-16-208mil"},
       {"code": "C93000", "package": "DIP-16"}]


class FakeSource:
    name = "fake"

    def discover(self, query):
        pkg = (query.get("params") or {}).get("package")
        return [r for r in ULN if not pkg or r["package"] == pkg]

    def verify(self, refs):
        pk = {r["code"]: r["package"] for r in ULN}
        return {r: PartFact(
            ref=r, found=True, stock=400_000, mpn="ULN2003ADR", manufacturer="TI",
            price_tiers=[{"startQuantity": 1, "unitPrice": 0.12}],
            raw={"componentCode": r, "componentModel": "ULN2003ADR",
                 "componentSpecification": pk[r], "stockCount": 400_000,
                 "libraryType": "base",
                 "priceRanges": [{"startQuantity": 1, "unitPrice": 0.12}],
                 "parameters": []},
            provenance="fake") for r in refs}


class FakeAgent:
    name = "fake-agent"

    def interpret_part(self, ctx):
        from hendley.ai.interpreter import Interpretation
        return Interpretation()

    def read_part(self, dossier):
        return None

    def interpret_footprint(self, footprint, headline=""):
        return {"package": "SOIC-16", "envelope": {}, "confidence": 0.95,
                "rationale": "150 mil ⇒ the 3.9mm body"}

    def read_family(self, family, footprint="", headline="", packages=()):
        return {"packages": ["SOIC-16"], "partNumbers": ["ULN2003ADR"],
                "class": "darlington transistor array",
                "traps": [{"part": "ULN2004A",
                           "why": "pin-identical on the same land, but a 10.5k "
                                  "series resistor on every input"}],
                "rationale": "D = the 3.9mm SOIC", "confidence": 0.9}

    def derive_key(self, ctx):
        return {"spec": {"kind": "darlington array", "value": "",
                         "package": "SOIC-16", "qualifier": ""},
                "rationale": "", "confidence": 0.9}


class FakeBridge:
    """One family part: U1, VALUE=ULN2003, footprint SO16 @150 mil."""

    def read_all(self, entity, obj=None, page=1000):
        if entity == "electronics.Schematic":
            return [{"object_id": 1, "name": r"C:\T\demo sch.sch"}]
        if entity == "electronics.Part":
            return [{"object_id": 10, "name": "U1", "value": "ULN2003",
                     "device_object_id": 100}]
        if entity == "electronics.Device":
            return [{"object_id": 100, "package_object_id": 50}]
        if entity == "electronics.Package":
            return [{"object_id": 50, "name": "SO16",
                     "headline": "Small Outline package 150 mil"}]
        if entity == "electronics.Attribute":
            return []
        if entity == "electronics.Element":
            return [{"object_id": 30, "name": "U1", "x": 1, "y": 2, "angle": 0,
                     "mirror": 0, "populate": 1, "package_object_id": 50}]
        raise AssertionError(entity)

    def read(self, entity, obj=None):
        return {"items": self.read_all(entity, obj)}

    def run_eagle(self, command):
        return {}


def serve(live: bool):
    if live:
        return HendleyApp()          # real catalog, real agent, real caches
    tmp = pathlib.Path(tempfile.mkdtemp())
    return HendleyApp(db_path=tmp / "p.db", outdir=tmp, draft_path=tmp / "d.json",
                      cache_path=tmp / "c.json",
                      datasource_factory=FakeSource,
                      bridge_factory=lambda host: FakeBridge(),
                      interpreter_factory=FakeAgent)


def main() -> int:
    from playwright.sync_api import sync_playwright

    live = "--live" in sys.argv
    OUT.mkdir(parents=True, exist_ok=True)
    app = serve(live)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    # --live replays the cached design; the fake reads its own bridge on Refresh
    lines = []
    if live:
        cache = json.loads(
            (pathlib.Path.home() / ".hendley/design-cache.json").read_text())
        lines = [(" ".join(ln["designators"]), i)
                 for i, ln in enumerate(cache["requirements"]["lines"])
                 if ln.get("family")]
        if not lines:
            print("no family lines in the design cache — Refresh the app against "
                  "Fusion once (schematic fronted) to write it")
            return 1

    errors: list[str] = []
    bad = 0
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1500, "height": 1050})
        page.on("pageerror", lambda e: errors.append(f"PAGEERROR: {e}"))
        page.goto(f"http://127.0.0.1:{srv.server_port}/")

        if live:
            page.wait_for_selector("button.comp", timeout=30_000)   # from cache
        else:
            page.click("#refresh-btn")
            page.wait_for_selector("button.comp", timeout=60_000)
            lines = [("U1", 0)]
        page.wait_for_timeout(1200)

        # The component rail is draggable, remembers its width, and never gains
        # a horizontal scrollbar even when narrowed.
        handle = page.locator("#rail-resizer")
        box = handle.bounding_box()
        if box:
            page.mouse.move(box["x"] + box["width"] / 2, box["y"] + 30)
            page.mouse.down()
            page.mouse.move(245, box["y"] + 30)
            page.mouse.up()
            rail_width = page.locator(".rail").evaluate("e => e.getBoundingClientRect().width")
            no_x_scroll = page.locator("#comps").evaluate(
                "e => e.scrollWidth <= e.clientWidth")
            if not (235 <= rail_width <= 255 and no_x_scroll):
                bad += 1
                print(f"rail resize FAILED: width={rail_width}, no-x-scroll={no_x_scroll}")

        for name, i in lines:
            page.click(f'button.comp[data-line="{i}"]')
            try:
                # a family part SEARCHES ITSELF on open — nothing is typed
                page.wait_for_selector(".sect.family", timeout=240_000)
                page.wait_for_timeout(1000)
                shot = OUT / f"{name.split()[0]}.png"
                page.screenshot(path=str(shot), full_page=True)
                say = page.inner_text(".say").replace("\n", " ")
                traps = page.query_selector_all(".traps li")
                print(f"{name:<9} {say[:78]}")
                print(f"{'':<9} {len(traps)} trap(s) shown  ->  {shot}")
            except Exception as exc:
                bad += 1
                page.screenshot(path=str(OUT / f"{name.split()[0]}-FAIL.png"),
                                full_page=True)
                print(f"{name:<9} NO FAMILY BLOCK — {str(exc).splitlines()[0][:70]}")

        if not live:      # the pick must flip the rail green
            page.click("input[type=radio] >> nth=0")
            page.wait_for_timeout(2000)
            rail = page.inner_text('button.comp[data-line="0"]')
            ok = "✓" in rail
            bad += 0 if ok else 1
            print(f"\npick -> rail {'GREEN ✓' if ok else 'NOT resolved: ' + rail!r}")

        browser.close()
    srv.shutdown()

    print("\nJS errors:", "\n".join(errors) if errors else "none")
    return 1 if (errors or bad) else 0


if __name__ == "__main__":
    raise SystemExit(main())
