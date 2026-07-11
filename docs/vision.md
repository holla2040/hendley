# Hendley Vision

**Project:** Hendley — AI-Assisted BOM Resolver  
**Version:** 1.0  
**Status:** Vision baseline

## 1. Vision

Hendley will separate **electronic design intent** from **manufacturing component selection**.

Current ECAD workflows commonly require engineers to attach manufacturer, distributor, or assembly-provider part numbers to schematic components. That approach makes procurement information part of the design record even when the circuit only requires a generic electrical component.

For many components, the engineer's intent is straightforward:

- 22 kΩ
- ±1%
- 0603
- minimum power rating
- compatible footprint

The exact purchasable part depends on inventory, lifecycle, price, manufacturing provider, and build quantity. Those conditions change far more frequently than the design.

Hendley introduces a dedicated, AI-assisted resolution layer between ECAD and manufacturing. It interprets engineering requirements, evaluates purchasable candidates, applies provider-specific sourcing policy, presents ranked and explainable recommendations, records the engineer's decisions, and produces a manufacturing-ready BOM.

The objective is simple:

> **Free engineers to do design.**

AI assists with repetitive analysis. Engineers retain final authority.

## 2. The Problem

The conventional workflow mixes two different activities:

1. **Engineering definition** — determining what the circuit requires.
2. **Manufacturing resolution** — determining which specific part should be purchased and assembled now.

This coupling creates recurring problems:

- Supply-chain changes require maintenance of otherwise-correct design data.
- Engineers repeatedly search catalogs, compare inventory, and locate alternates.
- Board-house identifiers become embedded in schematic attributes.
- Proven component choices are difficult to reuse consistently.
- A design becomes unnecessarily coupled to one sourcing or manufacturing workflow.
- Preparing a manufacturing BOM can consume hours after the design is complete.

Existing supply-chain features are useful, but they usually begin after a specific manufacturer part or managed component has already been selected. Hendley addresses the earlier decision: whether a specific purchasable part needs to be fixed in the design at all.

## 3. Why Now

Modern AI, structured component data, and programmable provider interfaces make a different workflow practical.

The system can now:

- interpret engineering attributes
- normalize inconsistent component descriptions
- search provider and distributor data
- apply deterministic engineering constraints
- compare valid alternatives
- explain tradeoffs
- preserve approval history
- reuse proven parts across projects

AI is an enabling technology, not the authority. Hard requirements remain deterministic, supplier facts remain sourced, and the engineer approves every released selection.

## 4. Separation of Concerns

Hendley intentionally separates the following responsibilities.

### Engineering Design

Owned by the ECAD system and the engineer:

- schematic capture
- PCB layout
- electrical intent
- mechanical intent
- design verification
- explicit exact-part requirements

### Requirements Capture

Owned by an ECAD importer or live-design integration:

- read component attributes
- preserve reference designators and quantities
- distinguish mandatory constraints from preferences
- normalize the design into a provider-independent Requirements BOM

### Component Resolution

Owned by the resolver core:

- discover candidates
- reject incompatible parts
- rank valid candidates
- identify exceptions
- explain recommendations
- prepare decisions for review

### Procurement Policy

Owned by a Provider Strategy:

- choose eligible data sources
- define stock and sourcing rules
- contribute provider-specific eligibility and ranking policy
- express manufacturing-provider preferences

### Provider Output

Owned by a Provider Adapter:

- validate provider-required fields
- map approved results into the provider's format
- emit manufacturing-ready BOMs and supporting reports

### Engineering Knowledge

Owned by the Knowledge Base:

- record approvals and rejections
- preserve rationale
- identify prior use
- favor proven components when they remain valid
- never override mandatory engineering constraints

## 5. Initial Manufacturing Target

The first complete target is the JLCPCB/LCSC workflow.

JLCPCB is a useful first implementation because its assembly process depends heavily on LCSC/JLC component identifiers and provider-specific inventory. Hendley should remove the need to place those identifiers in Fusion Electronics merely so they appear in an exported BOM.

JLCPCB is the first provider, not an architectural limitation. PCBWay is the second target because it exercises a different sourcing model and helps prove that the resolver core is provider-independent.

## 6. Human and AI Roles

The division of responsibility is explicit:

- deterministic code validates hard constraints
- provider data supplies inventory, pricing, lifecycle, and identifiers
- ranking policy orders valid candidates
- AI interprets ambiguity and explains tradeoffs
- the engineer approves or rejects the result

Guiding principle:

> **AI advises. Engineers decide.**

## 7. Reusable Engineering Knowledge

Every approval is potentially useful beyond the current project.

If a 22 kΩ, 0603, 1% resistor has been approved and successfully manufactured on several boards, Hendley should prefer it again when:

- the engineering requirements still match
- the selected provider can source it
- sufficient inventory exists
- lifecycle status remains acceptable
- no project-specific rule excludes it

Historical use informs the recommendation. It does not prove eligibility and does not replace current validation.

## 8. Current Hendley and the Target Product

The repository already contains practical building blocks:

- JLCPCB API access
- live component detail, stock, price, and parameter retrieval
- BOM stock checking
- alternate discovery with live JLC verification
- Fusion Electronics design reading over its local HTTP interface
- generation of explicit, engineer-reviewed Fusion migration scripts

These capabilities are the starting point. The target product adds the provider-independent Requirements BOM, deterministic resolver, ranking, knowledge reuse, review workflow, and provider adapters described in the PRD.

Existing migration utilities may remain as explicit engineering tools, but they are not part of the automatic BOM-resolution path and must not blur the boundary between design intent and procurement resolution.

## 9. Success

The intended workflow is:

1. The engineer completes and verifies the design.
2. Hendley reads the live design or imports its component data.
3. Hendley constructs and validates a Requirements BOM.
4. The engineer selects a Provider Strategy.
5. Hendley finds, filters, and ranks candidates.
6. The engineer reviews recommendations and exceptions.
7. Hendley records approvals.
8. A Provider Adapter generates the manufacturing-ready BOM.
9. The engineer submits the result to the assembly provider.

Routine post-design BOM work should be reduced from hours of catalog searching to minutes of focused review.

## 10. Long-Term Direction

Hendley should become an open, provider-independent platform for moving from completed electronic design to manufacturing without repetitive procurement work.

The long-term goal is not merely to automate BOM formatting. It is to redefine the interface between electronic design and electronic manufacturing so that:

- engineering intent remains stable
- procurement policy remains replaceable
- provider integrations remain modular
- engineering knowledge accumulates over time
- engineers remain in control
