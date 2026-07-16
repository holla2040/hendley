```applies-to
catalogType: Diodes - General Purpose
catalogType: Switching Diodes
catalogType: Switching Diode
```

# Ordinary diode class proof

A generic diode symbol excludes visually distinctive Zener, Schottky, and TVS
intent, but it does not distinguish every catalog spelling for ordinary and
switching diodes. When no exact model family is specified, prove candidates
against the live catalog class with `secondTypeName in` the applicable ordinary
class values above. This class proof is independent from package and electrical
rating proof.

An exact family such as `1N4148` is narrower evidence: prove the live
`componentModel` contains that family, in addition to proving the package. Do
not infer an exact manufacturer suffix or configuration from the schematic's
family name.
