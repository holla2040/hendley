# Product Requirements Document

# AI-Assisted BOM Resolver

**Document:** `PRD.md`  
**Version:** 1.1 Draft  
**Status:** Product-definition baseline  
**Source:** Consolidated from the project design conversation and aligned with the current Hendley implementation  
**Primary audience:** Electrical engineers, software contributors, and maintainers

---

## 1. Executive Summary

Hendley is intended to become an open, extensible AI-Assisted BOM Resolver that transforms a requirements-based engineering Bill of Materials into a manufacturing-ready Bill of Materials. The repository currently remains under its stated proprietary license; changing that legal status is a separate project decision.

The project exists to solve a recurring problem in electronic design: engineers are routinely required to perform procurement work inside, or immediately after, the ECAD workflow. For generic components such as resistors, capacitors, inductors, and other commonly substitutable parts, engineers often spend hours searching catalogs, comparing stock, finding alternates, checking lifecycle information, and converting manufacturer or distributor part numbers into the identifiers required by a PCB assembly provider.

That work is necessary for manufacturing, but it is not circuit design.

The product therefore separates two concerns that are commonly coupled today:

1. **Engineering definition** — what electrical and mechanical characteristics the design requires.
2. **Manufacturing resolution** — which specific purchasable component should be used for a selected assembly provider at a particular point in time.

The system accepts a **Requirements BOM** produced from a live ECAD integration or imported from an exported BOM. Each line describes engineering intent, such as value, package, tolerance, voltage rating, power rating, footprint, and any mandatory manufacturer constraints. The resolver then searches appropriate data sources, filters incompatible parts, ranks valid candidates, explains the tradeoffs, and presents the results for engineer approval.

After approval, a provider-specific output layer generates a **Manufacturing BOM** suitable for the selected PCB assembly provider.

The first target use case is a Fusion Electronics design exported for assembly through JLCPCB using LCSC/JLC part numbers. The product must not, however, be limited to JLCPCB. PCBWay and other assembly providers must be supportable through extensible provider-specific modules.

The product's guiding objective is:

> **Free engineers to do design.**

AI assists with repetitive analysis. Engineers retain final authority.

---

## 2. Product Context

### 2.1 Current Workflow

In a conventional ECAD workflow, the designer commonly places a component in a schematic and associates it with one or more exact part numbers. Depending on the tool and organization, these may include:

- a manufacturer part number
- a distributor part number
- an internal company part number
- a PCB assembly provider's part number
- approved alternates
- sourcing notes

This information is frequently stored as schematic attributes so it will appear in the exported BOM.

For the primary user of this project, a typical design workflow has been:

1. Complete the schematic and PCB design.
2. Run the appropriate electrical and design-rule checks.
3. Export the BOM.
4. Search for acceptable parts.
5. determine whether the selected parts are in stock
6. find alternates when parts are unavailable
7. select parts that the board house can source
8. add the assembly provider's part numbers to the design or BOM
9. repeat until the BOM is accepted by the assembly provider

For a medium-sized design, this process can consume four to five hours even when the engineering design itself is complete.

### 2.2 Why the Existing Workflow Is Inefficient

The workflow mixes long-lived engineering information with short-lived procurement information.

Engineering information is comparatively stable:

- 22 kΩ
- 1% tolerance
- 0603 package
- minimum power rating
- required footprint
- voltage rating
- dielectric
- temperature requirements

Procurement information is transient:

- which manufacturer part is in stock today
- which distributor has sufficient quantity
- which part a particular board house can source
- current price breaks
- minimum order quantity
- lifecycle state
- provider-specific inventory classification
- provider-specific part identifier

A supply-chain change should not require redesigning or editing an otherwise correct schematic.

### 2.3 Why Existing Tools Do Not Fully Solve the Problem

Existing ECAD supply-chain features improve visibility into availability, pricing, lifecycle status, and alternates. They are valuable, but they generally begin after a specific manufacturer part or managed component has already been chosen.

This project addresses a different problem.

The goal is not merely to monitor a selected part. The goal is to delay selection of a specific purchasable part until the manufacturing-preparation stage whenever the component can be described by engineering requirements alone.

