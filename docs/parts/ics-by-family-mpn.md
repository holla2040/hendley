```applies-to
judgment: family
catalogType: Darlington Transistor Arrays
catalogType: I/O Expanders
catalogType: RS-485 / RS-422 ICs
catalogType: Bridge Rectifiers
catalogType: Transistor, Photovoltaic Output Optoisolators
category: components
```

# ICs named by a family, not by a part number

This note is about the commonest thing a designer actually does: place a library
part and label it **`MAX232`**, **`ULN2003`**, **`SP3485`**. That is a *family*,
not something you can order. A MAX232 exists as SOIC-16, SSOP-16, TSSOP-16 and
DIP-16; the thing that decides which one you may buy is **the footprint already
on the board**. Everything below is how to close that gap, measured 2026-07-13.

## The index cannot do this for you

There is **no MPN or keyword param on any IC category** (`io_expanders`, `ldos`,
…). Those slugs take an exact `package` string and nothing else useful. The
official JLC API cannot search at all — it only verifies codes you already hold.

So there is exactly **one** discovery surface for a family name:

    GET https://jlcsearch.tscircuit.com/components/list.json?search=ULN2003

FTS over part **names**, prefix-matching, in-stock rows only. Rows carry `lcsc`,
`mfr` (which is the full **MPN**, not the maker), `package`, `stock`.

**`components` DOES honour `package`** (measured 2026-07-13 — an earlier draft of this
note said the opposite, and it was wrong):

    ?search=SP3485                 → 19 rows
    ?search=SP3485&package=SOIC-8  → exactly the 2 SOIC-8 parts
    ?search=SP3485&package=BOGUS-9 → 0 rows

So the whole query is **family + package**, and it is tight: `ULN2003`+`SOIC-16` → 11
rows · `PCF8574`+`SOIC-16-300mil` → 5 · `MB10S`+`MBS` → 40 · `SP3485`+`SOIC-8` → 2 ·
`LTV-352T`+`SOP-4-2.54mm` → 1.

`is_basic` is honoured too. ⚠️ **`stock_min` is SILENTLY IGNORED** — `stock_min=999999999`
still returns all 19 rows. Never filter stock at the index; verify it live.

The package is still **re-asserted as a sieve term**, because a param the index quietly
drops is exactly how a TSSOP part reaches a 150-mil land with nothing on screen saying so.

⚠️ **The index's `stock` is a stale snapshot and can be off by 100×.** Measured:
`LTV-352T` (C10800) read **128,222 in the index and 1,295 live**. Never quote index
stock. Every candidate that survives the package sieve goes through
`hendley detail <code>` before it is shown to anyone.

## ⚠️ The CLASS is a label. It is not a query, and it is not a sieve term.

Tempting, and wrong twice over.

**Not a query.** `?search=optocoupler` returns 100 rows — the cap — topped by *LEDs*
(`KT-0603R`, `KT-0805Y`), spanning LEDs, IR LEDs and three optocoupler subcategories.
`?search=LTV-352T` returns exactly **1**. FTS ANDs tokens against part NAMES, so a class
word matches everything and nothing. There is also no `optocouplers` and no
`bridge_rectifiers` slug among the 44 categories: even knowing the class, there is no
parametric table to point at.

**Not a sieve term either — the INDEX's `subcategory` column disagrees with the catalog
on the very parts in front of you:**

| code | CATALOG `secondTypeName` | INDEX `subcategory` |
|---|---|---|
| C8963 | `RS-485 / RS-422 ICs` | `RS-485/RS-422 ICs` |
| C2692302 | `RS-485 / RS-422 ICs` | **`Buffers / Drivers`** ← same family |
| C108824 | `Bridge Rectifiers` | `Bridge Rectifiers` |
| C2886577 | `Bridge Rectifiers` | **`Diodes - General Purpose`** ← same part |

C2886577 is an MB10S **mounted on a real board here**. A plan sieving on `subcategory`
would have rejected the part already on the board — the `is_schottky` / `is_polarized`
failure mode: **zero results while looking like it filtered.**

Note which side is wrong: **the CATALOG is consistent across both pairs. The INDEX is
not.** `components.category` and `components.subcategory` now live in
`UNPROVABLE_COLUMNS` and are not offered to the agent.

So: read the class off the **catalog** once a part is in hand, use it to pick the right
note and to describe the part on screen — and let it find nothing and reject nothing.

## ⚠️ Never GUESS the package. Read it off the catalog's own list.

The trap that cost the most, because the guess looks completely reasonable:

| the library's footprint | what you'd naturally judge | what the CATALOG actually calls it |
|---|---|---|
| `SOIC-4` (a bridge rectifier) | `SOIC-4` | **`MBS`** |
| `SOP04` (a 4-pin optocoupler) | `SOP-4` | **`SOP-4-2.54mm`** |

