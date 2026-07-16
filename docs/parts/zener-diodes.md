```applies-to
catalogType: Zener Diodes
designator: D
```

# Zener diodes and this shop's voltage labels

## Local schematic values

In this shop's Fusion libraries, a diode value or attribute may state the
Zener voltage without naming an orderable part. On a `D` designator, the shop's
explicit cue is the letter **Z** anywhere in the VALUE or in a meaningful
attribute VALUE (case-insensitive):

- `VZ10`
- `10Z0`
- `Zener 10V`
- an attribute such as `TYPE=Zener`

These are **shop conventions, not manufacturer part numbers and not universal
syntax**. Interpret them as a proposed specification—`kind: diode`, `value:
10V`, Zener qualifier, and the normalized package from the footprint—then let
the engineer confirm that reading once. Cache the confirmed interpretation.
Never search the literal alias as though it were a family name.

The live catalog publishes that requirement as `Zener Voltage(Nom)`. Prove the
normalized voltage with an exact live sieve term on that field; name matching
is discovery, not voltage proof. For example, `VZ10`, `10Z0`, `Zener 10V`, or
`TYPE=Zener` plus a 10 V value requires `Zener Voltage(Nom) = 10V`. Do not
return a 13 V device merely because its model name happened to contain the
discovery text.

`10V0`, `10.0`, `500V`, and `1000V` contain no Z and therefore do **not** prove
Zener intent. An ordinary diode can state its reverse-voltage rating the same
way. Keep its diode class unresolved unless some other explicit specification
names it. Scan attribute values, never attribute names (`SIZE` contains a Z but
is not evidence), and ignore administrative/provider metadata such as DNP,
LCSC, MANUFACTURER, MP, and MF.

For a generic rectifier/ordinary-diode symbol, a bare voltage value is this
shop's minimum DC reverse-voltage requirement. The live catalog field is
`Voltage - DC Reverse(Vr)`; prove it with `gte` and unit `V`. This establishes
the rating, not a subtype: the symbol and live catalog class must still support
ordinary diode intent independently.

Use a coarse full-text discovery phrase containing the voltage and `diode`
along with the exact standard package. A package-only parametric request is
capped at 100 popular rows before live voltage proof and can hide the uncommon
high-voltage device that actually satisfies the requirement.

## Catalog identity

The live catalog's `secondTypeName` **`Zener Diodes`** is the authoritative
class once a concrete candidate is in hand. A designator letter, an index
subcategory, or a package cannot prove that a diode is Zener rather than
small-signal, Schottky, TVS/avalanche, or another diode class.

The parts index's advertised diode flags are not class evidence. In particular,
the project has measured that `is_schottky` is false even on Schottky parts.
Use the catalog class to label and review candidates; do not add a class term
that silently rejects parts from the index.

## Search and approval boundary

The voltage and package are requirements. The exact device remains an
engineering choice: power rating, tolerance, test current, leakage, dynamic
impedance, temperature behavior, and surge capability are not established by
the local value alone. Do not silently approve a candidate merely because its
nominal Zener voltage and land match.