The resolver therefore sits between ECAD and manufacturing rather than becoming another ECAD library-management feature.

---

### 2.4 Current Hendley Baseline

Hendley is not starting from an empty repository. The current codebase already provides several building blocks for the target product:

- a Python implementation of JLCPCB component API access
- component detail, stock, pricing, parameter, library, and private-inventory queries
- BOM inventory checks
- alternate discovery followed by live JLC verification
- live Fusion Electronics reads over Fusion's local HTTP interface
- generation of explicit Fusion `.scr` migration scripts

These capabilities are useful independently and were preserved. Since this baseline was written, the rest of the product defined by this PRD has been implemented: the canonical Requirements BOM (`hendley.domain.model`), the deterministic multi-provider resolver (`hendley.resolver`), reusable approval knowledge (`hendley.knowledge`), the ranked review workflow (the app, ADR-0003/0004), and the provider-independent output architecture (`hendley.providers`, with PCBWay as the second provider).

Fusion write-back is considered an ancillary, engineer-initiated migration utility. It is not an automatic step in the BOM-resolution workflow.

---

## 3. Product Vision

The intended workflow is:

```text
Engineering Design
        |
        v
Engineering Intent
        |
        v
Requirements BOM
        |
        v
AI-Assisted BOM Resolver
        |
        +--> Provider Strategy
        |
        +--> Component Data Sources
        |
        +--> Reusable Knowledge Base
        |
        +--> Ranking and Explanation
        |
        v
Engineer Review and Approval
        |
        v
Provider Adapter
        |
        v
Manufacturing BOM
        |
        v
PCB Assembly Provider
```

The system does not replace ECAD. It does not replace engineering judgment. It does not autonomously redesign circuits.

It creates a dedicated product layer for turning engineering intent into approved manufacturing selections.

---

## 4. Product Principles

### 4.1 Separation of Concerns

The product must separate:

- engineering intent
- component resolution
- procurement policy
- provider-specific sourcing behavior
- provider-specific output formatting
- historical engineering knowledge

Each concern must be independently understandable and replaceable.

### 4.2 Engineering Intent Is the Source of Truth

The Requirements BOM describes what the design requires. Mandatory engineering constraints must never be weakened by availability, price, historical preference, or AI inference.

### 4.3 Procurement Data Is Transient

Inventory, price, lifecycle state, provider preference, and distributor availability change over time. They must not be treated as permanent attributes of the electrical design.

### 4.4 Human-in-the-Loop Approval

AI recommends. Engineers approve.

The system must not silently approve components or generate a final manufacturing release without explicit approval.

### 4.5 Explainability

Every recommendation must include a concise explanation of:

- why the candidate is compatible
- why it was ranked where it was
- what data sources were used
- what tradeoffs influenced the recommendation
- what assumptions or uncertainties remain

### 4.6 Reuse of Proven Components

Previously approved parts should receive preference when they still satisfy the requirements and remain suitable for the selected provider and production quantity.

Historical preference must improve efficiency without overriding engineering constraints.

### 4.7 Provider Independence

The resolver core must not be tied to JLCPCB, LCSC, PCBWay, DigiKey, Mouser, or any other provider.

Provider-specific behavior must be isolated behind defined extension points.

### 4.8 Open-Source Extensibility

Third parties must be able to add support for new ECAD tools, data sources, PCB assembly providers, and output formats without rewriting the resolver core.

---

## 5. Goals

The product shall:

1. Accept component requirements from a live ECAD integration or an exported BOM and normalize them into a Requirements BOM.
2. Preserve engineering intent independently of procurement information.
3. Resolve generic component requirements into purchasable candidate parts.
4. Support exact manufacturer part numbers when the design requires a specific component.
5. Filter out candidates that violate mandatory constraints.
6. Rank valid candidates using configurable criteria.
7. Consider current availability, required build quantity, lifecycle, cost, and prior usage.
8. Explain each recommendation.
9. Present a short, ordered list rather than an unfiltered catalog search.
10. Require explicit engineer approval.
11. Record approved and rejected decisions.
12. Reuse prior approvals in future projects.
13. Produce a provider-specific Manufacturing BOM.
14. Support JLCPCB/LCSC as the first complete provider implementation.
15. Support PCBWay as a second provider model.
16. Remain extensible to additional board houses and distributor-centered workflows.
17. Reduce post-design BOM-preparation time from hours to minutes for routine components.

