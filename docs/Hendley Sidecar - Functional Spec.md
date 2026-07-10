# Fusion Sidecar Mission Direction

> **STATUS: UNDER REVIEW — do not build against this document yet.**
>
> Reviewed 2026-07-09. The central thesis is sound and is independently correct
> (see [Appendix A: Prior Art](#appendix-a-prior-art)). Three specific proposals
> in this document are defective, one contradicts code already committed in
> `c5707c9`, and the citation markers are unsourced. Inline annotations are
> marked **[REVIEW]**. Decisions required before implementation are collected in
> [Appendix B](#appendix-b-open-questions--decisions-required).
>
> Nothing below has been deleted. Original text is preserved verbatim.
>
> *(Filename says "Functional Spec"; the title says "Mission Direction." It is
> currently the latter. Pick one.)*

## Purpose

This document defines a practical mission direction for a Sidecar application that supports electronics design in Fusion while keeping the schematic generic and separating design intent from procurement resolution.

The core idea is to let Fusion remain the source of truth for circuit intent, while the Sidecar manages sourcing intelligence, inventory matching, candidate manufacturer part numbers, and final purchasable BOM generation.[cite:55][cite:59][cite:71]

## Guiding Principle

The schematic should describe what the circuit needs, not which exact vendor part was available on a particular day.[cite:27][cite:68] Manufacturer part numbers, distributor SKUs, stock conditions, and temporary sourcing substitutions are procurement-layer concerns and should be handled outside the ECAD editor whenever possible.[cite:27][cite:72]

> **[REVIEW]** This principle is correct, and it is not new — it is the
> **CPN + AVL/AML** model that enterprise EDA has used for ~30 years. The
> schematic carries a *corporate part number* (an internal ID for "22k 0603 1%
> thin film"); a PLM system holds an *approved manufacturer list* of qualified
> substitute MPNs against that CPN; binding happens at BOM release. Altium
> ships this as managed components + **Part Choices** + **ActiveBOM**;
> OrCAD as **CIS**; Zuken and Siemens as a central library with an AML per part.
>
> This document should say so. Not for credit-assignment reasons — because
> **each sub-problem below was already hit and solved by that lineage**, and
> three of this document's proposals get them wrong by not looking. The real
> split in the industry is not "spec-driven vs. MPN-in-schematic," it is
> **who has a PLM and who does not**. Hendley is a single-user PLM.
>
> Full survey in [Appendix A](#appendix-a-prior-art).

## Primary Workflow

The intended workflow is:

1. Place a generic component in Fusion.
2. Set the obvious design fields in Fusion, such as value, package, and basic part type.
3. Continue schematic work without stopping to search distributor sites or assign an MPN manually.
4. Use the Sidecar application, ideally by voice, to add extra per-designator constraints when needed.
5. Let the Sidecar search current inventory and maintain candidate matches in its own database.
6. Export a generic BOM from Fusion when needed.
7. Let the Sidecar transform that generic BOM into a final purchasing BOM using its stored matches, live inventory checks, and approval logic.[cite:71][cite:72][cite:73]

## Role of Fusion

Fusion should remain generic-first in this workflow. It should store the designator, generic component type, value, package, and any additional design requirements that are important for correctly characterizing the part in the circuit.[cite:77][cite:84]

Fusion already supports component and library attributes, and those attributes can be used as the structured home for design-level constraints rather than forcing the user to encode those constraints into a synthetic key string.[cite:77] This avoids brittle naming conventions and keeps the schematic readable.

> **[REVIEW] — CONFLICT WITH SHIPPED CODE.** "Rather than forcing the user to
> encode those constraints into a synthetic key string" is an argument against
> `partsdb.py`'s spec key `(kind, value, package, qualifier)` and against the
> standing rule in `CLAUDE.md` that *the agent supplies canonical keys, with no
> value normalization or spec parsing in Python*. Both this document and that
> code landed in the same commit (`c5707c9`). They are incompatible designs.
>
> This is a legitimate disagreement, not a mistake — but it is unresolved, and
> it is the single most load-bearing open question in the project. See
> [Appendix B, Q1](#q1--what-is-the-stable-identity-of-a-house-part).

## Role of the Sidecar

The Sidecar is responsible for the procurement and resolution layer.

Its main functions are:

- Accept natural-language or voice input about part requirements.
- Parse that input into structured attributes.
- Write those structured attributes back to the appropriate component in Fusion when possible through the available automation path.[cite:55][cite:59]
- Search supplier and inventory sources in parallel.
- Maintain an internal database of candidate and approved part matches.
- Reuse prior resolutions across projects when the same generic requirements appear again.
- Generate the final purchasable BOM externally from the generic Fusion BOM plus Sidecar knowledge.[cite:27][cite:72]

> **[REVIEW]** "Search supplier and inventory sources **in parallel**" glosses
> the hardest part of the system. Today there is exactly **one** supplier (JLC),
> and discovery already depends on a **third-party scraper index**
> (`jlcsearch.tscircuit.com`) because JLC's official API cannot search at all.
> Plural "supplier sources" implies an aggregator. The industry answer is
> **Octopart / Nexar**, which is a paid API with rate limits and licence terms.
> Name it and price it, or scope the document to JLC-only and say so.
>
> "Write those structured attributes back to Fusion" — see the annotation on
> [Immediate Build Direction](#immediate-build-direction) for why this is the
> wrong thing to put on the critical path.

## Voice-Driven Constraint Entry

A preferred interaction model is voice input to the Sidecar. The user can keep working in the schematic while speaking constraints such as dielectric, tolerance, voltage rating, technology, or vendor preference for a single designator.

Example intent:

- "R22 needs to be 1% metal film."
- "C14 should be X7R, 50V."
- "U3 must avoid Vendor X."
- "This capacitor should be low ESR."

The Sidecar should interpret the spoken instruction, normalize it into structured fields, associate it with the correct designator, and then both persist the requirement and launch sourcing searches without interrupting schematic capture.[cite:77][cite:84]

> **[REVIEW]** Voice is an **input modality, not architecture**, and this
> document gives it a top-level section, a place in the Mission Summary, and
> steps 1–2 of the build plan. That is a prioritization smell: the resolution
> and approval engine is the value; voice is a UI over it.
>
> Note also that **natural-language constraint intake already exists** — it is
> what the agent conversation in this repo *is* (`order-bom` skill, `CLAUDE.md`
> → "having a conversation about JLC parts"). Steps 1–2 are arguably already
> done for free. What does not exist is durable per-designator constraint
> storage. Build that; speech-to-text is a bolt-on to it later.

## Attribute Strategy

The approach should avoid a single packed field with separators or a pipe-delimited signature. Instead, the Sidecar should use separate structured attributes for each meaningful requirement.[cite:77]

Suggested attribute examples include:

- `TOLERANCE`
- `DIELECTRIC`
- `VOLTAGE_RATING`
- `POWER_RATING`
- `TEMP_COEFF`
- `ESR_CLASS`
- `NOISE_CLASS`
- `TECHNOLOGY`
- `PREFERRED_VENDOR`
- `DISALLOWED_VENDOR`
- `SIDECAR_STATUS`
- `SIDECAR_NOTES`[cite:77]

This structure is easier to inspect, easier to parse from speech, easier to update later, and easier to map into a generic BOM export than a single encoded field.[cite:77]

> **[REVIEW] — DEFECT. This list violates this document's own principle.**
>
> "Why MPNs Should Stay External" (below) argues that volatile supply-chain
> decisions must not pollute the schematic. Yet the last four entries here are
> to be written *into Fusion component attributes*:
>
> | Attribute | Layer | Belongs in Fusion? |
> |---|---|---|
> | `TOLERANCE`, `DIELECTRIC`, `VOLTAGE_RATING`, `POWER_RATING`, `TEMP_COEFF`, `TECHNOLOGY` | design intent | **yes** — these define the part |
> | `ESR_CLASS`, `NOISE_CLASS` | design intent (if the circuit needs it) | yes, but see Q1 |
> | `PREFERRED_VENDOR`, `DISALLOWED_VENDOR` | procurement | **no** — volatile, sidecar-owned |
> | `SIDECAR_STATUS`, `SIDECAR_NOTES` | sidecar bookkeeping | **no** — this is the sidecar using the schematic as its own database |
>
> `SIDECAR_STATUS` in the schematic is precisely the pollution the document
> warns against three sections later. The AVL model draws this line cleanly and
> for good reason: **design constraints attach to the CPN and live in the CAD;
> vendor preference, approval state, and lifecycle attach to the AVL and never
> touch the CAD.** A vendor going out of favour must not dirty the design file.
>
> Split the list along that line. Do not adopt it as written.

## Matching Model

The Sidecar should not treat the Fusion designator itself as the long-term reusable key. A designator is local to a schematic instance and is not a good cross-project identity.

Instead, the Sidecar should derive its internal matching identity from the full set of relevant attributes attached to the part, such as part family, value, package, tolerance, voltage, dielectric, technology, or other constraints.[cite:77] The designator is the handle for current-project interaction, while the attribute set is the basis for reusable sourcing knowledge.

> **[REVIEW] — The first half is right; the second half is a defect.**
>
> "A designator is local to a schematic instance and is not a good cross-project
> identity" is exactly the corporate-part-number realization, derived here from
> first principles. That is the hard insight and it is correct.
>
> But **"derive identity from the full set of relevant attributes" is an
> unstable key.** The identity of a part changes the moment its attribute set
> changes. Add `NOISE_CLASS` to capacitors next year and every capacitor that
> gains the field becomes a *new* part with no history — the accumulated
> sourcing intelligence silently forks, and `record()`'s promote/demote history
> chain snaps. Nothing errors. You just quietly stop knowing what you chose last
> time.
>
> This is why a CPN is an **assigned, opaque, stable handle** rather than a
> function of the spec: it survives attribute drift by construction. The shipped
> `(kind, value, package, qualifier)` tuple is a fixed-arity compromise — ugly,
> but it does not have this failure mode. **As specified, this section is a
> regression against code committed alongside it.**
>
> See [Appendix B, Q1](#q1--what-is-the-stable-identity-of-a-house-part).

## Why MPNs Should Stay External

Writing the selected MPN back into Fusion is optional and not required for the proposed architecture. Keeping MPNs external avoids polluting the schematic with volatile supply-chain decisions and lets the design remain stable even when stock, preferred suppliers, or approved alternates change over time.[cite:27][cite:68]

This also makes obsolescence handling cleaner. The schematic can stay unchanged while the Sidecar periodically refreshes candidate matches for the same generic requirements against current inventory and lifecycle conditions.[cite:27][cite:35]

> **[REVIEW]** The reasoning holds, but **"lifecycle conditions" is not
> implementable against the current data source.** JLC's component API
> (`getComponentDetailByCode`) returns stock, price, and parameters — it does
> **not** return lifecycle / EOL / NRND status. Neither does `jlcsearch`.
> "Refreshes against lifecycle conditions" therefore requires a second data
> source (Octopart/Nexar, SiliconExpert, or a distributor feed), which is a paid
> dependency this document does not acknowledge.
>
> What *is* implementable today is stock-and-price refresh — which is what
> `update_verified()` already does, with the standing warning that it is an
> advisory cache and **must never be ordered against**. Say that instead, or
> take on the dependency explicitly.
>
> Note also the tension with the section title: this section argues MPNs stay
> external, while [Attribute Strategy](#attribute-strategy) proposes writing
> vendor preference and sidecar status *into* Fusion. Resolve.

## BOM Strategy

The intended BOM strategy is generic-in, purchasable-out.

Fusion should produce a BOM that reflects the design at a generic level using its supported BOM and attribute mechanisms.[cite:71][cite:77] The Sidecar then consumes that generic BOM, resolves each line item using its internal database and live inventory queries, and emits a final purchasing BOM containing manufacturer part numbers, supplier SKUs, pricing context, and alternates where appropriate.[cite:72]

This approach turns BOM resolution into a downstream transformation stage instead of forcing sourcing decisions during schematic entry.[cite:72]

## Platform Constraints and Opportunity

Autodesk has introduced an electronics API as a first step with read-only support, while also exposing MCP and script-execution pathways that make automation around Fusion more practical than the raw electronics API alone would suggest.[cite:50][cite:55][cite:59][cite:61]

That makes the Sidecar approach attractive because it can rely on an agent-plus-execution path rather than waiting for native full-featured ECAD sourcing automation to arrive in the editor itself.[cite:55][cite:59]

## Error Handling and Clarification

Voice-driven entry should not blindly write back ambiguous or domain-inconsistent input. If the Sidecar hears something questionable, it should confirm before persisting it.

For example, a phrase that sounds like an invalid attribute combination or duplicated tolerance should trigger a clarification request rather than silently writing bad metadata into the project.[cite:77]

## Separation of Responsibilities

### Fusion owns

- Schematic capture
- Generic component identity
- Value
- Package
- Per-part design constraints as structured attributes
- Human-readable circuit intent[ cite:77][cite:84]

### Sidecar owns

- Voice or natural-language intake
- Constraint normalization
- Inventory and sourcing search
- Candidate MPN selection
- Preferred and rejected alternatives
- Approval history
- Time-sensitive supplier data
- Final purchasable BOM generation[ cite:27][cite:72]

## Desired End State

The desired end state is a workflow where the designer places generic parts, sets obvious circuit properties in Fusion, speaks additional per-designator requirements into the Sidecar as needed, and keeps moving without pausing to do manual part research.

The Sidecar continuously accumulates sourcing intelligence in the background and later converts the generic design BOM into a procurement-ready BOM at order time.[cite:72] This keeps the design environment focused on engineering intent and moves the volatile sourcing problem into a specialized companion system.[cite:27][cite:68]

## Immediate Build Direction

The first implementation should focus on the following:

1. Capture designator-targeted voice instructions.
2. Parse those instructions into structured attributes.
3. Associate them with the correct Fusion component.
4. Persist the normalized constraints in Fusion attributes when possible.[cite:55][cite:59][cite:77]
5. Store the same normalized constraints in the Sidecar database.
6. Query supplier sources for candidate matches.
7. Preserve candidate sets, approval state, and timestamps.
8. Ingest a generic BOM export from Fusion and produce a final purchasing BOM externally.[cite:71][cite:72]

> **[REVIEW] — DEFECT. The cost of this ordering is inverted.**
>
> Steps 3–4 put the **most fragile machinery in the repo on the critical path**
> of the most frequent operation. Writing constraints back into Fusion means the
> `Electron.run` / `.scr` bridge, which per `docs/fusion-notes.md` and
> `CLAUDE.md`: returns **no value** (success is indistinguishable from failure
> without an out-of-band read); leaves changes **unsaved** until the user saves
> in Fusion, so a crash silently loses them; and depends on `object_id`s that
> are **reassigned on every reload**, so every write needs a fresh scoped read
> first. It also stops at the first failing command in a script.
>
> Meanwhile the document correctly calls MPN write-back **"optional and not
> required."** That is backwards with respect to cost:
>
> - **Constraints churn constantly** during schematic capture — this is the hot
>   path, and it is the one being routed through the brittle bridge.
> - **MPNs are written once**, at order time, if ever.
>
> If constraints live in the sidecar keyed to the spec, **the write side is not
> needed for this workflow at all**, and the sidecar becomes an offline,
> testable, crash-safe component. The counter-argument is real and should be
> weighed rather than dismissed: attributes stored in Fusion travel with the
> design, survive loss of the sidecar DB, and are visible to the designer
> without a second tool. The AVL model's answer is to split them — design
> constraints in the CAD, sourcing constraints in the PLM — which is the same
> conclusion the [Attribute Strategy](#attribute-strategy) annotation reaches
> from the other direction.
>
> **Suggested reordering** (build the engine, bolt the UI on):
>
> 1. Durable per-designator constraint storage in the sidecar (no Fusion writes).
> 2. Generic BOM ingest → resolution → purchasable BOM out. *(Largely exists:
>    `load_resolution_json()` → `render_bom_csv()`.)*
> 3. Candidate sets, approval state, timestamps. *(Largely exists: `record()`
>    promote/demote + `history()`.)*
> 4. Resolve **Q1** and migrate the key.
> 5. Constraint write-back into Fusion for the *design-intent* subset only.
> 6. Voice intake.

## Mission Summary

The mission is not to turn Fusion into a sourcing engine. The mission is to build a Sidecar that lets the user design with generic parts, express real engineering constraints naturally, and postpone manufacturer-level decisions until a dedicated procurement-resolution stage.[cite:55][cite:71][cite:72]

That separation is the central design principle for the system.

> **[REVIEW]** Agreed, and worth stating plainly: **that separation is correct,
> it is the right principle, and this document arrived at it independently.**
> Everything flagged above is a matter of *how* to implement it, not *whether*.

---

# Appendix A — Prior Art

*Added 2026-07-09 during review. Confidence is noted per item; this territory
moves, and some details post-date the reviewer's knowledge. Verify before
relying on any specific claim.*

The separation this document proposes is the **CPN + AVL/AML** model, standard
in enterprise hardware for roughly thirty years:

- A schematic symbol carries a **Corporate Part Number (CPN)** — an internal
  identifier for a *specification*, e.g. "22k 0603 1% thin film."
- A PLM system holds an **Approved Manufacturer List (AML)** / **Approved Vendor
  List (AVL)** against that CPN: several MPNs, all qualified substitutes.
- The MPN is **bound at BOM release**, not at design time. Purchasing selects
  from the AML based on what is actually available that week.

Hendley's house-parts DB is a small, single-user instance of this. The spec key
is the CPN; the DB row plus its promote/demote `history()` chain is the AML.
**The industry split is not "spec-driven vs. MPN-in-schematic" — it is who has a
PLM and who does not.**

### Where each tool sits

**Altium** — *high confidence on architecture, lower on tiers/UI.* Does this
most explicitly, since roughly 2015. A managed component in an Altium 365
workspace is defined by symbol + footprint + parameters (a spec) and carries a
list of **Part Choices**: approved MPNs mapped to that component. **ActiveBOM**
then performs supply-chain resolution at BOM time — queries live distributor
data, ranks solutions by stock and price, lets you choose a manufacturer part
per line, flags lines with no valid solution or with obsolete parts. The
schematic references the component ID, not the MPN. **This document's workflow,
shipped as a product.**

**OrCAD / Allegro** — *high confidence.* **CIS** (Component Information System)
is literally a database binding a design part to a corporate part number and its
manufacturer parts, resolved via database queries.

**Zuken (CR-8000), Siemens Xpedition** — *high confidence.* Both drive from a
central corporate library with an AML per part. Same model, older, less
pleasant.

**KiCad** — *high confidence on the mechanisms.* The interesting case. KiCad 7
added **database libraries** (`.kicad_dbl`): symbols backed by an external SQL
table, one row per part, fields mapped to columns. KiCad 8 added **HTTP
libraries** pulling from a REST endpoint, the usual backend being **InvenTree**
(open-source PLM). So the machinery exists — but **binding happens at placement
time**: you pick the row and the symbol instance is stamped with that row's MPN.
There is no BOM-time re-resolution pass, no "this part died, show me alternates
against the same spec." You rerun placement or hand-edit fields.

Notably, the community plugin **`kicad-jlcpcb-tools`** independently arrived at
something close to this design: it keeps LCSC part assignments in a project-side
database rather than in the schematic, and injects them into fab outputs at
export. Its key is the **designator**, not the spec — so it does not accumulate
reusable knowledge across projects — but the instinct to keep sourcing out of
the schematic is the same one, and it is worth reading before building.

**Fusion Electronics** — *lowest confidence; verify.* The weakest of the three,
which is presumably why this repo exists. It inherits EAGLE's model: a device
has attributes, `MPN`/`OPN` among them, and EAGLE bolted on an Octopart-backed
supply-chain panel showing pricing and availability. Fusion has library
management and a path into Fusion Manage for PLM, but nothing resembling
ActiveBOM's resolution pass — and the Electronics **object API is read-only**,
hence this repo's `.scr` / `Electron.run` bridge.

### What is actually novel here

Not the decoupling. Two smaller things, both real:

1. **The key is the spec tuple itself, not an assigned opaque CPN.** This
   eliminates the part-number administration step that makes CPN systems
   miserable for one person — nobody allocates `RES-0603-22K0-1P` or maintains a
   registry. The tradeoff is that the key space is only as consistent as its
   canonicalization, which is why `partsdb.py` pushes canonicalization onto the
   agent instead of parsing specs in Python. That is the right call, and it
   means `22k` / `22K` / `22000` are three different parts unless something
   upstream stays disciplined. **See Q1 — this is the crux.**

2. **Alternate selection is a judgment call by an agent** weighing verified live
   data against stated preferences (this user's documented bias: high inventory
   over low price), rather than a fixed ranking. Altium's ActiveBOM ranks;
   `alternates.py` explicitly refuses to sort, filter, or pick. **That is the
   genuinely different bet, and it is the thing worth defending.**

---

# Appendix B — Open Questions / Decisions Required

*These block implementation. None is answered by this document as written.*

### Q1 — What is the stable identity of a house part?

Three incompatible answers currently exist in the repo:

| Option | Where it lives | Fails how |
|---|---|---|
| **A.** Fixed tuple `(kind, value, package, qualifier)` | `partsdb.py`, `CLAUDE.md` — **shipped** | Rigid arity; can't express a new constraint without a schema change. Canonicalization is the agent's problem. |
| **B.** Hash of the full attribute set | This document, "Matching Model" | **Unstable.** Adding an attribute silently reforks identity and orphans history. |
| **C.** Assigned opaque CPN, attributes hang off it | The industry answer | Requires a registry and an allocation step — the very bureaucracy a one-person shop is trying to avoid. |

A and B are both committed in `c5707c9`. **They cannot both be right.** C is what
everyone else converged on, and its stated cost may be smaller than it looks if
the agent allocates the CPN rather than the human.

*Recommendation: C, with agent-allocated identifiers, keeping A's tuple as a
lookup index rather than as the identity. Decide before writing more code
against either.*

### Q2 — Which attributes live in Fusion, and which in the sidecar?

The document proposes writing all twelve into Fusion, then argues four sections
later that volatile data must stay out of the schematic. Split the list along
the design-intent / procurement line — see the
[Attribute Strategy](#attribute-strategy) annotation for a proposed split.

### Q3 — Is Fusion constraint write-back required at all for v1?

If constraints live in the sidecar, the `Electron.run` write bridge is not on
the critical path and the sidecar becomes offline and testable. What is lost:
constraints no longer travel with the design file, and are invisible without the
sidecar. **Decide whether that loss is acceptable for v1.** (It probably is.)

### Q4 — One supplier or many?

"Search supplier and inventory sources in parallel" implies an aggregator. Today
there is one supplier (JLC) and discovery runs through a third-party scraper
index because the official API cannot search. Multi-source means **Octopart /
Nexar** — a paid API with rate limits and licence terms. Either take the
dependency explicitly or scope the document to JLC-only.

### Q5 — Where does lifecycle / EOL data come from?

JLC's API does not return it. Neither does `jlcsearch`. The obsolescence story
in "Why MPNs Should Stay External" is currently unimplementable. Same answer set
as Q4.

### Q6 — What does "approval" mean?

The document says "preserve candidate sets, approval state, and timestamps" but
never defines: who approves, what invalidates an approval, or whether an
approved part stays approved when its spec key changes (see Q1 — under option B,
it silently does not). `partsdb.py` already has a real answer for part of this
(promote on `record()`, demote the prior row, never delete). Build on it or
supersede it deliberately.

---

# Appendix C — On the citation markers

This document carries ~30 `[cite:NN]` markers. **There is no bibliography — in
this file or anywhere in the repository.** Verified:

```
$ grep -rl "cite:" --exclude-dir=.git .
docs/Hendley Sidecar - Functional Spec.md
```

This is almost certainly an artifact of a research-mode drafting tool whose
reference list was dropped on the way out. As it stands the markers **assert
authority the document cannot cash**, and a reader has no way to check a claim
or tell a sourced statement from an invented one.

They have been left in place rather than stripped, because they may be
recoverable from the original drafting session. **Either restore the
bibliography or delete the markers.** Do not ship them as-is.