`?search=MB10S&package=SOIC-4` → **0 rows**. `?search=LTV-352T&package=SOP-4` → **0 rows**.
Not because JLC lacks the part — it has 40 of one and 1 of the other — but because that is
not the word the catalog uses. **A wrong package returns zero while looking exactly like a
family JLC does not stock**, which is the worst possible failure: it is indistinguishable
from a true answer.

So the package is never invented. Ask the catalog for the family with **no package at
all**, read off the packages it actually stocks it in, and choose from *that* list:

    ?search=MB10S     → MBS (40 parts) · SMD-4P (2) · SOP-4 (2) · IBS (1)
    ?search=LTV-352T  → SOP-4-2.54mm (1)

The footprint's geometry then decides *which* of them when there is a choice (150-mil
`SOIC-16` vs 300-mil `SOIC-16-300mil`). The library's name proposes; the catalog's list
disposes.

### …and take ALL the catalog's words for that one land, not one of them

The catalog spells a single land several ways, and **the different spellings hold
different parts**:

    ?search=SP3485&package=SOIC-8  → 2 parts.  Best: C8963, 327k in stock, BASIC
    ?search=SP3485&package=SOP-8   → 10 parts. Best: C668205, 145k, extended

Both are the 3.9 mm 8-pin body. Same land. A search forced to pick one string throws
away half the field — and here it would have thrown away the **Basic part with 7× the
stock**, while looking like a complete answer.

So the land is a **set** of catalog words, and the sieve carries it as one term:

    {"field": "package", "op": "in", "value": ["SOIC-8", "SOP-8"]}

The index takes only one `package` per request, so a set means **one request per
spelling**, unioned into one table. Do NOT instead widen the net to the bare family:

    ?search=1N4148   → 100 rows   ⚠️ CAPPED
    ?search=LM358    → 100 rows   ⚠️ CAPPED
    ?search=AMS1117  → 100 rows   ⚠️ CAPPED   (and `limit=500` changes nothing)

**The listing cap is a hard 100 and cannot be raised.** A bare-family net would quietly
truncate a popular part; a package-filtered one is far under it (`SP3485`+`SOIC-8` → 2,
`ULN2003`+`SOIC-16` → 11). Every request still carries the whole set as its sieve term, so
a part is proven against the **land**, not against the one spelling that happened to fetch
it. The rejects read plainly: *`is 'MSOP-8', not SOIC-8 or SOP-8`*.

⚠️ A different BODY is a different land, not another spelling: 150-mil `SOIC-16` and
300-mil `SOIC-16-300mil` are **not** interchangeable, and neither is a TSSOP, a DIP or a
QFN. The geometry is what tells them apart.

## Read the footprint's geometry, not its name

Library footprint names are a local convention and lie by omission — `SO16`,
`IC-SO8`, `SOP04` tell you nothing about body width, and body width is precisely
what separates the parts you may order from the ones you may not.

**`electronics.Package` carries a `headline`, and the headline carries the
geometry.** Join `electronics.Device` on `device_object_id` → `package_object_id`,
schematic-side, no `BOARD;` switch needed. Measured on a real design:

| footprint name | its headline | what that means |
|---|---|---|
| `SO16` | "Small Outline package **150 mil**" | 3.9 mm body → narrow SOIC-16 |
| `SOIC127P1032X265-16N` | "1.27 mm pitch, **10.32 mm span, 10.30 X 7.50**" | 7.5 mm body → **300 mil wide** |
| `IC-SO8` | "**D** (R-PDSO-G8)" | TI's `D` suffix → narrow SOIC-8 |

A footprint whose headline is blank gives you nothing; fall back to the package
bounding box (`x2-x1`, `y2-y1`) or ask the engineer. Do not guess from the name.

## Web-search the family for its suffix decoder

This is the step that makes the whole thing work, and it cannot be done from the
catalog. **The datasheet's ordering table maps suffix → body**, which converts a
footprint into an expected MPN shape. Measured examples:

- **ULN2003** — `D` = SOIC 3.9 mm body · `NS` = SOP 5.3 mm · `PW` = TSSOP ·
  `N` = PDIP · trailing `R` = tape-and-reel. So a 150 mil `SO16` wants a
  **`ULN2003ADR`**, never a `ULN2003ANSR` (which is the 208 mil wide part).
- **PCF8574** — `T` = SO16, and NXP's "SO16" here is the **7.5 mm wide body**
  (SOT162-1), i.e. the catalog's `SOIC-16-300mil`. `TS` = SSOP20, `P` = DIP16.
- **SP3485** — `EN-L` = industrial (−40…+85 °C) · `CN-L` = commercial (0…+70 °C).
  Same narrow SOIC-8 body: here the suffix is a **temperature grade**, not a package.

## ⚠️ A trap is about FUNCTION. Never about the package.

The agent that names the traps **can slander a good part**, and it did (2026-07-13). On a
PCF8574 in a 300-mil land it warned:

> *"PCF8574T — a NARROW 3.9 mm body (150 mil). It will not reach the 7.5 mm-body land on
> this board. Wrong land, not wrong part."*