---

## 6. Non-Goals

Version 1.0 shall not:

- silently or automatically modify schematic or PCB design files as part of BOM resolution
- replace ECAD software
- generate circuit designs
- change component values
- alter footprints
- perform PCB placement or routing
- automatically order parts
- replace ERP, PLM, MRP, or purchasing systems
- guarantee availability after the moment data was retrieved
- make autonomous engineering approvals
- perform unrestricted IC substitution without explicit engineering constraints
- infer safety-critical requirements without confirmation
- become a complete enterprise component-management system

---

## 7. Target Users

### 7.1 Primary User

The primary user is an electrical or hardware engineer who:

- completes a design in an ECAD tool
- understands the electrical requirements
- wants to avoid manually searching and resolving every generic component
- personally reviews final component selections
- submits a manufacturing BOM to a PCB assembly provider

### 7.2 Initial User Profile

The initial product is optimized for:

- independent engineers
- consultants
- small hardware teams
- engineers using Fusion Electronics
- engineers using JLCPCB/LCSC
- medium-sized PCB designs
- low- to moderate-volume builds

### 7.3 Secondary Users

Future or secondary users include:

- manufacturing engineers
- component engineers
- purchasing staff
- contract manufacturers
- enterprise hardware teams
- organizations maintaining approved vendor or approved component lists

---

## 8. Core Concepts and Terminology

### 8.1 Engineering Intent

Engineering intent is the set of electrical, mechanical, environmental, and explicit sourcing constraints required for the component to satisfy the design.

Examples include:

- component category
- nominal value
- tolerance
- package
- footprint
- voltage rating
- current rating
- power rating
- dielectric
- temperature range
- frequency characteristics
- polarity
- required certifications
- mandatory manufacturer
- mandatory manufacturer part number

### 8.2 Requirements BOM

A Requirements BOM is a provider-independent list of component requirements exported from ECAD or constructed from ECAD data.

It describes what is required, not what must be purchased.

### 8.3 Candidate Component

A Candidate Component is a purchasable manufacturer part that appears to satisfy the Requirements BOM line.

### 8.4 Resolved Component

A Resolved Component is a Candidate Component that has passed mandatory validation and is presented for approval.

### 8.5 Approved Component

An Approved Component is a Resolved Component explicitly accepted by the engineer for a specific project, provider context, and manufacturing release.

### 8.6 Manufacturing BOM

A Manufacturing BOM is a provider-specific output containing approved parts and the identifiers required by the assembly provider.

### 8.7 Provider Strategy

A Provider Strategy defines how component resolution should operate for a selected manufacturing or procurement context.

It determines:

- eligible data sources
- provider-specific sourcing constraints
- stock requirements
- ranking priorities
- provider-specific compatibility rules
- preferred component categories or inventories

### 8.8 Provider Adapter

A Provider Adapter transforms approved results into the file format and fields required by a PCB assembly provider.

A Provider Strategy influences what should be selected.

A Provider Adapter determines how the approved selection is delivered.

### 8.9 Knowledge Base

The Knowledge Base stores previous decisions and supporting context so future projects can reuse proven parts and avoid repeating the same analysis.

---

## 9. Supported Component Selection Modes

The product must support more than one form of component definition.

### 9.1 Requirements-Defined Components

Used when many manufacturer parts can satisfy the design.

Examples:

- resistors
- capacitors
- inductors
- common diodes
- LEDs
- generic transistors
- some connectors
- common protection components

Example:

```text
Category: Resistor
Value: 22 kΩ
Package: 0603
Tolerance: ±1%
Minimum power: 100 mW
```

### 9.2 Manufacturer-Constrained Components

Used when the manufacturer is required but multiple orderable variants or provider identifiers may exist.

Example:

