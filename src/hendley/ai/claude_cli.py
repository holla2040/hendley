"""ClaudeCLIInterpreter — judgment via headless Claude Code (``claude -p``).

Rides the user's existing Claude subscription: no API key, no separate
billing, works on any machine where ``claude`` is installed and logged in.
Latency is seconds per call, which the interpretation cache makes
irrelevant (each unique string is judged once, ever).

Failure of any kind — binary missing, timeout, non-JSON output, refusal —
returns ``None``: the caller falls back to the one-time confirm card. The
LLM can lower zero-touch coverage, never break the flow.

A well-formed answer that isn't a COMPLETE spec is not a failure: it comes
back as an Interpretation with ``spec=None`` and the fields it did read in
``partial`` (the confirm card's prefill). Only ``None`` means "stop asking
this interpreter".
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Sequence
from typing import Any

from ..domain.model import SpecKey
from .interpreter import Interpretation
from .partnotes import note_for

DEFAULT_BIN = "claude"
TIMEOUT_S = 120

PROMPT = """\
You are the component-interpretation step of an electronics BOM tool.
A schematic part carries ad-hoc, designer-written text. Map it onto the
tool's canonical vocabulary.

Part context (verbatim from the design):
{context}

{part_notes}

Rules:
- kind: lowercase category noun (resistor, capacitor, inductor, diode, led,
  fuse, switch, connector, ic, transistor, crystal, ...). Use the
  designator prefix and value/footprint together.
- value: canonical short form, lowercase suffixes: resistance like "22k",
  "4.7k", "220", "1M"; capacitance like "100n", "47u"; inductance like
  "22u". Extra ratings (voltage, tolerance, dielectric) belong in
  qualifier, NOT in value. When the design states no value and none can be
  inferred (a diode with no VALUE — which part it is, is the engineer's
  call), answer "" and say so in the rationale: NEVER invent one. The
  fields you DID read still reach the engineer.
- package: normalize the library footprint name to the industry package it
  denotes, in catalog spelling:
  - a standard chip size (0201/0402/0603/0805/1206/1210/2010/2512) → that
    size ("R-0402" → "0402").
  - an embedded standard package name → the catalog form as distributors
    list it (e.g. "D-SOD323" → "SOD-323").
  - ONLY when no standard package is recognizable, keep the library
    footprint name VERBATIM (e.g. "C-E-5" — it keys the database).
- qualifier: the extra requirements as a short string (e.g. "50V",
  "1%", "X7R 25V"), or "" if none.
- envelope: your best reading of the footprint's physical reality:
  mount "smd" or "tht"; maxDiaMm / maxLenMm / leadSpacingMm when the
  footprint name or geometry implies them; omit fields you cannot infer.
  (Example: an Eagle footprint named C-E-5 is typically a radial
  electrolytic with 5 mm lead spacing, so bodies up to ~10-13 mm dia fit.)
- confidence: 0..1 — how sure you are of the WHOLE reading. Below 0.8 the
  tool will ask the engineer instead of trusting you; be honest.
- rationale: one short sentence.

Answer with ONLY this JSON object, no prose, no code fences:
{{"kind": "...", "value": "...", "package": "...", "qualifier": "...",
  "envelope": {{"mount": "smd|tht", "maxDiaMm": 0, "maxLenMm": 0,
                "leadSpacingMm": 0}},
  "confidence": 0.0, "rationale": "..."}}
"""

FOOTPRINT_PROMPT = """\
You are the footprint-normalization step of an electronics BOM tool.
A schematic library carries this footprint name, verbatim:
{footprint}

The library's OWN description of that footprint (empty if it gives none).
When it states a body width, a pitch or a span, THAT IS THE ANSWER and it
outranks anything you would infer from the name — the name is a local
convention and the geometry is a measurement:
{headline}

Map it to the industry package it denotes, in catalog spelling:
- a standard chip size (0201/0402/0603/0805/1206/1210/2010/2512) → that
  size ("C-0603" → "0603").
- an embedded standard package name → the catalog form as distributors
  list it (e.g. "D-SOD323" → "SOD-323").
- BODY WIDTH IS PART OF THE PACKAGE, and it is where this goes wrong. A
  16-pin small-outline part is "SOIC-16" at a 3.9mm body (150 mil) and
  "SOIC-16-300mil" at a 7.5mm one — different lands, different parts. A
  name like "SO16" does not say which; a headline reading "150 mil", or
  "10.32 mm span, 10.30 X 7.50", does. Use it.
- if no standard package is recognizable, package is "" — the library
  name keys the database instead; never guess.
Also your best reading of the footprint's physical envelope: mount "smd"
or "tht"; maxDiaMm / maxLenMm / leadSpacingMm when the name implies them;
omit fields you cannot infer.
confidence: 0..1 for the WHOLE reading; below 0.8 the tool ignores it —
be honest.

Answer with ONLY this JSON object, no prose, no code fences:
{{"package": "...", "envelope": {{"mount": "smd|tht", "maxDiaMm": 0,
  "maxLenMm": 0, "leadSpacingMm": 0}},
  "confidence": 0.0, "rationale": "..."}}
"""

# The parts index, as MEASURED (not as its column names advertise). Every
# claim here was verified live against jlcsearch; get this wrong and the
# tool ships the wrong part while looking like it filtered.
INDEX_FACTS = """\
The index (jlcsearch) has one endpoint per category, plus a keyword endpoint.

NET — the query. It honours ONLY these params. It SILENTLY IGNORES every
other param (an unknown name is not an error: you get 100 unfiltered rows
that LOOK filtered):
  - package        exact string, no wildcards ("0603", "SOD-323")
  - resistance     ohms      (resistors, resistor_arrays)
  - capacitance    farads    (capacitors; 100n = 1e-7)
  - search         keywords  (ONLY on the "components" endpoint)
