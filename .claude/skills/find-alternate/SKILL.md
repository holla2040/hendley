---
name: find-alternate
description: Find, verify and recommend a replacement JLCPCB part for one design part — out of stock, a different package, or a different value. Use when the user says "find a replacement/alternate for <part>", "R8 is out of stock", "same part in 0402", or similar. Drives hendley detail + hendley alternates --json, filters on verified parameters, recommends one part. Never applies the change to the design.
---

# find-alternate — change one part, by recommendation

Moved from the root `CLAUDE.md` on 2026-11-22. Steps 1-4 below; step 5 is the root's "Changing a part" rule, repeated at the end.

Many conversations are a one-shot lookup — *"is C25768 in stock?"* → `hendley
detail`; *"check this BOM before I order"* → `hendley stock`. The main multi-step
job is **changing a part**, and there is **one** workflow for it; the only thing
that varies is *why* the part changes — it's **out of stock**, or you want a
**different package**, or a **different value**. (If the part lives in a Fusion
design, first read the live design over the bridge — see the root `CLAUDE.md` "Fusion access from WSL" — to get its designator and the exact package variant names.) Drive it as:

1. **Anchor on the target.** `hendley detail <code>` → read its category, exact
   `componentSpecification` (the package string), and key specs. The exact
   package string is what you pass as `--package` (see matching rules below).
   `detail` **already prints JSON** — there is **no `--json` flag**; don't pass one
   (it errors). Only `stock` and `alternates` take `--json` (see the root `CLAUDE.md` "CLI output").
2. **Translate the spoken constraint into flags** — *you* own the hard filter; it
   is NOT hardcoded. "same package" → `--package "<exact spec>"`; a category →
   `--category <slug>` (`hendley alternates --list-categories`); other constraints
   → `-p key=value`. Then run `hendley alternates <code> --category … [--package …]
   [-p …] --json`. The tool discovers candidates from jlcsearch and **verifies
   every one live** (stock/price/parameters) — it does the gather, not the pick.
3. **Apply any value/numeric hard filter yourself, over the verified `--json`.**
   Most categories have **no** jlcsearch query param for the spec you care about
   (e.g. `resistor_arrays` has no resistance param), and the `_min`/`_max` params
   are unreliable — so don't try to push it into the query. Instead filter the
   `candidates[]` on each part's verified `parameters[]` (the authoritative live
   specs). The recipe (here, keep only 330 Ω parts) — use it, don't re-invent it:

   ```bash
   hendley alternates C29719 --category resistor_arrays --package "0603x4" --json \
   | python3 -c 'import json,sys
   d=json.load(sys.stdin)
   def spec(c,name):
       return next((p["parameterValue"] for p in (c["parameters"] or [])
                    if p["parameterName"]==name), None)
   for c in d["candidates"]:
       if c["verified"] and (spec(c,"Resistance") or "").startswith("330"):
           print(c["code"], c["liveStock"], c["unitPrice1"], spec(c,"Resistance"))'
   ```
4. **Trade off and recommend (this is your job, not the tool's).** Weigh the
   *verified* data. User's bias: **high inventory = popular = supply-chain-safe,
   and they'll pay a bit more for it** — the opposite of "cheapest". **Same
   package is the top priority** (changing it changes the PCB layout); a different
   package can still win if the inventory/price payoff justifies a re-layout.
   Always **surface electrical caveats** — e.g. downsizing 0603→0402 drops the
   power/voltage rating, so check the part's actual dissipation first. Recommend
   one with reasoning the user can override.

**jlcsearch matching rules (so your flags actually match):**
- `package` and other per-category **string** filters are **exact, case-
  sensitive, no wildcards** (`DFN-8` ≠ `DFN-8(3x3)`; `%`/`*`/substrings → 0 rows).
  Use the target's exact `componentSpecification`.
- Numeric `_min`/`_max` params are **unreliable** (sparse columns silently drop
  null rows). Apply numeric/spec filters yourself over the verified
  `parameters[]`, not via jlcsearch query params.
- Fuzzy / cross-package discovery: `--category components -p search="<tokens>"`
  (FTS, token + prefix; in-stock parts only).

**Do NOT** filter or rank on Basic vs. Extended — it's a fee attribute, not a
selection criterion (display it, don't select on it). That fee is the JLCPCB PCBA
**feeder/loading charge**, per *unique* part type and one-time per order (NOT per
unit): **Economic** tier ≈ **$3** per Extended part (Basic free); **Standard**
tier ≈ **$1.50** per part type for *both* Basic and Extended — so "Basic is
cheaper" really only holds on Economic, and the impact scales with BOM diversity
and amortizes over board count. The *unit-price* gap between a Basic and Extended
equivalent is negligible (often Extended is even cheaper per unit). The fee is
**not** returned by the component API (it's order-level) — which is exactly why
you surface Basic/Extended for the user's judgment rather than select on it.
(Source: jlcpcb.com/help/article/pcb-assembly-price — a policy figure that
changes; verify if it matters.) **Do NOT** download the whole catalog "for one
part" — jlcsearch is the discovery surface.

## 5. Hand the recommendation to the designer. STOP THERE.

**Changing a part** (out of stock / different package / different value) has one workflow: the **`find-alternate` skill** (`.claude/skills/find-alternate/SKILL.md`). ⛔ It ends at a recommendation — **you do not apply the change** (standing rule, 2026-07-13). Give the user the designator, the chosen `Cxxxx`, the MPN, the manufacturer, the exact package, and the caveats; **they** edit Fusion; then re-read the design over the bridge to confirm. **Do NOT** run `hendley scr`, write a swap JSON, generate a `.scr`, or fire `Electron.run` / `fusion_mcp_execute` at the design. Do not offer to. If the user asks for a `.scr`, tell them that path is retired and confirm before doing anything.