```text
Manufacturer: Example Semiconductor
Device family: XYZ123
Package: QFN-32
Temperature grade: Industrial
```

### 9.3 Exact-Part Components

Used when the circuit requires an exact manufacturer part number.

Examples:

- microcontrollers
- FPGAs
- specialized analog ICs
- calibrated sensors
- regulatory-approved modules
- parts with firmware or programming dependencies

The resolver may still identify sourcing options and provider identifiers, but it must not substitute another device unless explicitly instructed.

---

## 10. Primary User Workflow

### 10.1 Design Phase

1. The engineer creates the schematic and PCB in an ECAD tool.
2. Components are described using engineering attributes.
3. Exact manufacturer part numbers are included only when electrically or programmatically required.
4. Generic parts remain requirements-defined.
5. The engineer completes ERC, DRC, and other design validation.

### 10.2 Ingestion Phase

1. The engineer allows Hendley to read the live design or supplies an exported BOM or component dataset.
2. The ECAD integration maps source attributes into the canonical Requirements BOM.
3. The system reports missing, malformed, or ambiguous attributes.
4. The engineer corrects blocking issues before resolution proceeds.

### 10.3 Resolution Phase

1. The engineer selects a Provider Strategy.
2. The system loads the project quantity and provider context.
3. The system retrieves candidate components.
4. Mandatory engineering constraints are applied.
5. Provider-specific eligibility rules are applied.
6. Valid candidates are ranked.
7. Prior approvals and project history influence ranking.
8. AI generates explanations and identifies exceptions.

### 10.4 Review Phase

1. The engineer reviews the top recommendation for each line.
2. Previously approved, low-risk matches may be grouped for efficient review.
3. Exceptions receive prominent attention.
4. The engineer may approve, reject, override, or defer each selection.
5. Rejection reasons may be recorded.
6. Approved decisions are saved to the Knowledge Base.

### 10.5 Output Phase

1. The Provider Adapter validates required output fields.
2. The system generates the Manufacturing BOM.
3. The system generates supporting reports.
4. The engineer submits the BOM to the assembly provider.
5. The project retains an auditable record of what was approved and why.

---

## 11. Provider Models

### 11.1 JLCPCB/LCSC Provider Model

JLCPCB is the first target implementation because the assembly workflow depends heavily on LCSC/JLC-specific part identifiers and available inventory.

The JLCPCB/LCSC Provider Strategy shall be capable of:

- searching or consuming LCSC/JLC component data
- considering available quantity for the planned board build
- identifying provider-specific part numbers
- preferring previously approved components when still suitable
- distinguishing ordinary availability from provider-specific assembly eligibility
- applying configured preferences such as stock level, cost, reuse, and provider classification
- reporting when no acceptable provider-specific part is available

The JLCPCB Provider Adapter shall generate the fields and format required for submission to JLCPCB.

The objective is to remove the need for the engineer to manually enter LCSC/JLC part numbers into Fusion Electronics merely so they appear in the exported BOM.

### 11.2 PCBWay Provider Model

PCBWay represents a different sourcing workflow and is included to prove that provider behavior is not hard-coded around JLCPCB.

The PCBWay Provider Strategy may:

- prioritize manufacturer part numbers
- consider multiple distributor sources
- represent provider-supported sourcing preferences
- preserve alternates
- generate sourcing notes where provider confirmation is required

The PCBWay Provider Adapter shall produce a PCBWay-compatible Manufacturing BOM without changing the Requirements BOM or resolver core.

### 11.3 Future Provider Models

Future providers may include:

- distributor-centric strategies
- internal approved-component strategies
- internal inventory strategies
- contract manufacturer strategies
- regional sourcing strategies
- organization-specific procurement policies

---

## 12. Functional Requirements

### 12.1 BOM Import

The system shall:

- read component data from a live Fusion Electronics design
- import Fusion Electronics BOM data when export is preferred
- import generic CSV files
- preserve reference designators
- preserve quantities
- preserve user-defined attributes
- support grouped reference designators
- report unknown columns
- allow explicit field mapping
- normalize imported records into a Requirements BOM
- preserve the original source data for audit purposes

