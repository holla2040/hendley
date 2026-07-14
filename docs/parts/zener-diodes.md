```applies-to
catalogType: Zener Diodes
designator: D
```

# Zener diodes and this shop's voltage labels

## Local schematic values

In this shop's Fusion libraries, a diode value may state the Zener voltage
without naming an orderable part. These observed spellings all mean a **10 V
Zener diode** when they occur on a diode designator and diode footprint:

- `VZ10`
- `10V0`
- `10.0`

These are **shop conventions, not manufacturer part numbers and not universal
syntax**. Interpret them as a proposed specification—`kind: diode`, `value:
10V`, Zener qualifier, and the normalized package from the footprint—then let
the engineer confirm that reading once. Cache the confirmed interpretation.
Never search the literal alias as though it were a family name.

Do not generalize from the punctuation alone. A number on a non-diode
designator, or a diode footprint that does not support the proposed package,
is not proof of a Zener requirement.

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