Any category endpoint returns at most 100 rows, sorted by STOCK DESCENDING.

SIEVE — the truth. Python proves EVERY candidate against EVERY sieve term, so
the sieve cannot be ignored. Any constraint you put in the net you MUST also
put in the sieve; anything the net cannot express goes in the sieve alone. A
term nothing can prove sends that row to the "couldn't check" list, never to
the results.

A term's "field" may name EITHER of two vocabularies:
  - an INDEX column (listed below) — already a number, so it needs no unit;
  - a CATALOG parameter, spelled exactly as the catalog spells it
    ("Capacitance", "Voltage Rating", "Diameter", "Height - Seated (Max)").
    The catalog publishes the SAME names for every manufacturer, and it
    publishes far more than the index types — the capacitors table has no
    diameter or height column at all. When a catalog record is in front of
    you, ITS parameter names are the vocabulary: copy them VERBATIM.

The net's OWN params must appear in the sieve under their INDEX names
(package, capacitance_farads, resistance) — the request is rebuilt from the
terms, so that is what makes dropping a term really drop it from the query
instead of the net quietly re-asserting it. So a typical sieve is: the net's
params in index names, PLUS everything else in catalog names.

And when the index types a value the ENGINEER judges a part on (capacitance,
resistance), state it in BOTH vocabularies:
  {"field": "capacitance_farads", "op": "eq", "value": 1e-5}   ← builds the query
  {"field": "Capacitance",        "op": "eq", "value": "10uF"} ← the column they read
The index term is a number Python can filter on; the catalog term is what
becomes a COLUMN in the results table, in the units an engineer actually reads.
Neither is redundant. A value the engineer constrained but cannot see is a value
they cannot compare parts on.

A catalog value is TEXT ("50V", "5.4mm"). To compare it with lte/gte/lt/gt you
MUST declare its unit, and the unit must be the exact suffix the catalog
prints:
  {"field": "Voltage Rating", "op": "gte", "value": 50, "unit": "V"}
  {"field": "Height - Seated (Max)", "op": "lte", "value": 5.4, "unit": "mm"}
Python strips exactly that suffix and compares. A value that does not conform
to it ("17mA@120Hz" asked for in mA, "-40℃~+105℃") CANNOT be compared
numerically — use eq or contains for those, or leave them out. NEVER invent a
unit to force a comparison through.