Future importers should be addable without changing the resolver core.

### 12.2 Requirements Validation

The system shall validate:

- presence of required fields
- valid numeric values
- valid units
- recognized package names
- recognized component categories
- footprint/package compatibility information
- contradictory constraints
- malformed tolerances
- incomplete exact-part definitions
- unsupported component classes

Validation results shall distinguish:

- blocking errors
- warnings
- informational notices

### 12.3 Requirements Normalization

The system shall normalize:

- unit prefixes
- resistance, capacitance, and inductance notation
- tolerance representation
- voltage representation
- power representation
- package aliases
- manufacturer aliases
- temperature grades
- reference-designator grouping

The original value and normalized value shall both remain available for review.

### 12.4 Candidate Discovery

The system shall:

- query one or more configured component data sources
- identify candidate manufacturer parts
- preserve source provenance
- preserve data retrieval time
- retrieve availability and pricing where supported
- retrieve provider-specific identifiers where supported
- retrieve lifecycle status where supported
- support cached data
- indicate stale or incomplete data

### 12.5 Mandatory Filtering

The system shall reject any candidate that violates a mandatory constraint.

Mandatory filtering must be deterministic and must occur before AI ranking or explanation.

Examples include:

- wrong value
- insufficient voltage rating
- insufficient power rating
- incompatible package
- incompatible footprint
- wrong polarity
- required manufacturer mismatch
- required MPN mismatch
- unsupported temperature rating
- provider-ineligible part

### 12.6 Candidate Ranking

The system shall support configurable ranking criteria including:

- engineering match quality
- provider eligibility
- required build quantity
- available inventory
- previous approval
- previous project usage
- organizational preference
- lifecycle status
- multi-source availability
- cost
- minimum order quantity
- provider-specific cost or handling implications
- data quality and confidence

The system shall not treat lowest unit price as the universal primary criterion.

### 12.7 Recommendation Explanation

For each recommended candidate, the system shall explain:

- which mandatory requirements were satisfied
- which preferences were satisfied
- historical usage
- available quantity
- lifecycle condition
- price considerations
- provider-specific advantages or disadvantages
- why it outranked the next-best candidate
- any missing or uncertain information

### 12.8 Engineer Review

The review interface shall allow the engineer to:

- view the requirement
- view ranked candidates
- view source data
- view provider identifiers
- compare candidates
- approve a candidate
- reject a candidate
- record rejection rationale
- select a lower-ranked candidate
- manually enter an exact part
- defer a decision
- mark a requirement as unresolved
- rerun resolution after changing criteria

### 12.9 Bulk Review

The system should allow efficient review of repeated or previously approved components.

Bulk approval may be offered only when:

- mandatory constraints match
- the same previously approved part is recommended
- provider eligibility is confirmed
- required inventory is sufficient
- no new warning is present

The engineer must still explicitly confirm the bulk action.

### 12.10 Knowledge Capture

The system shall record:

- approved part
- rejected candidates
- decision rationale
- project
- requirement signature
- provider strategy
- provider identifier
- source data timestamp
- approving user
- approval time
- manual overrides
- relevant warnings

### 12.11 Knowledge Reuse

When resolving a new BOM, the system shall identify prior decisions that match the requirement.

A previously approved part should receive favorable ranking when:

- all mandatory constraints still pass
- the provider can source it
- sufficient inventory exists
- lifecycle status remains acceptable
- no project-specific restriction excludes it

Prior approval shall never bypass current validation.

### 12.12 Provider Strategy Selection

The engineer shall be able to select and configure a Provider Strategy before resolution.

The selected strategy shall be recorded with the project and output.

### 12.13 Provider Output

The system shall generate:

- a provider-specific Manufacturing BOM
- a generic Manufacturing BOM
- a resolution report
- an exception report
- an alternate-parts report
- an approval record

### 12.14 Exception Handling

The system shall isolate and clearly present:

- no valid candidates
- insufficient inventory
- conflicting requirements
- missing attributes
- stale supplier data
- discontinued parts
- ambiguous footprint/package relationships
- low-confidence AI interpretation
- provider-specific incompatibility
- unavailable provider part number

