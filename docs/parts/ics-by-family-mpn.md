```applies-to
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

⚠️ **`components` takes NO package param.** Package is a *per-category* filter and
`components` is its own table. So you cannot ask "MAX232 in SOIC-16" in one query.
**Search the family, then sieve the package yourself** against the footprint. This
is not a limitation to work around — it is the whole job.

⚠️ **The index's `stock` is a stale snapshot and can be off by 100×.** Measured:
`LTV-352T` (C10800) read **128,222 in the index and 1,295 live**. Never quote index
stock. Every candidate that survives the package sieve goes through
`hendley detail <code>` before it is shown to anyone.

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
  less reverse standoff.

So: sieve on package, then read the *catalog's* `parameters` for the spec that
actually defines the part (CTR, address, V_R, temp grade) and say out loud what
changes if the engineer takes the substitute.

## Consolidate identical parts

Two designators with the same family and the same footprint should usually get the
**same LCSC code**. JLCPCB's feeder/loading fee is charged **per unique part type**,
so a needless second code costs money for nothing. Check the rest of the design
before recommending a fresh part for a designator whose twin is already resolved.

## The anchor

A part's identity is its schematic **VALUE** or its **`MPN`** attribute — whichever
the designer filled in. The legacy **`MP` attribute is not an anchor** (it is being
retired, and it disagreed with VALUE on a real board: `MP=MB6S` against
`VALUE=MB10S`). Ignore `MP` and `MF`.
