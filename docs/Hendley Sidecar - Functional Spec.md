# Fusion Sidecar Mission Direction

## Purpose

This document defines a practical mission direction for a Sidecar application that supports electronics design in Fusion while keeping the schematic generic and separating design intent from procurement resolution.

The core idea is to let Fusion remain the source of truth for circuit intent, while the Sidecar manages sourcing intelligence, inventory matching, candidate manufacturer part numbers, and final purchasable BOM generation.[cite:55][cite:59][cite:71]

## Guiding Principle

The schematic should describe what the circuit needs, not which exact vendor part was available on a particular day.[cite:27][cite:68] Manufacturer part numbers, distributor SKUs, stock conditions, and temporary sourcing substitutions are procurement-layer concerns and should be handled outside the ECAD editor whenever possible.[cite:27][cite:72]

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

## Voice-Driven Constraint Entry

A preferred interaction model is voice input to the Sidecar. The user can keep working in the schematic while speaking constraints such as dielectric, tolerance, voltage rating, technology, or vendor preference for a single designator.

Example intent:

- "R22 needs to be 1% metal film."
- "C14 should be X7R, 50V."
- "U3 must avoid Vendor X."
- "This capacitor should be low ESR."

The Sidecar should interpret the spoken instruction, normalize it into structured fields, associate it with the correct designator, and then both persist the requirement and launch sourcing searches without interrupting schematic capture.[cite:77][cite:84]

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

## Matching Model

The Sidecar should not treat the Fusion designator itself as the long-term reusable key. A designator is local to a schematic instance and is not a good cross-project identity.

Instead, the Sidecar should derive its internal matching identity from the full set of relevant attributes attached to the part, such as part family, value, package, tolerance, voltage, dielectric, technology, or other constraints.[cite:77] The designator is the handle for current-project interaction, while the attribute set is the basis for reusable sourcing knowledge.

## Why MPNs Should Stay External

Writing the selected MPN back into Fusion is optional and not required for the proposed architecture. Keeping MPNs external avoids polluting the schematic with volatile supply-chain decisions and lets the design remain stable even when stock, preferred suppliers, or approved alternates change over time.[cite:27][cite:68]

This also makes obsolescence handling cleaner. The schematic can stay unchanged while the Sidecar periodically refreshes candidate matches for the same generic requirements against current inventory and lifecycle conditions.[cite:27][cite:35]

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

## Mission Summary

The mission is not to turn Fusion into a sourcing engine. The mission is to build a Sidecar that lets the user design with generic parts, express real engineering constraints naturally, and postpone manufacturer-level decisions until a dedicated procurement-resolution stage.[cite:55][cite:71][cite:72]

That separation is the central design principle for the system.