WHAT THE PART *IS* — never ask the index. The index has no honest column for a
part's CLASS. Its flags LIE: is_polarized is false on every aluminium
electrolytic; is_schottky, is_zener and is_tvs are false on every schottky,
zener and TVS; capacitor_type is "unknown" and diode_type is "general_purpose"
for all of them. Those columns are NOT listed below and MUST NOT be used — a
term on one returns ZERO parts while looking like it filtered. The part's class
is catalog.secondType ("Aluminum Electrolytic Capacitors - SMD", "Schottky
Barrier Diodes (SBD)", "Chip Resistor - Surface Mount"). Read it there. If you
need a class you cannot prove, say so in "say" — do not fake it with a flag.

Column traps:
  - power_watts is the catalog's string WITH THE UNIT DROPPED, so its unit is
    not constant: 0603 = 100 (mW) but 2512 = 1, 2, 3 (WATTS), and 1206 holds
    both 250 and 1. It is also NULL on some rows. NEVER sieve on it — "gte 100"
    rejects every 1 W part, which is strictly better. Show it; do not prove it.
  - tolerance_fraction: 0.01 means ±1%. "1%" means "1% or better" → lte 0.01.
  - capacitance_farads is the row column; "capacitance" is the net param.
  - Prefer the INDEX column when the catalog's string carries an SI prefix
    (resistance "1.5kΩ", capacitance "10uF") — the column is already a number
    and comparable. Prefer the CATALOG for everything the index doesn't type.
  - ONE TERM PER FIELD. An index column and a catalog parameter that differ only
    in case or punctuation are the SAME FIELD (resistance / "Resistance";
    voltage_rating / "Voltage Rating"). Stating both is not belt-and-braces: the
    string one ("10kΩ") is compared against the column's NUMBER and misses on
    every part alive. Capacitance is the exception — its column is
    capacitance_farads, a different name, so a cap may state both.

Categories and their sieve columns — this list is MEASURED. A column not named
here either does not exist or cannot prove anything; either way, do not use it.
  resistors: resistance, tolerance_fraction, package, max_overload_voltage,
    is_basic  (power_watts exists but CANNOT be proved — see the traps above)
  resistor_arrays: resistance, tolerance_fraction, package,
    number_of_resistors, number_of_pins, topology  (power_watts: as above)
  capacitors: capacitance_farads, tolerance_fraction, voltage_rating,
    temperature_coefficient(X7R/X5R/C0G/NP0 — NULL on electrolytics), package
  diodes: forward_voltage, reverse_voltage, recovery_time_ns, package,
    configuration
  leds: color, wavelength_nm, forward_voltage, forward_current,
    luminous_intensity_mcd, viewing_angle_deg, power_dissipation_mw,
    lens_color, package
  mosfets: drain_source_voltage, continuous_drain_current,
    gate_threshold_voltage, power_dissipation, package
  fuses: current_rating, voltage_rating, is_resettable, package
  ldos: output_voltage_min, output_voltage_max, output_current_max,
    dropout_voltage, input_voltage_min, input_voltage_max, quiescent_current,
    output_type, package
  voltage_regulators: output_voltage_min, output_voltage_max,
    output_current_max, dropout_voltage, input_voltage_min,
    input_voltage_max, package
  headers: pitch_mm, num_pins, num_rows, num_pins_per_row, gender,
    is_right_angle, is_shrouded, current_rating_amp, package
  jst_connectors / wire_to_board_connectors: pitch_mm, num_pins, num_rows,
    reference_series, gender, mounting_style, package
  usb_c_connectors: number_of_contacts, number_of_ports, current_rating_a,
    gender, mounting_style, package
  switches: switch_type, circuit, current_rating_a, voltage_rating_v,
    pin_count, package
  relays: relay_type, contact_form, coil_voltage, coil_resistance,
    max_switching_current, max_switching_voltage, package
  potentiometers: max_resistance, package
  microcontrollers: cpu_core, cpu_speed_hz, flash_size_bytes, gpio_count,
    has_usb, has_adc, package
  arm_processors / risc_v_processors: cpu_speed_hz, flash_size_bytes,
    ram_size_bytes, gpio_count, package (arm_processors also: cpu_core)
  adcs: resolution_bits, num_channels, sampling_rate_hz, supply_voltage_min,
    supply_voltage_max, has_spi, has_i2c, package
  dacs: resolution_bits, settling_time_us, supply_voltage_min,
    supply_voltage_max, package
  io_expanders: num_gpios, has_i2c, has_spi, has_interrupt, package
  led_drivers: output_current_max, channel_count, supply_voltage_min,
    supply_voltage_max, package
  fpc_connectors: pitch_mm, number_of_contacts, contact_type
  battery_holders: battery_type, connector_type, package
  microphones: microphone_type, package
  accelerometers: axes, supply_voltage_min, supply_voltage_max, package
  gyroscopes: axes, supply_voltage_min, supply_voltage_max, has_i2c, has_spi,
    package
  wifi_modules: core_processor, antenna_type, frequency_ghz, package
  fpgas / led_with_ic / gas_sensors: package ONLY — the index cannot filter
    these; prove everything against the catalog's parameters.
  Every category also carries: is_basic, is_preferred, price1, stock.
  These categories are EMPTY — never use them (use mode "fts"):
    bjt_transistors, boost_converters, buck_boost_converters, lcd_display,
    oled_display, led_dot_matrix_display.
  There is NO inductors category — inductors use mode "fts".
"""

READ_PROMPT = """\
You are the reading step of an electronics BOM tool. The engineer just opened
one of their design's parts. Work out what it actually IS — and hand back the
search that would find more of it.

Everything the tool knows about this part:
{dossier}

HOW TO READ IT
- If "catalog" is present, it is the part's own record from the live parts
  catalog, fetched with the part number the schematic pins. It is GROUND
  TRUTH. Do not guess ANYTHING it already tells you:
    * the package is catalog.package (componentSpecification) — VERBATIM.
      It may be Chinese ("插件" = through-hole/plug-in, "贴片" = SMD) and it
      may carry dimensions ("插件,D5xL11mm"). Copy it exactly; it is the only
      string the index will match.
    * the value, voltage, tolerance, dielectric, dimensions, pin pitch are in
      catalog.parameters. Read them off.
    * confidence should be HIGH (>0.9): you are not guessing, you are reading.
- The schematic's own words are how the ENGINEER describes the part
  ("10uF@50V"), and its footprint is a LIBRARY name ("C-E-5", "R-0603").
  A library footprint name is NOT a catalog package. It never goes in a
  query — it would match nothing. Use the catalog package if you have one;
  otherwise normalize the footprint if it plainly denotes a standard package
  ("R-0603" → "0603", "D-SOD323" → "SOD-323"), and if it does not, leave the
  package OUT of the query entirely and say what it implies as sieve terms
  instead (is_polarized, is_surface_mount, mounting_style ...).
- Digits in a library footprint name are not measurements unless the library
  headline or drawing explicitly establishes that meaning. `C-E-10` is a local
  identifier, not proof of a 10 mm diameter. Never turn such digits into a
  package or dimensional sieve term.
- With no catalog record, read what you can from the designator, the value and
  the footprint, and be honest about confidence.
- If "visualEvidence" is present, the attached images are the schematic sheets
  and board for this exact design revision. Locate the requested designator in
  the schematic before interpreting its symbol. Symbol shape, polarity marks,
  terminal labels and nearby circuit context are evidence of DESIGN INTENT:
  use them to distinguish broad classes such as polarized/electrolytic versus
  ordinary capacitors; zener/TVS/schottky/ordinary diodes; and MOSFET/BJT/JFET
  plus channel or polarity where the symbol actually shows it. The board image
  may support mount/package conclusions but not electrical class. In Fusion
  board exports, a red rectangular copper pad with no visible drill is an SMD
  pad; a through-hole pad has a visible drilled hole (often a dark or colored
  circular center). Do not call two undrilled pads through-hole merely because
  a circular can outline surrounds them. `visualEvidence.placements` gives the
  footprint names and board coordinates for the labeled lands in that same
  image. A plainly standard land such as 0603 or a known pin pitch may be used
  as a visual ruler: compare pixel spans to estimate the target body's diameter
  or pad span. State the visual comparison and uncertainty; do not use a local
  footprint's digits as the measurement. When a diameter is visually supported,
  include it both as a live catalog `Diameter` sieve term (unit `mm`) and as a
  compact discovery token such as `D5`; the token fetches while the catalog
  parameter proves. Never claim
  `visualEvidence.boardCrops` gives exact physical width/height for a crop
  centered on the requested designator. Use that known frame as the preferred
  ruler; the target land is at its center. Do not mistake a neighboring label
  or footprint for the centered target.
  a subtype the drawing does not show. State visual cues in the rationale and
  lower confidence when the symbol is generic or the target cannot be located.

WHAT TO HAND BACK
- "is": one plain-English line naming the part, as an engineer would say it
  ("10 uF 50 V aluminium electrolytic, through-hole, D5 x 11 mm, 2 mm pitch").
- "spec": the canonical key — kind, value, package (CATALOG package),
  qualifier (the ratings: "50V", "X7R", "1%"). Leave value "" if the part
  genuinely has none (a general-purpose diode); never invent one.
- "search": the words that go in the search box — what an engineer would type
  to find this part again. Keep them few and searchable. NEVER put a library
  footprint name ("C-E-5") or the schematic's punctuation ("10uF@50V") in it.
- "plan": the query that finds more of this part, ready to fire (same rules as
  below: only package + one value param actually filter; everything you demand
  must ALSO be in the sieve).
  Use mode `fts` with category `components` and a FEW class-specific search
  words when class is essential but no exact catalog package is known. A broad
  parametric value query is capped before the live class sieve runs; keyword
  discovery can put the intended class inside that cap. The class still MUST be
  proven with `secondTypeName` because keyword/index matches are not proof.
  Keep this discovery phrase COARSE: defining value/rating plus the broad
  subtype noun (for example `10uF 25V electrolytic`). Do not add mount words,
  material spelling variants, polarity, or the family noun when the live sieve
  already proves them; the name index ANDs every token, so `SMD aluminum` can
  hide valid catalog-class matches before proof.
  Use mode `parametric` when an exact catalog package or a sufficiently narrow
  dense value net is known.
  When "catalog" is present, build the SIEVE FROM catalog.parameters — one term
  per parameter that genuinely constrains the part, each field spelled VERBATIM
  as the catalog spells it, each unit declared. The engineer sees these terms
  before they search and drops the ones they don't want, so ask for what the
  part actually IS — with "or better" wherever an engineer would take better:
      Voltage Rating        → gte   (a 63 V part drops into a 50 V slot)
      Height - Seated (Max) → lte   (a shorter can still fits the board)
      Capacitance, Diameter, Tolerance, dielectric → eq (these must match)
  LEAVE OUT what merely DESCRIBES the part rather than constraining it
  (Lifetime, Operating Temperature, an ESR of "-"). A term nobody asked for
  only throws good parts away.
- When the evidence identifies a component class, make that intent executable:
  add a sieve term on the live catalog field `secondTypeName`. Copy an exact
  value (or an `in` list of exact values) from `catalogClassVocabulary` in the
  dossier. Do not invent a catalog label. This is the authoritative class
  proof for electrolytic/ceramic capacitors, diode subtypes, and transistor
  families; never substitute an index class flag. If your `intent.subtype`
  names one of those distinctions and the vocabulary contains the matching
  class, the term is REQUIRED rather than something to defer until after search.

{index_facts}
Answer with ONLY this JSON object, no prose, no code fences:
{{"is": "...",
  "intent": {{"family": "...", "subtype": "...", "polarity": "...",
               "mount": "...", "visualCues": ["..."],
               "uncertainties": ["..."]}},
  "spec": {{"kind": "...", "value": "...", "package": "...",
            "qualifier": "..."}},
  "search": "...",
  "plan": {{"mode": "parametric|fts", "category": "...", "net": {{}}, "sieve": [
      {{"field": "...", "op": "eq|ne|lte|gte|lt|gt|contains|isTrue|isFalse",
        "value": 0, "unit": ""}}]}},
  "rationale": "one short sentence — say if you read it from the catalog",
  "confidence": 0.0}}
"""

SEARCH_PROMPT = """\
You are the search step of an electronics BOM tool. An engineer typed words
into a parts search box. Turn their words into a query plan.

The design line they typed it against (verbatim from the schematic):
{context}

What they typed (VERBATIM — this is what they want, it outranks the design
line if the two disagree; empty means "use the design line"):
{terms}
{instruction}
{index_facts}
Choose a mode:
- "code"       they gave a JLC part code (C12345). net {{}}, sieve [].
- "fts"        they gave a manufacturer part number or a name, or nothing
               in the catalog's parametric vocabulary fits. category is
               "components", net is {{"search": "<the words to match>"}}.
               Keep the words FEW — this index ANDs tokens against part
               NAMES, so extra words ("resistor", "1%") find nothing.
- "parametric" the normal case for passives and any part with a category.
               Put package + the one value param in the net; put EVERY
               constraint (including those two) in the sieve.

sieve ops: eq, ne, lte, gte, lt, gt, contains, isTrue, isFalse.
An "or better" reading is your job: 1% → tolerance lte 0.01; 25V → voltage
gte 25; 1/4W → power_watts gte 250.
If "catalog" is present it is the part they are searching FROM — its parameter
names are the vocabulary for the sieve, spelled verbatim, with units declared.

lookingFor: your reading of what they want, for the screen — NOT a database
key, so leave a field "" rather than inventing it.
say: one short line naming what you searched for, in the engineer's words
("22k 0603, 1% or better, 1/4W or better"). It is shown above the results.
confidence: 0..1, honest.

Answer with ONLY this JSON object, no prose, no code fences:
{{"mode": "parametric|fts|code", "category": "...",
  "net": {{"package": "...", "resistance": 0}},
  "sieve": [{{"field": "...", "op": "eq|ne|lte|gte|lt|gt|contains|isTrue|isFalse",
              "value": 0, "unit": ""}}],
  "lookingFor": {{"kind": "...", "value": "...", "package": "...",
                  "qualifier": "..."}},
  "say": "...", "confidence": 0.0}}
"""

FAMILY_PROMPT = """\
You are the part-identification step of an electronics BOM tool. A designer
labelled a component with a FAMILY — an incomplete part number — and the
board carries a footprint. Your job is to say which member of that family
may actually go on that board, and what would go wrong if the wrong one did.

USE WEB SEARCH. The catalog cannot answer this: it lists what is in stock, not
what the suffixes MEAN. The manufacturer's datasheet ordering table can.

The family the designer typed (verbatim):
{family}

The footprint on the board, and the library's own description of it (the
description is a measurement and outranks the name):
  name:     {footprint}
  geometry: {headline}