Unresolved exceptions shall not be silently omitted from output.

### 12.15 Re-Resolution

The system shall support rerunning resolution when:

- provider changes
- build quantity changes
- inventory changes
- a requirement changes
- a candidate is rejected
- ranking policy changes
- a previous approval becomes invalid

The Requirements BOM must remain unchanged when only procurement conditions change.

---

## 13. AI Requirements

### 13.1 Appropriate AI Uses

AI may be used to:

- interpret nonstandard component descriptions
- map ambiguous attributes to normalized fields
- summarize candidate differences
- explain ranking results
- identify unusual selections
- identify likely missing constraints
- suggest follow-up questions
- assist the engineer during exception review
- summarize the final resolution state

### 13.2 Prohibited AI Behavior

AI shall not:

- invent inventory
- invent pricing
- invent manufacturer specifications
- claim datasheet compliance without evidence
- override hard constraints
- approve components
- alter engineering values without confirmation
- hide uncertainty
- silently infer safety-critical requirements

### 13.3 AI Confidence and Provenance

AI-generated output shall be distinguishable from deterministic validation and supplier data.

Where applicable, AI output shall include:

- confidence level
- assumptions
- referenced source fields
- unresolved ambiguity

### 13.4 AI Independence

The product should not depend on a single AI provider.

AI integration must be replaceable and optional for deterministic core functions.

---

## 14. Knowledge Base Requirements

### 14.1 Purpose

The Knowledge Base captures institutional and personal engineering knowledge so each project improves future resolution.

### 14.2 Stored Knowledge

The Knowledge Base may contain:

- approved manufacturer parts
- provider-specific part identifiers
- rejected parts
- preferred substitutions
- project usage history
- engineer comments
- preferred manufacturers
- preferred passive series
- known assembly issues
- historical shortages
- lifecycle events
- provider-specific suitability
- evidence of successful production use

### 14.3 Knowledge Scopes

The product should support:

1. project-local knowledge
2. user-level knowledge
3. organization-level knowledge

Version 1.0 may implement project-local and user-level knowledge first.

### 14.4 Precedence

Mandatory engineering constraints take precedence over all knowledge.

Project-specific restrictions take precedence over user preferences.

Current provider eligibility and inventory take precedence over historical convenience.

### 14.5 Transparency

Historical influence on a ranking must be visible.

Example:

```text
Previously approved on three projects.
Last used successfully for JLCPCB assembly.
Current stock is sufficient for this build.
No lifecycle warning is present.
```

---

## 15. Non-Functional Requirements

### 15.1 Modularity

The product shall use clear module boundaries for:

- importers
- normalization
- resolver core
- data sources
- ranking
- AI assistance
- knowledge storage
- provider strategies
- provider adapters
- reporting

### 15.2 Extensibility

New provider support must not require modifying core resolution logic.

### 15.3 Local-First Operation

The system should support local project storage and local knowledge storage.

Cloud services may be used for data retrieval or AI, but the product must clearly disclose when project information leaves the local system.

### 15.4 Performance

A medium-sized BOM should resolve quickly enough to support interactive engineering review.

The target is seconds to a few minutes depending on external data-source latency, not hours.

### 15.5 Reliability

Failure to resolve one BOM line shall not prevent unrelated lines from being processed.

### 15.6 Determinism

Hard filtering and base ranking shall be deterministic for identical inputs, configuration, and data snapshots.

### 15.7 Auditability

The product shall retain enough information to determine:

- what requirements were imported
- what data was used
- which strategy was active
- how candidates were ranked
- what the engineer approved
- what output was generated

### 15.8 Data Freshness

Supplier and provider data shall include retrieval timestamps where available.

The system shall warn when critical availability information may be stale.

### 15.9 Security

Credentials for suppliers, providers, and AI services shall not be stored in source-controlled project files.

### 15.10 Usability

The product shall minimize the number of decisions that require engineer attention.

Routine, high-confidence, previously approved parts should be easy to review.

Exceptions and risks should be prominent.

---

## 16. System Boundaries

