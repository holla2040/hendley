```applies-to
catalogType: Schottky Diodes
catalogType: ESD And Surge Protection (TVS/ESD)
```

# Schottky and TVS diode class proof

## Class identity

Schottky and TVS intent may come from the schematic value, an explicit
attribute, or a visually distinctive symbol. A generic diode symbol does not
prove either class. When the evidence does identify one, make it executable
with the exact live catalog `secondTypeName`:

- `Schottky Diodes` for a Schottky barrier diode;
- `ESD And Surge Protection (TVS/ESD)` for a TVS or avalanche suppressor.

The parts index's `is_schottky` and `is_tvs` flags are measured false on parts
of those classes. They are never evidence and must never appear in a sieve.
Keyword or family-name matching is discovery only; the live catalog class is
the proof.

## Search boundary

Use coarse class-specific words when they are needed to bring the right family
inside the index's 100-row discovery cap. Repeat the intended class in the live
`secondTypeName` sieve. Prove a standard package such as `SOD-323` or `SOD-123`
separately.

A family label such as `BAT54` establishes Schottky intent but does not select
an exact orderable variant or configuration. Use it in coarse FTS discovery
and prove that the live catalog `componentModel` contains the family label;
package and `secondTypeName` remain separate proof terms. Likewise, `18V TVS` supplies a
nominal standoff or breakdown target and class intent, but not directionality,
pulse rating, clamp voltage, leakage, or test conditions. Keep those missing
electrical choices visible for engineering review; do not invent them from the
symbol or family name. Use the descriptive TVS words for coarse FTS discovery,
but do not claim which catalog voltage parameter they constrain. If that
ambiguity changes which part is acceptable, keep the reading below automatic
acceptance confidence until the engineer identifies the intended parameter.

## Shop convention status

No Hendley shop convention currently defines a bare TVS voltage as
`Reverse Stand-Off Voltage (Vrwm)`. Therefore `18V TVS` is class intent and a
descriptive discovery phrase, not an automatic voltage acceptance term. The
reader must omit voltage from the live sieve and set
`intent.ratingAmbiguous=true`; the server honors that structured guard
regardless of numeric confidence. An engineer may still state `Vrwm 18V`, choose an exact
family/part, or record a future convention explicitly; those are new evidence,
not an inference from the number alone.