THE PACKAGES THE CATALOG ACTUALLY STOCKS THIS FAMILY IN, with how many parts
sit in each. This is the catalog's OWN vocabulary, and it is the only spelling
that will match anything:
{packages}

{family_notes}

Find, from the datasheet / distributor pages:

0. packages: EVERY catalog package listed above that is THIS SAME LAND — the one
   the board has. Copy them VERBATIM from that list; a package the catalog does
   not use finds nothing, however right it looks. Two things go wrong here:

   - GUESSING. A bridge rectifier's land is called "SOIC-4" by the library and
     "MBS" by the catalog; a 4-pin optocoupler's is "SOP04" in the library and
     "SOP-4-2.54mm" in the catalog. Neither is guessable — both are in the list.

   - PICKING ONLY ONE. The catalog spells ONE land several ways, and the
     different spellings hold DIFFERENT parts. The 3.9mm 8-pin body is both
     "SOIC-8" and "SOP-8": the Basic, 327k-in-stock SP3485 sits under SOIC-8 and
     a search that chose SOP-8 never sees it. So name them ALL.

   But ONLY the ones that are the same land. BODY WIDTH IS A DIFFERENT LAND:
   150-mil "SOIC-16" and 300-mil "SOIC-16-300mil" are NOT interchangeable, and
   nor is a TSSOP, a DIP or a QFN. Use the geometry to decide.
   If none of them is this footprint, return [] and say why. [] is honest;
   a wrong package is not.