The product is responsible for:

- importing component requirements
- normalizing engineering attributes
- discovering candidate parts
- applying mandatory constraints
- applying provider policy
- ranking valid candidates
- explaining recommendations
- recording engineer decisions
- generating manufacturing outputs

The product is not responsible for:

- determining whether the circuit design is electrically correct
- editing the schematic
- editing the PCB
- approving parts without an engineer
- placing purchase orders
- managing warehouse inventory
- replacing enterprise ERP or PLM systems
- guaranteeing that provider inventory remains available after export

---

## 17. Version 1.0 Scope

Version 1.0 shall prioritize:

- live Fusion Electronics ingestion
- Fusion Electronics or generic CSV import
- passive component resolution
- exact-part handling for constrained components
- JLCPCB/LCSC Provider Strategy
- JLCPCB/LCSC Provider Adapter
- PCBWay Provider Strategy
- PCBWay Provider Adapter
- local Knowledge Base
- deterministic filtering and ranking
- AI-assisted explanation
- engineer approval workflow
- generic and provider-specific Manufacturing BOM generation
- exception and audit reporting

Complex functional substitution of ICs is outside the initial scope unless exact requirements are explicitly provided.

---

## 18. Success Criteria

The product will be considered successful when it demonstrates all of the following:

1. A Fusion Electronics BOM can be converted into a normalized Requirements BOM.
2. Generic passive components can be resolved without embedding provider part numbers in the schematic.
3. The same Requirements BOM can be processed for JLCPCB and PCBWay without changing engineering intent.
4. Provider-specific outputs can be generated through separate adapters.
5. Previously approved parts are reused when still suitable.
6. Engineer approval is required before final output.
7. Every recommendation includes a usable explanation.
8. Unresolved components are clearly reported.
9. The resolver core contains no JLCPCB- or PCBWay-specific selection logic.
10. Routine BOM preparation time is reduced from approximately four to five hours to a review process measured in minutes.

---

## 19. Acceptance Criteria

A Version 1.0 release shall pass the following product-level acceptance tests.

### 19.1 Requirements Import

Given a supported Fusion Electronics or CSV BOM, the system produces a valid Requirements BOM while preserving reference designators, quantity, engineering attributes, and source data.

### 19.2 Requirements Validation

Given malformed, missing, or contradictory attributes, the system reports actionable errors and does not silently infer blocking requirements.

### 19.3 Passive Resolution

Given a valid passive requirement, the system returns only candidates that satisfy mandatory constraints.

### 19.4 Exact-Part Handling

Given an exact manufacturer part number, the system does not substitute another functional part unless explicitly authorized.

### 19.5 Provider Independence

Given the same Requirements BOM and two different Provider Strategies, the system may produce different approved candidates and outputs without modifying the Requirements BOM.

### 19.6 JLCPCB Output

Given approved selections under the JLCPCB/LCSC strategy, the adapter produces an output containing the provider identifiers required for the JLCPCB workflow.

### 19.7 PCBWay Output

Given approved selections under the PCBWay strategy, the adapter produces a PCBWay-compatible output without changing resolver-core behavior.

### 19.8 Historical Reuse

Given a requirement matching a previously approved part, the system identifies the history and ranks the prior part favorably when it remains valid.

### 19.9 Human Approval

The system does not generate a final released Manufacturing BOM while required items remain unapproved.

### 19.10 Explainability

For every recommended candidate, the system displays the primary ranking factors, data sources, and known uncertainties.

### 19.11 Exception Safety

Given a BOM with unresolved lines, the system reports those lines and does not silently remove them from the output.

### 19.12 Reproducibility

Given the same Requirements BOM, configuration, provider strategy, and preserved data snapshot, deterministic filtering and ranking produce the same result.

---

## 20. Risks and Mitigations

### 20.1 Incomplete Supplier Data

**Risk:** Distributor or provider data may omit important specifications.

**Mitigation:** Preserve provenance, display missing data, and prevent unsupported assumptions from becoming silent approvals.

### 20.2 Changing APIs and Websites

**Risk:** Provider data interfaces may change.

