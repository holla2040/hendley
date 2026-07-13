# Aluminium electrolytic capacitors

```applies-to
catalogType: Aluminum Electrolytic Capacitors - SMD
catalogType: Aluminum Electrolytic Capacitors - Leaded
category: capacitors
```

## The can size IS the package string

This is the whole trick for this class. The catalog's package for an
electrolytic is `SMD,D5xL5.4mm` — it encodes the **diameter and the height**,
the two things that decide whether the part fits the footprint. Through-hole
reads `插件,D5xL11mm` (插件 = plug-in/leaded, 贴片 = SMD).

`package` is one of only two params the index actually honours, and it matches by
**exact string**. So the net is tight with nothing clever:

    capacitors?package=SMD,D5xL5.4mm&capacitance=0.00001

That is ~36 rows for a 10 µF can — no truncation, no guessing. Do **not** try to
filter the can dimensions any other way: the index has no diameter or height
column, and the catalog's `Diameter` / `Height - Seated (Max)` are text.

## What the catalog publishes for this class

`Capacitance` · `Voltage Rating` · `Diameter` · `Height - Seated (Max)` ·
`Tolerance` · `Ripple Current` · `Operating Temperature` · `Lifetime` ·
`Equivalent Series Resistance(ESR)`

These names are identical for every manufacturer. The index's `attributes` blob
is **not** — it carries the raw datasheet keys, and 583 of 680 sampled parts call
the diameter `φD` while 62 call it `Diameter`. Always write terms in the catalog's
names.

## How to constrain each one

| field | op | why |
|---|---|---|
| `capacitance_farads` | `eq` | the index term — this is what filters the query |
| `Capacitance` | `eq` (`"10uF"`) | **also state it in the catalog's words** — this is the COLUMN the engineer reads. Both terms; neither is redundant |
| `Voltage Rating` | **`gte`** (unit `V`) | an over-rated part drops straight in — this is what makes a 63 V can available for a 50 V slot |
| `Diameter` | `eq` (unit `mm`) | it is the land pattern; a wider can does not fit |
| `Height - Seated (Max)` | **`lte`** (unit `mm`) | a shorter can still fits under the enclosure |

Voltage and height **must** carry their unit, or the catalog's `"50V"` / `"5.4mm"`
cannot be compared and every part becomes an honest miss.

## Do not sieve on Tolerance

`Tolerance eq "±20%"` looks harmless and is a trap: it **rejects a ±10% part**,
which is strictly *better*. And the string cannot be compared numerically (`±20%`
is not a number in `%`), so there is no "or better" form of it. Leave it out
unless the engineer explicitly asks for a tolerance — then say so in `say`.

## Never touch these index columns

`is_polarized` is **`false` on every aluminium electrolytic in the catalog.**
`capacitor_type` is `"unknown"` for all of them. `esr_ohms` is constant `3`,
`ripple_current_amps` is always null, and `temperature_coefficient` is null (it is
an MLCC field). A term on any of these returns **zero parts while looking like it
filtered** — this is not hypothetical; `is_polarized isTrue` once rejected all 36
candidates for a perfectly good 10 µF 50 V can.

**An electrolytic is identified by `catalog.secondType`, never by a flag.**

## Read, don't filter

`Ripple Current` (`17mA@120Hz`), `Lifetime` (`2000hrs@105℃`), `ESR` and
`Operating Temperature` (`-40℃~+105℃`) are strings with an `@` or a range in
them. They are **not** numerically comparable — show them for the engineer's
judgement, never make them sieve terms.

## Picking

The shop's bias: **high stock = popular = supply-chain-safe, and worth paying a
little more for.** The can size is non-negotiable (it is the footprint). Voltage
over-rating is free margin. Everything else is a trade-off for the engineer, not
for the tool.