That is **false**. C7605 *is* a `PCF8574T`, and the catalog lists its package as
`SOIC-16-300mil` — the wide body, which is exactly what the board has. (NXP's "SO16" for
the `T` suffix is the 7.5 mm SOT162-1. The datasheet says so.)

Nothing broke, because the **catalog** proves the package and the sieve was unmoved: the
good part stayed on the table. But the engineer would have read the warning and skipped
the genuine NXP part — the one they should have bought.

**So a trap may only speak about what the package CANNOT show**: the I²C address, the
voltage, the gain, the CTR, the temperature grade, the register model. The catalog proves
the land, exactly, for every part, and it **outranks the agent**. A trap that talks about
bodies, pin counts or lands is not protecting anyone; it is condemning a good part with a
guess. (Enforced in `FAMILY_PROMPT`; if you rewrite that prompt, keep this rule.)

## The traps that are not packages

The package sieve is necessary and **not sufficient**. Three real ones, measured:

- **`PCF8574` vs `PCF8574A` is a different I²C base address** (0x20 vs 0x38), in
  an identical SOIC-16-300mil body. It will solder down perfectly and the firmware
  will not find it. **Never** let an `A` part into a `PCF8574` result on the
  grounds that the package matches.
- **`LTV-352T` is a 1000–5000 % CTR optocoupler.** Its same-package, same-pinout
  neighbours `LTV-357T` (50–600 %) and `EL357N` (200–400 %) are **not drop-ins** —
  the current transfer ratio is 3–5× lower and the LED drive must be rechecked.
- **`MB10S` (1000 V) vs `MB6S` (600 V)** share the `MBS` package. Same land, 40 %
  less reverse standoff. (`MB8S` is 800 V — the same trap, one step milder.)
- **`SP3485` (3.3 V) vs `SP485` / `MAX485` / `SN75176` (5 V)** — the identical SOIC-8
  land AND the identical 75176 pinout. It is a *supply voltage* difference, and nothing
  about the footprint or the package will ever hint at it.
- **`PCA9554` vs `PCF8574` — the subtlest one on this board.** Pin-to-pin compatible,
  and it shares the 0x20–0x27 address range, so it solders down and it even **ACKs**.
  But it is **register-based**: every access needs a command byte selecting
  input/output/polarity/configuration, and its ports **power up as INPUTS**. PCF8574
  firmware — a bare byte write — will not drive it at all. It answers, and does nothing.
- **Temperature grade**: `SP3485EN` is −40…+85 °C, `SP3485CN` is 0…+70 °C. Same body,
  same part number stem, one letter.

So: sieve on package, then read the *catalog's* `parameters` for the spec that
actually defines the part (CTR, address, V_R, temp grade) and say out loud what
changes if the engineer takes the substitute.

**Traps are shown, never silently substituted, and never auto-excluded.** A trap part
stays an orderable row with the warning above it, and that is deliberate: the agent's
part-name claims can be WRONG (see the `PCF8574T` slander above), so auto-excluding on
one would silently kill a good part. Warn loudly; let the engineer decide.

## Consolidate identical parts

Two designators with the same family and the same footprint should usually get the
**same LCSC code**. JLCPCB's feeder/loading fee is charged **per unique part type**,
so a needless second code costs money for nothing. Check the rest of the design
before recommending a fresh part for a designator whose twin is already resolved.

## ⚠️ A library VALUE is not always a family

`D1` on this board has VALUE `VZ10` and footprint `D-SOD323`. `VZ10` looks exactly like a
family — but it is **this shop's name for a 10 V zener**, not a part number anyone sells.
Searched by name it matches nothing sensible: the catalog's package list for "VZ10" comes
back as **electrolytic can sizes** (`SMD,D6.3xL7.7mm`), because those are the parts whose
NAMES happen to contain it.

The pipeline refuses honestly — *"can't tell which package `D-SOD323` is"* — and names the
packages the catalog does stock, so nothing wrong is ever offered. But it does not resolve.

**That part needs the SPEC path, not the family path**: `kind=zener, value=10V,
package=SOD-323`, sieved against the `diodes` category's real columns. The judgment
"`VZ10` means a 10 V zener" is a **shop convention** — it belongs where the other
conventions live (read by the agent, confirmed once by the engineer, cached in
`interpretations` for ever). **Do not hardcode `VZ10`.** The next library will have its
own private words.

The lesson generalizes: **a family is a part number the WORLD knows. A value is a name
only this shop knows.** They are indistinguishable by looking, and only the catalog can
tell you which one you are holding.

## The anchor

A part's identity is its schematic **VALUE** or its **`MPN`** attribute — whichever
the designer filled in. The legacy **`MP` attribute is not an anchor** (it is being
retired, and it disagreed with VALUE on a real board: `MP=MB6S` against
`VALUE=MB10S`). Ignore `MP` and `MF`.
