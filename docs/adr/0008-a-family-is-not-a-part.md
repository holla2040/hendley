# ADR-0008 — A family is not a part

Status: accepted (2026-07-13)
Supersedes nothing. Bounds ADR-0006 ("discovery is judgment").

## Context

A designer places an IC and types **`ULN2003`** into the schematic VALUE. They do that
because the value shows on the schematic, which is convenient. They are never going to
type `SP3485EN-L/TR` into that field, and we should not ask them to.

What they typed is a **family** — an incomplete part number. `ULN2003` ships as SOIC-16,
SOP-16, TSSOP-16, DIP-16 and a wide-body SO-16-208mil. Only one of them fits the land
already on the board. **The orderable part is decided by the family plus the footprint,
and by nothing else.**

Hendley handled this in two ways, both wrong:

- **VALUE=`ULN2003`** → no spec, no mode. The interpreter was asked to invent a `SpecKey`
  from the library footprint *name* alone.
- **MPN attribute=`ULN2003`** → the line was **PINNED**. The family was treated as an
  exact orderable part, never sieved, and shipped to the resolver as if it were real.
  That was the default for any designer who filled in that attribute.

## The words (the full glossary is in CLAUDE.md)

One loose word ("anchor") cost a round-trip of confusion, so these are fixed:

- **family** — the incomplete part number the designer typed (`MB10S`). MPN attribute
  wins over VALUE; `MP`/`MF` are never a family.
- **land** — the physical copper the part solders to. It has **two names**: the
  **footprint** (the library's, e.g. `SOIC-4`) and the **package** (the catalog's, e.g.
  `MBS`). Telling those two apart is most of this job.
- **class** — the catalog's `secondTypeName`. A label. Never a query, never a sieve term.
- **trap** — a part that fits the same land and is NOT the same part (`MB6S` at 600 V
  under an `MB10S` at 1000 V). Shown, never silently substituted.
- **part** — a full MPN + LCSC code you can actually order.

## Decision

**A family is a discovery seed, never a selection mode.** It lives in
`RequirementLine.family` — deliberately not `mpn`, because a family is a *default*, not a
lock. `U`/`D`/`Q` designators with no LCSC and a footprint carry one; passives keep the
deterministic spec path.

**The query is `family + package`. Python composes it.** This is the one authorized
exception to ADR-0006's *"Python never composes a search"* (Craig, 2026-07-13):

    components/list.json?search=<family>&package=<package>

It is not judgment. The words are the **designer's own**, passed through verbatim, and
the package is a judgment the agent already made about the footprint. Asking an agent to
"plan" a query whose every term is already known would be theatre. Python composes this
one query shape and nothing else; every result is still live-verified and every term
still proven.

**The package is CHOSEN from the catalog's own vocabulary, never invented.** Ask the
catalog for the family with no package at all, read off the packages it actually stocks it
in, and pick from that list. A package judged from the library's footprint name is a guess
*at* the catalog's word rather than a reading *of* it, and they disagree exactly where it
hurts:

| library footprint | the natural judgment | what the catalog calls it |
|---|---|---|
| `SOIC-4` (bridge rectifier) | `SOIC-4` | **`MBS`** |
| `SOP04` (4-pin optocoupler) | `SOP-4` | **`SOP-4-2.54mm`** |

Both guesses return **zero rows** — not because JLC lacks the part (it has 40 of the first)
but because that is not its word. **A wrong package returns zero while looking exactly like
a family JLC does not stock**: indistinguishable from a true answer. This is the same class
of error as the class-label trap, and it is why the catalog is asked before the search is
fired. The geometry then decides *which* of the offered packages, when there is a choice.

**And a land is a SET of the catalog's words, not one of them.** The catalog spells one
land several ways and the spellings hold *different parts*:

    ?search=SP3485&package=SOIC-8  → 2 parts.  Best: C8963, 327k in stock, BASIC
    ?search=SP3485&package=SOP-8   → 10 parts. Best: C668205, 145k, extended

Both are the 3.9 mm 8-pin body. Forced to pick one string, the search throws away half the
field — here, the **Basic part with 7× the stock** — while looking like a complete answer.
So the sieve gained an `in` op and carries the set as one term; the index takes only one
`package`, so with a set the net widens to the family alone and the sieve narrows, which
is where the proving always belonged. A different *body* remains a different *land*:
150-mil and 300-mil SOIC-16 are not interchangeable.

**The footprint's GEOMETRY is read, not its name.** `electronics.Package.headline` says
*"Small Outline package 150 mil"* where the name says only `SO16`. The name cannot
distinguish a 3.9 mm body from a 7.5 mm one; those are different catalog packages holding
different parts. This is now captured schematic-side (no `BOARD;` switch) and fed to
`interpret_footprint`.

**The web is asked exactly one thing, once per family**: which complete part number
belongs in *this* land (the suffix decoder — ULN2003 `D` is a 3.9 mm SOIC, `NS` a 5.3 mm
SOP), and which lookalikes share the land but not the part. That is in the datasheet's
ordering table and nowhere in the catalog. `read_family()` is the only judgment allowed
`--allowedTools WebSearch`, and it is cached forever.

## The two things that must never be done

**1. The class is a label — never a query, and never a sieve term off the INDEX.**

Not a query: `?search=optocoupler` → 100 rows (the cap), topped by **LEDs**.
`?search=LTV-352T` → 1. FTS ANDs tokens against part *names*.

Not a sieve term either — **the index's `subcategory` column disagrees with the catalog
on the very parts in front of us** (measured 2026-07-13):

| code | CATALOG `secondTypeName` | INDEX `subcategory` |
|---|---|---|
| C8963 | `RS-485 / RS-422 ICs` | `RS-485/RS-422 ICs` |
| C2692302 | `RS-485 / RS-422 ICs` | **`Buffers / Drivers`** ← same family |
| C108824 | `Bridge Rectifiers` | `Bridge Rectifiers` |
| C2886577 | `Bridge Rectifiers` | **`Diodes - General Purpose`** ← same part |

C2886577 is an MB10S **mounted on a real board here**. A plan sieving on `subcategory`
would have rejected the part already on the board, while looking like it filtered — the
`is_schottky` / `is_polarized` failure mode exactly.

Note which side is wrong: **the CATALOG is consistent across both pairs; the INDEX is
not.** That is precisely why ADR-0007 says a part's class comes from `secondTypeName` and
never from an index column. `components.category` and `components.subcategory` are
therefore in `UNPROVABLE_COLUMNS` and are no longer offered to the agent.

**2. The web names the reference part, not the field.** It will say `PCF8574DWR` (TI). It
will never say `PCF8574DWR(UMW)` or `ULN2003ADTR(XBLW)` — JLC's house brands, which are
frequently the better buy (UMW: 9,910 in stock against NXP's 5,673). So the catalog sweep
is the field and the web's answer is the reference row that says which of them is right.
Neither replaces the other.

## Consequences

- A designer can keep typing families into VALUE, which is what they were going to do.
- A family in the MPN attribute can no longer pin an unorderable part number.
- `search.py` now proves the package on an FTS search. It previously proved **nothing** —
  `_query()` dropped every net param but `search`, and `_full_sieve()` returned early
  unless the mode was parametric.
- The traps (`PCF8574A` is a different I²C address; `MB6S` is 600 V where `MB10S` is
  1000 V; `EL357N` is 3–5× less CTR than `LTV-352T`; `MAX485` is a +5 V part on the
  identical SOIC-8 land) are surfaced, not silently substituted.
- One web call per family, ever. ~$0.15, cached in `interpretations`.
