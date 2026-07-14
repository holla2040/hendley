# Part-class notes — what this shop knows about each kind of part

There is no one way to search for a part, and pretending there is has cost us
real searches. A resistor's index column `resistance` has the SAME NAME as the
catalog's `Resistance`, so a plan that states both ends up asking "10000 =
`10kΩ`" and rejects every part alive — while a capacitor, whose column is
`capacitance_farads`, must state both. An electrolytic hides its can dimensions
inside the package string. A diode's family — small-signal, Schottky, zener,
avalanche — is something the parts index **cannot tell you at all**:
`is_schottky` is `false` on every schottky in the catalog.

Every class has its own traps, and the cost of not knowing one is a search that
returns the wrong parts, or none, while looking like it worked.

So the knowledge lives here: **one markdown note per part class**, written by
whoever learned it, read by the agent the moment it opens a part of that class.
It is not in Python (ADR-0006 — Python composes nothing and judges nothing) and
it is not buried in a prompt string. It is a document you can edit.

## The format

A note opens with a fenced `applies-to` block:

    ```applies-to
    catalogType: Aluminum Electrolytic Capacitors - SMD
    catalogType: Aluminum Electrolytic Capacitors - Leaded
    category: capacitors
    ```

- **`catalogType`** — the live catalog's own `secondTypeName`. This is the only
  honest name for what a part *is*, and it is what a note should key on. Repeat
  the line for each class the note covers. Real examples:
  `Aluminum Electrolytic Capacitors - SMD`, `Schottky Barrier Diodes (SBD)`,
  `Zener Diodes`, `Chip Resistor - Surface Mount`,
  `ESD And Surge Protection (TVS/ESD)`.
- **`category`** — the jlcsearch slug (`capacitors`, `diodes`, `resistors`, …).
  A *fallback* only: it matches when the part has no catalog record to key on,
  and it is far coarser (every capacitor, electrolytic or not, is `capacitors`).

Everything after the block is the note, handed to the agent verbatim. Write it
for an engineer, not for a parser.

## What a good note says

Look at [aluminium-electrolytic-capacitors.md](aluminium-electrolytic-capacitors.md).
It answers:

- **Which index columns actually filter**, and what the tight net looks like.
- **What the catalog publishes** for this class, by exact parameter name.
- **How to constrain each field** — and which are `gte`/`lte` ("or better")
  rather than `eq`. Over-rating voltage is free margin; a shorter can still fits.
- **Which fields are a trap.** `Tolerance eq "±20%"` silently rejects a ±10%
  part, which is *better*.
- **Which index columns are poison.** Named, with the consequence spelled out.
- **Which fields are read-only** — strings like `17mA@120Hz` that can be shown
  but never compared.

## To find these facts for a new class

Everything in the electrolytic note was measured, not guessed:

- `hendley detail <code>` prints a real part's catalog record — its
  `secondTypeName` and its exact `parameters` names.
- The index's columns and their fill rates are measured against
  `jlcsearch.tscircuit.com/<category>/list.json`. A column that is **constant,
  always-null, sparsely populated, or carries no consistent UNIT proves
  nothing** — those live in `UNPROVABLE_COLUMNS` in
  `src/hendley/datasources/jlc/alternates.py`, and there are 46 of them.
  Probe more than one package: `resistors.power_watts` looks like a clean,
  fully-populated milliwatt column until you read a 2512 and find `1`, meaning
  one watt.

## No note is not a failure

A class nobody has written up yet simply gets no special knowledge, and the agent
stays conservative. **Never invent a note** — an unmeasured "fact" here is worse
than silence, because the agent will believe it.

## Written

- [Aluminium electrolytic capacitors](aluminium-electrolytic-capacitors.md)
- [Chip resistors (surface mount)](chip-resistors.md)

## Still to write

- MOSFETs
- The diode families — small-signal, Schottky, zener, avalanche/TVS — which the
  catalog's `secondTypeName` distinguishes and the index does not.
