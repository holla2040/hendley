```applies-to
catalogType: MOSFETs
catalogType: Bipolar (BJT)
catalogType: JFETs
designator: Q
```

# Discrete transistor class and polarity proof

## Class comes from the live catalog

A `Q` designator does not distinguish a MOSFET, BJT, JFET, or IGBT. The
schematic symbol and circuit context express design intent; a concrete
candidate proves its family with the exact live `secondTypeName`:

- `MOSFETs`
- `Bipolar (BJT)`
- `JFETs`

Always add the matching `secondTypeName` term when the symbol establishes one
of these classes.

## Polarity and channel

On a conventional BJT symbol, an emitter arrow pointing away from the base is
NPN and an arrow pointing toward the base is PNP. On a conventional JFET
symbol, a gate arrow pointing into the channel is N-channel and an arrow
pointing out of the channel is P-channel. Use these cues only when the target
symbol is clearly located and readable; otherwise preserve uncertainty.

The live catalog publishes the subtype under different normalized parameter
names for each family:

- MOSFET: `Type = N-Channel` or `Type = P-Channel`
- BJT: `type = NPN` or `type = PNP`
- JFET: `FET Type = N-Channel` or `FET Type = P-Channel`

Use the exact parameter appropriate to the visually identified class. A
package, designator, keyword match, or low-side/high-side placement is not
candidate proof. Some catalog records publish `-` or omit the parameter; those
parts remain honest misses rather than silently crossing polarity.

## Ratings and package

Measured catalog rating names include `Drain to Source Voltage` for MOSFETs,
`Collector - Emitter Voltage VCEO` and `Current - Collector(Ic)` for BJTs, and
`Gate-Source Breakdown Voltage (Vgss)` for JFETs. Constrain only ratings the
schematic actually states; threshold, on-resistance, gain, dissipation, and
pinout remain engineering choices when absent.

For this library, `SOT23-3` normalizes to `SOT-23`. The live catalog also has a
separate `SOT-23-3` spelling, but one search plan must use one exact package
net. Do not let two identical library footprints normalize differently merely
because their symbols differ.