**Mitigation:** Isolate data-source connectors and version provider modules independently.

### 20.3 Ambiguous Engineering Requirements

**Risk:** A BOM line may not contain enough information to select safely.

**Mitigation:** Flag missing requirements and require engineer clarification.

### 20.4 AI Hallucination

**Risk:** AI may produce convincing but unsupported claims.

**Mitigation:** Keep validation deterministic, require evidence, expose uncertainty, and require human approval.

### 20.5 Overfitting to JLCPCB

**Risk:** The first implementation may accidentally embed JLCPCB assumptions into the core.

**Mitigation:** Implement PCBWay as a second provider early and enforce strategy/adapter separation.

### 20.6 Excessive Automation

**Risk:** Engineers may distrust the system or miss important decisions.

**Mitigation:** Prioritize explainability, exception-focused review, and explicit approval.

### 20.7 Stale Availability

**Risk:** Stock may change between resolution and order submission.

**Mitigation:** Timestamp data and support refresh immediately before final export.

### 20.8 Poor Historical Decisions

**Risk:** A previously approved part may not be appropriate for a new project.

**Mitigation:** Treat history as a ranking preference, never as eligibility proof.

---

## 21. Open Questions

Questions open when this PRD was written; several have since been resolved — the Requirements BOM schema (`hendley.domain.model`, versioned), provider data retrieval/caching (`hendley.datasources` / `hendley.providers`), the AI/deterministic split (ADR-0005/0006), and manual-alternate representation (the ranked AVL, ADR-0006). `docs/architecture.md` §14 tracks what remains. The original list:

- What canonical schema will represent the Requirements BOM?
- Which Fusion Electronics export or API path will be used first?
- How will provider data be retrieved and cached?
- What ranking configuration should be user-editable?
- How will component categories define required and optional attributes?
- How will footprint compatibility be represented?
- How will project, user, and organization knowledge be merged?
- What data must be stored to reproduce a prior resolution?
- Which portions of the system operate without AI?
- What plugin packaging and discovery mechanism will be used?
- What open-source license will govern the project, and when will the repository transition from its current proprietary status?
- What test datasets can be distributed publicly?
- How will provider modules communicate data-quality limitations?
- How should manually specified alternates be represented?

These are implementation and architecture decisions. They do not change the product intent defined in this PRD.

---

## 22. Future Enhancements

Potential future capabilities include:

- additional ECAD importers
- organization-wide knowledge sharing
- PLM integration
- ERP integration
- internal inventory awareness
- lifecycle monitoring
- shortage alerts
- supplier risk analysis
- policy-based auto-approval for narrowly defined low-risk cases
- compliance and certification checks
- automated datasheet extraction
- collaborative engineering review
- manufacturing feedback capture
- approved-component library generation
- cost and lead-time scenario comparison
- procurement planning across multiple builds
- enterprise authentication and access control

These features shall not compromise the core separation between engineering intent and procurement resolution.

---

## 23. Document Relationship

This PRD defines what the product must do and why.

Related project documents should have the following roles:

- `vision.md` — project purpose and long-term direction
- `architecture-principles.md` — architectural rules and boundaries
- `PRD.md` — product behavior, scope, workflows, and acceptance criteria
- `architecture.md` — modules, interfaces, data models, and implementation structure
- architecture decision records — specific implementation decisions and their rationale

When these documents conflict, the conflict must be resolved explicitly rather than silently implemented.

---

## 24. Final Product Statement

The AI-Assisted BOM Resolver is intended to remove repetitive procurement work from the engineering-design workflow without removing the engineer from the decision process.

The product captures requirements instead of prematurely fixing procurement choices. It resolves those requirements using current provider data, reusable engineering knowledge, deterministic validation, configurable ranking, and AI-assisted explanation.

The result is a provider-specific Manufacturing BOM produced through a fast, reviewable, and auditable process.

The product succeeds when an engineer can complete a design, export a Requirements BOM, review a short set of intelligent recommendations, approve the results, and submit a manufacturing-ready BOM without spending hours manually searching catalogs and rewriting part-number fields.

> **Free engineers to do design.**
