# Chip resistors (surface mount)

```applies-to
catalogType: Chip Resistor - Surface Mount
category: resistors
```

## One resistance term, in the index's name, as a plain number

    resistors?package=0603&resistance=10000

`package` (exact string) and `resistance` (**plain ohms**) are the only two
params the index honours for this class, and one sieve term proves the value:

    {"field": "resistance", "op": "eq", "value": 10000}

**NEVER also state it in the catalog's words** (`{"field": "Resistance",
"value": "10kΩ"}`). The index column `resistance` and the catalog parameter
`Resistance` are the SAME NAME once punctuation and case are dropped, so the
sieve resolves the term to the index's number (`10000`) and compares it against
the string `"10kΩ"` — a miss on **every part in the catalog**. `10k` is not a
number in Ω, so no unit can rescue it either.

This is the exact opposite of the electrolytic rule, and the difference is real:
`Capacitance` does *not* collide (its index column is `capacitance_farads`), so
a capacitor states both. **A resistor states one.** The single index term still
*displays* `10kΩ` in the table, because the column shows the catalog's own
string.

## What the catalog publishes for this class

`Resistance` · `Power(Watts)` · `Tolerance` · `Temperature Coefficient` ·
`Voltage-Supply(Max)` · `Operating Temperature` · `Type`

The index's `attributes` blob spells the same fields differently (`Overload
Voltage (Max)`, `Operating Temperature Range`) — the usual drift. Write terms in
the catalog's names, except where they collide with an index column (above).

## How to constrain each one

| field | op | why |
|---|---|---|
| `resistance` | `eq` | the index term — ohms, plain number. This is the whole filter |
| `package` | `eq` | exact string, no wildcards |
| `tolerance_fraction` | **`lte`** | a FRACTION, not a percent: `0.01` is ±1%. `lte 0.01` = "1% or better", so a ±0.1% part passes — as it should |

That is the whole list. Everything else this class publishes is **read, not
proved** (below).

`tolerance_fraction eq 0.01` is a trap: it rejects a ±0.5% part, which is
strictly better. Measured across a 10 kΩ 0603 result set: `0.01` ×41 (±1%),
`0.05` ×22 (±5%), `0.001` ×20 (±0.1%), `0.005` ×12 (±0.5%), tighter ×4.

## NEVER sieve on power

`power_watts` is the catalog's string **with its unit thrown away**, and it
rejects good parts two different ways:

- **The unit is not always milliwatts.** 0402 = `100`/`62.5`, 0603 = `100`,
  0805 = `125`, 1206 = `250` — but 1206 also carries `1`, and 2512 carries
  `1`, `2`, `3`. Those are **watts**. So `power_watts gte 100` rejects every
  1 W part, which is strictly *better* silicon, while passing a 250 mW one.
- **It is null on ~3% of rows** (3 of 100 on a 10 kΩ 0603 search; C5184132 is
  one). The sieve then falls back to the catalog's `"100mW"` string, cannot
  coerce it, and records an honest miss — a red cell on a part that is exactly
  100 mW.

For a chip resistor **the package sets the power rating** (0603 = 100 mW). Show
the power column; never make it a term. If the engineer explicitly asks for
headroom, say so in `say` and let them read the column.

## Read, don't filter

- **`Type`** — `Thick Film Resistor` / `Thin Film Resistor` / `Current Sensing
  Resistors`. The catalog is the only thing that knows which. Thin film is the
  same value at 100–300× the price (C5184132, ±0.01%: **$0.8086** against
  C25804, ±1%: **$0.0026**), and a 2512 search returns current-sense shunts
  (0.5 mΩ) mixed in with thick films. Show it; the engineer judges.
- **`Temperature Coefficient`** (`±100ppm/℃`), **`Operating Temperature`**
  (`-55℃~+155℃`), **`Voltage-Supply(Max)`** (`75V`) — strings with a `±` or a
  range in them; not numerically comparable.
- **`max_overload_voltage`** proves nothing: near-constant per package (0402:
  only `50`; 0805: only `150`) and just 58/100 filled on 2512, so a term on it
  rejects nulls and buys nothing.

## Never touch these index columns

`is_surface_mount` and `in_stock` are `True` on every row.
`is_multi_resistor_chip` and `is_potentiometer` are `False` on every row.
`description` is the empty string on every row. `number_of_pins` and
`number_of_resistors` are **null on every resistor row** (they belong to
`resistor_arrays`). A term on any of them proves nothing, and the null ones
reject the entire result set while looking like they filtered.

## Picking

Stock is the bias: **high stock = popular = supply-chain-safe, and worth paying
a little more for.** Two cautions specific to this class:

- Sorting by tolerance ascending floats the precision thin-films to the top.
  They are 100–300× the price for the same value — $404 against $1.30 for 500
  pieces. Tolerance is a *ceiling*, not a target.
- The index's stock is an LCSC snapshot, not JLC assembly stock. C25804 shows
  37 M in the index and **0** live. Only the live-verified number decides.