1. partNumbers: the COMPLETE, orderable part numbers of this family that fit
   THIS footprint — most-standard first. Decode the suffix: for ULN2003, "D"
   is a 3.9mm-body SOIC and "NS" is a 5.3mm-body SOP, so a 150-mil land wants
   a ULN2003ADR and NOT a ULN2003ANSR. Give the base part numbers; do not
   worry about tape-and-reel suffixes.
   If you cannot tell which fits, return [] and SAY SO in rationale. An empty
   list is an honest answer. A guessed part number is not.

2. class: what this part IS, in plain words ("bridge rectifier", "RS-485
   transceiver", "I2C I/O expander"). For the panel — a label, nothing more.

3. traps: the parts that FIT THE SAME LAND but are NOT the same part. This is
   the whole point of asking you, and it is where a board gets ruined. Each is
   {{"part": "<the lookalike>", "why": "<what differs, concretely>"}}.

   ⚠️ A TRAP IS ABOUT FUNCTION, NEVER ABOUT THE PACKAGE. Do not say a part is
   the wrong body, the wrong land or the wrong pin count — the CATALOG proves
   the package for every part, exactly, and it outranks you. Saying "PCF8574T is
   the narrow 3.9mm body" when the catalog lists that very part as
   SOIC-16-300mil does not protect anyone: it slanders a good part, and the
   engineer may skip the one they should have bought. The package is handled.
   You are here for what the package CANNOT show: the address, the voltage, the
   gain, the temperature grade, the register model.

   Real examples of exactly what to catch:
     - PCF8574 vs PCF8574A — a DIFFERENT I2C base address (0x20 vs 0x38).
       Identical package. The firmware will not find it.
     - MB10S (1000V) vs MB6S (600V) — same MBS package, 40% less standoff.
     - LTV-352T (CTR 1000-5000%) vs LTV-357T / EL357N (CTR 50-600%) — same
       SOP-4 land, 3-5x less current transfer.
     - a temperature grade (SP3485EN = -40..+85C, SP3485CN = 0..+70C).
     - PCA9554 vs PCF8574 — same pinout, same I2C address range, but REGISTER
       based: its ports power up as inputs and a bare byte write does not drive
       them. Solders down, ACKs, does nothing.
   Only state a trap you actually verified. [] is fine. NEVER invent one.

confidence: 0..1, honest.

Answer with ONLY this JSON object, no prose, no code fences:
{{"packages": ["..."], "partNumbers": ["..."], "class": "...",
  "traps": [{{"part": "...", "why": "..."}}],
  "rationale": "...", "confidence": 0.0}}
"""

KEY_PROMPT = """\
You are the bookkeeping step of an electronics BOM tool. The engineer just
approved a part for a design line. Name the REQUIREMENT that part satisfies
— the key this shop's approved-parts database (the AVL) files it under, and
looks it up by in every future design.

The design line (verbatim from the schematic):
{context}

What the engineer searched for: {terms}
What the app had remembered for this line: {remembered}
The part they approved (verified from the catalog):
{part}

Rules for the key:
- kind: the lowercase category noun (resistor, capacitor, diode, led, ...).
- value: the part's defining value — "22k", "100n", "10u". A resistor or a
  capacitor always has one. A general-purpose diode, a test point, a
  connector may have NONE: then leave value "". NEVER INVENT ONE — an empty
  value is a correct answer, a fabricated one poisons every future design.
  A part number is not a value (that is what the approved part records).
- package: the catalog package ("0603", "SOD-323"), not the library
  footprint name ("R-0603", "D-SOD323") — unless nothing standard is
  recognizable, in which case keep the library name verbatim.
- qualifier: the RATINGS and requirements that make this need distinct from
  the same kind/value/package with different demands — "1%", "X7R 50V",
  "1/4W", "zener 10V", "schottky". If the engineer's search asked for it, it
  belongs here. Empty when there is nothing to distinguish.

Think about the NEXT design that hits this same requirement: too loose a key
mounts the wrong part silently; too tight a key makes the shop re-approve
the same thing forever. Key what the DESIGN needs, not what this one part is.

Answer with ONLY this JSON object, no prose, no code fences:
{{"spec": {{"kind": "...", "value": "...", "package": "...",
            "qualifier": "..."}},
  "rationale": "one short sentence", "confidence": 0.0}}
"""

SIEVE_OPS = ("eq", "ne", "lte", "gte", "lt", "gt", "contains", "in",
             "isTrue", "isFalse")
TRUTH_OPS = ("isTrue", "isFalse")


def _term(p: Any) -> dict | None:
    """One sieve term, or nothing at all.

    A term is a PROMISE that Python can check the part against: a field, an op,
    and — unless the op is a bare truth test — something to compare with. A term
    with no ``value`` cannot pass anything, so it would quietly fail every
    candidate and read on screen as if the catalog had let the engineer down.
    Drop it instead; a malformed predicate is never guessed at.
    """
    if not isinstance(p, dict):
        return None
    field = str(p.get("field") or "").strip()
    op = str(p.get("op") or "").strip()
    if not field or op not in SIEVE_OPS:
        return None
    term = {"field": field, "op": op}
    if op not in TRUTH_OPS:
        if p.get("value") is None or p.get("value") == "":
            return None
        term["value"] = p["value"]
    unit = str(p.get("unit") or "").strip()
    if unit:                    # the unit the CATALOG prints, so "50V" compares
        term["unit"] = unit
    return term


def _class_notes(catalog: dict | None, category: str | None = None) -> str:
    """What this shop knows about THIS class of part (``docs/parts/``).

    Every part class has its own traps, and no prompt can carry them all. The
    note for the class in front of us is pasted in whole; a class nobody has
    written up gets nothing, and the agent stays conservative rather than
    guessing. See ``partnotes.py``.
    """
    note = note_for((catalog or {}).get("secondType"), category)
    if not note:
        return ""
    vocabulary = ""
    if not (catalog or {}).get("secondType") and category:
        from .partnotes import catalog_types_for

        types = catalog_types_for(category)
        if types:
            vocabulary = ("\nCATALOG CLASS VALUES DOCUMENTED FOR THIS CATEGORY "
                          "(copy only values supported by the evidence):\n- "
                          + "\n- ".join(types) + "\n")
    return ("\nWHAT THIS SHOP KNOWS ABOUT THIS CLASS OF PART — measured, and it\n"
            "outranks the general rules above wherever the two disagree:\n\n"
            + note + vocabulary + "\n")


class ClaudeCLIInterpreter:
    """Interpretation through ``claude -p`` with strict-JSON output."""

    name = "claude-cli"

    def __init__(self, binary: str | None = None, timeout: int = TIMEOUT_S):
        self.binary = binary or os.environ.get("HENDLEY_CLAUDE_BIN", DEFAULT_BIN)
        self.timeout = timeout

    def interpret_part(self, ctx: dict) -> Interpretation | None:
        designator = str(ctx.get("designator") or "")
        prefix = "".join(c for c in designator if c.isalpha()).upper()
        note = note_for(designator=prefix)
        if prefix == "D":
            from ..requirements.normalizer import has_zener_evidence

            ctx = dict(ctx)
            ctx["zenerEvidence"] = has_zener_evidence(
                designator, str(ctx.get("value") or ""),
                dict(ctx.get("attributes") or {}))
        prompt = PROMPT.format(
            context=json.dumps(ctx, indent=2, ensure_ascii=False),
            part_notes=("SHOP KNOWLEDGE — apply it conservatively; a local alias "
                        "must still be confirmed by the engineer:\n\n" + note)
            if note else "")
        obj = self._ask(prompt)
        if obj is None:
            return None
        interpreted = self._parse(obj)
        # Diode class is too consequential to leave solely to a probabilistic
        # reading. With no written Z cue, an ordinary reverse-voltage rating
        # must never become a Zener requirement.
        if (prefix == "D" and not ctx.get("zenerEvidence") and interpreted.spec
                and "zener" in interpreted.spec.qualifier.casefold()):
            qualifier = re.sub("zener", "", interpreted.spec.qualifier,
                               flags=re.IGNORECASE).strip(" ,;/")
            interpreted.spec = SpecKey(
                interpreted.spec.kind, interpreted.spec.value,
                interpreted.spec.package, qualifier)
            interpreted.rationale = (
                interpreted.rationale + "; Zener removed because the design contains no Z cue"
            ).strip("; ")
        return interpreted

    def interpret_footprint(self, footprint: str,
                            headline: str = "") -> dict | None:
        """Judge one library footprint name → its catalog package (+envelope).

        ``headline`` is the library's own description of the footprint, and it is
        the only honest way to tell a 3.9mm body from a 7.5mm one: "SO16" is a
        local convention, "Small Outline package 150 mil" is a measurement.

        Returns ``{"package", "envelope", "confidence", "rationale"}`` or
        None on any failure. An empty ``package`` is a valid, honest answer
        (nothing standard recognizable)."""
        obj = self._ask(FOOTPRINT_PROMPT.format(
            footprint=footprint, headline=headline or "(the library gives none)"))
        if obj is None or "package" not in obj:
            return None
        env = obj.get("envelope") or {}
        try:
            confidence = max(0.0, min(1.0, float(obj.get("confidence") or 0.0)))
        except (TypeError, ValueError):
            return None
        return {
            "package": str(obj.get("package") or "").strip(),
            "envelope": {k: v for k, v in env.items() if v not in (None, 0, "")},
            "confidence": confidence,
            "rationale": str(obj.get("rationale") or ""),
        }

    def read_family(self, family: str, footprint: str = "", headline: str = "",
                    packages: Sequence[tuple[str, int]] = ()) -> dict | None:
        """What may go on this board, given a FAMILY and the footprint under it.

        The one judgment that needs the WEB. The catalog lists what is in stock;
        it does not say what a part-number suffix MEANS, and it will not tell you
        that a PCF8574A is a different I2C address from a PCF8574 in an identical
        body. The datasheet's ordering table says both.

        ``packages`` is the catalog's OWN list of packages it stocks this family
        in, with counts — and handing it over is what makes the answer land. A
        package judged from the footprint name alone is a plausible guess against
        the catalog's actual word: the library calls a bridge rectifier's land
        ``SOIC-4`` and the catalog calls it ``MBS``; the library says ``SOP04``
        and the catalog says ``SOP-4-2.54mm``. Both guesses return ZERO rows
        while looking perfectly reasonable. So the agent CHOOSES from the
        catalog's vocabulary instead of inventing a word in it.

        It chooses **all** the words for one land, not one of them: the catalog
        spells the 3.9mm 8-pin body both ``SOIC-8`` and ``SOP-8``, and they hold
        DIFFERENT parts — the Basic, 327k-in-stock SP3485 is under ``SOIC-8``, so
        a search that had to pick one string would simply never see it.

        Returns ``{"packages", "partNumbers", "class", "traps", "rationale",
        "confidence"}``, or None if the interpreter is unavailable. An EMPTY
        ``partNumbers`` is an honest answer, not a failure: the catalog sweep
        still finds the parts, including the ones the web never names — JLC's
        house brands, frequently the better buy. What the web adds is knowing
        WHICH of them is right, and what is merely lurking in the same land.
        """
        if not str(family or "").strip():
            return None
        offered = {str(p) for p, _ in packages}
        truncated = bool(getattr(packages, "truncated", False))
        listing = "\n".join(f"  {p}  ({n} parts)" for p, n in packages)
        if truncated:
            listing += ("\n  [INCOMPLETE: the catalog capped this sample at 100 rows. "
                        "You may name a datasheet-supported package absent from the "
                        "sample; the caller will verify that exact spelling.]")
        obj = self._ask(
            FAMILY_PROMPT.format(
                family=family,
                footprint=footprint or "(none given)",
                headline=headline or "(the library gives none)",
                packages=listing or "  (the catalog stocks none of this family)",
                family_notes=("REPOSITORY FAMILY GUIDANCE — measured knowledge "
                              "that outranks generic examples:\n\n" +
                              (note_for(judgment="family") or "(none)"))),
            tools="WebSearch",
        )
        if obj is None:
            return None
        # every package must be one the CATALOG uses. A word it does not use finds
        # nothing, so an invented one is dropped rather than fired.
        chosen = [str(p).strip() for p in (obj.get("packages") or [])
                  if str(p).strip()]
        packages_out = [p for p in chosen if truncated or not offered or p in offered]
        traps = [
            {"part": str(t.get("part") or "").strip(),
             "why": str(t.get("why") or "").strip()}
            for t in (obj.get("traps") or []) if isinstance(t, dict)
            and str(t.get("part") or "").strip() and str(t.get("why") or "").strip()
        ]
        try:
            confidence = max(0.0, min(1.0, float(obj.get("confidence") or 0.0)))
        except (TypeError, ValueError):
            confidence = 0.0
        return {
            "packages": packages_out,
            "partNumbers": [str(p).strip() for p in (obj.get("partNumbers") or [])
                            if str(p).strip()],
            "class": str(obj.get("class") or "").strip(),
            "traps": traps,
            "rationale": str(obj.get("rationale") or ""),
            "confidence": confidence,
        }

    def read_part(self, dossier: dict) -> dict | None:
        """Work out what a part IS, from everything known. See the protocol."""
        from .partnotes import catalog_types_for

        dossier = dict(dossier)
        dossier["catalogClassVocabulary"] = catalog_types_for()
        visual = dossier.get("visualEvidence") or {}
        target = str(visual.get("designator") or "")
        crops = [c for c in (visual.get("boardCrops") or [])
                 if str(c.get("designator") or "") == target]
        crop_images = [str(c.get("image")) for c in crops if c.get("image")]
        board = str(visual.get("boardImage") or "").strip()
        images = crop_images + ([board] if board else []) + [
            str(p) for p in (visual.get("images") or [])
            if str(p).strip() and str(p) != board and str(p) not in crop_images]
        obj = self._ask(READ_PROMPT.format(
            dossier=json.dumps(dossier, indent=2, ensure_ascii=False),
            index_facts=INDEX_FACTS + _class_notes(dossier.get("catalog"))),
            images=images)
        if obj is None:
            return None
        spec = obj.get("spec") or {}
        try:
            key = SpecKey(
                kind=str(spec.get("kind") or "").strip().lower(),
                value=str(spec.get("value") or "").strip(),
                package=str(spec.get("package") or "").strip(),
                qualifier=str(spec.get("qualifier") or "").strip(),
            ).to_dict()
        except (ValueError, TypeError):
            key = None      # couldn't place it — the reading still stands
        try:
            confidence = max(0.0, min(1.0, float(obj.get("confidence") or 0.0)))
        except (TypeError, ValueError):
            confidence = 0.0
        return {
            "is": str(obj.get("is") or "").strip(),
            "intent": dict(obj.get("intent") or {}),
            "spec": key,
            "search": str(obj.get("search") or "").strip(),
            "plan": self._plan({"mode": "parametric", **(obj.get("plan") or {})}),
            "rationale": str(obj.get("rationale") or ""),
            "confidence": confidence,
        }

    def plan_search(self, ctx: dict) -> dict | None:
        """Plan a catalog query from the engineer's words. See the protocol."""
        design = {k: ctx.get(k) for k in ("designator", "value", "footprint")}
        told: list[str] = []
        # the engineer's own corrections are ORDERS, not hints: a designator
        # letter means whatever this shop's library says it means (X is a
        # connector in one house and a socket in another — you cannot know)
        convention = ctx.get("convention") or {}
        if convention.get("kind"):
            told.append(
                f"THIS SHOP'S CONVENTION: designator '{convention.get('prefix')}' "
                f"means a {convention['kind']}"
                + (f" (category '{convention['category']}')"
                   if convention.get("category") else "")
                + " — they told you so; do not second-guess it.")
        forced = str(ctx.get("category") or "").strip()
        if forced:
            told.append(
                f"THE ENGINEER HAS CHOSEN THE CATEGORY: '{forced}'. Use it, "
                "exactly. Do not pick another. Build the net and sieve from "
                "ITS columns."
                + (" ('components' is the keyword index — use mode 'fts'.)"
                   if forced == "components" else ""))
        catalog = ctx.get("catalog")
        if catalog:
            design["catalog"] = catalog   # the part they are searching FROM
        obj = self._ask(SEARCH_PROMPT.format(
            context=json.dumps(design, indent=2, ensure_ascii=False),
            terms=json.dumps(str(ctx.get("terms") or ""), ensure_ascii=False),
            instruction=("\n" + "\n".join(told) + "\n") if told else "",
            index_facts=INDEX_FACTS + _class_notes(catalog, forced or None)))
        if obj is None:
            return None
        plan = self._plan(obj)
        if plan and forced and plan["category"] != forced:
            plan["category"] = forced      # their choice stands, always
        return plan

    def _plan(self, obj: dict) -> dict | None:
        mode = str(obj.get("mode") or "").strip().lower()
        if mode not in ("parametric", "fts", "code"):
            return None
        net = obj.get("net")
        sieve = obj.get("sieve")
        looking = obj.get("lookingFor") or {}
        try:
            confidence = max(0.0, min(1.0, float(obj.get("confidence") or 0.0)))
        except (TypeError, ValueError):
            confidence = 0.0
        return {
            "mode": mode,
            "category": str(obj.get("category") or "").strip(),
            "net": dict(net) if isinstance(net, dict) else {},
            # a malformed predicate is dropped, never guessed at
            "sieve": [t for t in map(_term,
                                     sieve if isinstance(sieve, list) else [])
                      if t],
            "lookingFor": {k: str(looking.get(k) or "").strip()
                           for k in ("kind", "value", "package", "qualifier")}
            if isinstance(looking, dict) else {},
            "say": str(obj.get("say") or "").strip(),
            "confidence": confidence,
        }

    def derive_key(self, ctx: dict) -> dict | None:
        """Name the requirement a pick satisfies. See the protocol."""
        design = {k: ctx.get(k) for k in ("designator", "value", "footprint")}
        obj = self._ask(KEY_PROMPT.format(
            context=json.dumps(design, indent=2, ensure_ascii=False),
            terms=json.dumps(str(ctx.get("terms") or ""), ensure_ascii=False),
            remembered=json.dumps(ctx.get("remembered") or {}, ensure_ascii=False),
            part=json.dumps(ctx.get("part") or {}, indent=2, ensure_ascii=False)))
        if obj is None:
            return None
        spec = obj.get("spec")
        if not isinstance(spec, dict):
            return None
        try:
            key = SpecKey(
                kind=str(spec.get("kind") or "").strip().lower(),
                value=str(spec.get("value") or "").strip(),
                package=str(spec.get("package") or "").strip(),
                qualifier=str(spec.get("qualifier") or "").strip(),
            )
        except (ValueError, TypeError):
            return None   # kind or package missing: no key, the caller says so
        try:
            confidence = max(0.0, min(1.0, float(obj.get("confidence") or 0.0)))
        except (TypeError, ValueError):
            confidence = 0.0
        return {"spec": key.to_dict(),
                "rationale": str(obj.get("rationale") or ""),
                "confidence": confidence}

    def _ask(self, prompt: str, tools: str = "", images=()) -> dict | None:
        """Run ``claude -p`` and return the extracted JSON object, or None.

        ``tools`` opts one judgment into Claude Code's tools (``"WebSearch"``).
        It is off by default and stays off for every judgment that the catalog
        can answer: a web call is slow and costs money, and a judgment that CAN
        be made from data we hold should never be made from a search result.
        Only :meth:`read_family` needs it — what a part-number suffix MEANS is
        in the datasheet's ordering table and nowhere in the catalog.
        """
        # The Claude compatibility backend has no repository-proven local-image
        # transport. It accepts this shared argument and falls back to the text
        # dossier; Codex attaches the actual files.
        argv = [self.binary, "-p", prompt, "--output-format", "json"]
        if tools:
            argv += ["--allowedTools", tools]
        try:
            proc = subprocess.run(
                argv, capture_output=True, text=True, timeout=self.timeout,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return None
        if proc.returncode != 0:
            return None
        try:
            envelope = json.loads(proc.stdout)
            text = envelope.get("result") if isinstance(envelope, dict) else None
        except json.JSONDecodeError:
            text = proc.stdout
        if not text:
            return None
        return _extract_json_object(text)

    def _parse(self, obj: dict) -> Interpretation | None:
        fields = {
            "kind": str(obj.get("kind") or "").strip().lower(),
            "value": str(obj.get("value") or "").strip(),
            "package": str(obj.get("package") or "").strip(),
            "qualifier": str(obj.get("qualifier") or "").strip(),
        }
        env = obj.get("envelope") or {}
        try:
            confidence = max(0.0, min(1.0, float(obj.get("confidence") or 0.0)))
        except (TypeError, ValueError):
            confidence = 0.0
        out = Interpretation(
            envelope={k: v for k, v in env.items() if v not in (None, 0, "")},
            confidence=confidence,
            rationale=str(obj.get("rationale") or ""),
        )
        try:
            out.spec = SpecKey(**fields)
        except (ValueError, TypeError):
            # an incomplete reading is knowledge, not failure (a diode with no
            # schematic VALUE): it prefills the confirm card, and the
            # interpreter stays alive for every other part
            out.partial = {k: v for k, v in fields.items() if v}
        return out


def _extract_json_object(text: str) -> dict | None:
    """The model was told 'JSON only', but strip fences/prose defensively."""
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None
