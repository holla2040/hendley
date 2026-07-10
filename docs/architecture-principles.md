# Architecture Principles

**Project:** Hendley — AI-Assisted BOM Resolver  
**Version:** 1.0  
**Status:** Architectural baseline

## 1. Purpose

This document defines the principles that constrain Hendley's architecture.

The Vision explains why the project exists. The PRD defines what the product must do. The System Architecture describes the modules and interfaces used to implement it. This document sits between them and establishes the rules that implementation choices must preserve.

## 2. Engineering Intent Is the Source of Truth

Engineering intent describes the electrical, mechanical, environmental, and explicit part constraints required for the design to function.

Examples include:

- nominal value
- tolerance
- package and footprint
- voltage, current, and power ratings
- dielectric or material
- temperature range
- polarity
- certifications
- mandatory manufacturer or exact MPN

Procurement conditions must never weaken a mandatory engineering constraint.

A part is not valid because it is inexpensive, available, historically preferred, or recommended by AI. It is valid only after all mandatory requirements pass.

## 3. Procurement Information Is Transient

Inventory, pricing, distributor availability, lifecycle state, provider classification, and provider-specific identifiers change independently of the circuit.

These facts belong to manufacturing resolution, not to the permanent definition of a generic component.

The architecture shall permit the same design to be resolved for different providers and at different times without changing its engineering intent.

## 4. Separate the Concerns

Hendley separates the following concerns:

```text
ECAD / Live Design
        |
        v
Requirements Capture and Normalization
        |
        v
Provider-Independent Requirements BOM
        |
        v
Deterministic Resolver Core
        |
        +--> Component Data Sources
        +--> Knowledge Base
        +--> Provider Strategy
        +--> Ranking
        +--> AI Explanation
        |
        v
Engineer Review and Approval
        |
        v
Provider Adapter
        |
        v
Manufacturing BOM and Reports
```

The boundaries are deliberate:

- Importers read source-specific design data.
- Normalization creates a canonical representation.
- The Resolver Core applies provider-independent resolution flow.
- Data Sources return sourced component facts.
- Provider Strategies express sourcing and manufacturing policy.
- Ranking orders candidates that have already passed hard validation.
- AI interprets and explains; it does not establish facts.
- The Knowledge Base preserves prior decisions.
- Provider Adapters format approved results.
- The engineer authorizes release.

A module should not absorb a neighboring responsibility merely because doing so is expedient.

## 5. Deterministic Validation Precedes Ranking

Mandatory filtering must be deterministic, testable, and independent of AI.

The resolution order is:

1. normalize the requirement
2. discover candidates
3. validate source data
4. reject candidates that violate hard constraints
5. apply provider eligibility rules
6. rank remaining candidates
7. generate explanations
8. request engineer approval

AI must not rescue a part that failed hard validation.

## 6. Ranking Is Policy, Not Truth

Several valid parts may satisfy the same requirement.

Ranking exists to reduce engineer effort by presenting the most useful candidates first. It may consider:

- fit to engineering preferences
- current stock for the planned quantity
- lifecycle status
- prior approval and successful use
- provider preference
- multi-source availability
- cost and minimum order quantity
- data quality

The score must be inspectable. A recommendation must be understandable without trusting an opaque model.

## 7. Provider Strategy and Provider Adapter Are Different

A **Provider Strategy** affects resolution. It defines the provider's search space, eligibility rules, stock policy, sourcing preferences, and ranking contributions.

A **Provider Adapter** operates after approval. It validates provider-required fields and converts approved results into the provider's expected file format.

A strategy answers:

> Which parts are appropriate for this manufacturing context?

An adapter answers:

> How must the approved selections be represented for this provider?

Adapters shall not select parts. The Resolver Core shall not format provider files.

## 8. The Resolver Core Is Provider-Independent

The Resolver Core must contain no hard-coded JLCPCB, LCSC, PCBWay, DigiKey, Mouser, or other provider behavior.

JLCPCB/LCSC is the first target because it is the immediate use case. PCBWay is an early second implementation that verifies the abstraction.

Adding a new provider should require a new strategy, adapter, and possibly data-source connector—not changes to the core resolution algorithm.

## 9. AI Is Advisory and Replaceable

AI may:

- interpret ambiguous text
- propose normalized attributes
- summarize candidate differences
- explain ranking factors
- identify likely missing constraints
- assist with exception review

AI shall not:

- fabricate specifications, stock, pricing, or lifecycle facts
- override deterministic constraints
- approve a component
- silently alter engineering intent
- hide uncertainty

The deterministic product must continue to function when the AI provider is unavailable. AI integration shall be replaceable and shall not bind the project to one model vendor.

## 10. Engineers Approve Released Selections

Hendley is a decision-support system.

Every released manufacturing selection must be attributable to an engineer. Bulk review may reduce repetitive interaction, but it still requires explicit confirmation and may only be offered when current validation has passed.

Unresolved or rejected lines must remain visible. They must not disappear from output.

## 11. History Informs; It Does Not Dictate

The Knowledge Base stores decisions and context, not merely a preferred-part lookup table.

Prior approval may improve ranking when current conditions remain valid. It does not bypass:

- current engineering validation
- provider eligibility
- inventory requirements
- lifecycle checks
- project-specific restrictions

The influence of historical knowledge must be visible in the recommendation.

## 12. Facts Require Provenance and Freshness

Component facts may come from provider APIs, distributor data, manufacturer data, local caches, or user-maintained records.

Where practical, each fact should carry:

- source
- retrieval time
- confidence or verification state
- freshness status

Unknown inventory is not zero inventory. Missing data is not proof of compliance. Stale data may be used for preliminary analysis only when clearly marked.

## 13. Local-First, Explicit External Use

Design and BOM data may be proprietary.

Project state and knowledge should remain local by default. The system must disclose and configure any transfer of project information to external AI or data services.

Credentials shall remain outside source control and be granted only the permissions required.

## 14. Existing Utilities Remain Separate from the Resolver Path

Hendley already supports explicit Fusion migration workflows, including generation and optional execution of `.scr` changes.

Those tools are useful, but they are not automatic consequences of BOM resolution.

Any write back to Fusion must be:

- initiated by the engineer
- represented as an explicit proposed change
- reviewable before execution
- independently verifiable afterward

The resolver's normal output is a manufacturing decision and Manufacturing BOM, not an unrequested design mutation.

## 15. Open Extension Through Stable Contracts

The architecture should support independently developed:

- ECAD importers
- data-source connectors
- Provider Strategies
- Provider Adapters
- knowledge-store backends
- report generators
- AI providers

Extension contracts should be versioned, testable, and narrower than internal implementation APIs.

The target is an open plugin ecosystem. The repository's legal license must be changed explicitly before it is represented as open source.

## 16. Architectural Invariants

Unless these principles are deliberately revised:

1. Engineering intent remains provider-independent.
2. Hard constraints are deterministic and precede ranking.
3. AI remains advisory.
4. Engineers approve released selections.
5. The Resolver Core contains no provider-specific policy.
6. Provider Strategies do not format output.
7. Provider Adapters do not select components.
8. Historical preference never overrides current eligibility.
9. Unknown or stale facts remain visible.
10. Manufacturing output is explainable and auditable.
11. Existing design-migration utilities remain outside the automatic resolver path.
12. New providers extend the system without modifying the Resolver Core.
