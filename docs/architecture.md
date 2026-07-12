# System Architecture

# Hendley — AI-Assisted BOM Resolver

**Version:** 1.0 Draft  
**Status:** Target architecture aligned with `PRD.md`  
**Related Documents:**

- `vision.md`
- `architecture-principles.md`
- `PRD.md`

## 1. Purpose

This document defines the target system architecture for Hendley.

It distinguishes between:

1. the useful capabilities already present in the repository
2. the provider-independent resolver described by the PRD
3. ancillary tools that may read from or explicitly write to Fusion but are not part of automatic BOM resolution

The architecture is deliberately modular so the current JLC/Fusion implementation can evolve into the target product without a monolithic rewrite.

## 2. Current Implementation Baseline

The current Hendley repository already contains or documents:

- Python JLCPCB API authentication and request handling
- component detail, library, private inventory, stock, and pricing retrieval
- BOM inventory checking
- alternate discovery using a parametric index followed by live JLC verification
- a command-line interface
- Fusion Electronics reads over its local HTTP interface
- generation of Fusion `.scr` migration scripts
- optional, engineer-initiated execution of those scripts through Fusion's command channel

These components should be treated as existing adapters and services that can be incorporated behind the target interfaces.

The current alternate workflow intentionally does not rank or approve parts. The target architecture adds normalized requirements, hard filtering, ranking, explanation, review, approval history, and provider-specific Manufacturing BOM output.

## 3. Architectural Goals

The architecture shall:

- keep engineering intent independent of procurement data
- keep provider-specific policy out of the Resolver Core
- support live ECAD ingestion and file import
- preserve existing JLCPCB and Fusion capabilities
- separate candidate facts from ranking policy
- apply hard constraints deterministically
- make recommendations explainable and auditable
- keep AI advisory and replaceable
- require explicit engineer approval
- preserve approved and rejected decisions for reuse
- support local-first operation
- allow new providers and ECAD tools through stable extension contracts

## 4. System Context

```text
+--------------------------+
| ECAD / Source Design     |
| Fusion live read, CSV... |
+------------+-------------+
             |
             v
+--------------------------+
| Ingestion Adapter        |
+------------+-------------+
             |
             v
+--------------------------+
| Requirements Normalizer  |
| + Validator              |
+------------+-------------+
             |
             v
+--------------------------+
| Canonical Requirements   |
| BOM                      |
+------------+-------------+
             |
             v
+--------------------------------------------------+
| Resolver Orchestrator                            |
|                                                  |
|  +----------------+  +------------------------+  |
|  | Hard Constraint|  | Provider Strategy      |  |
|  | Engine         |  | Eligibility + Policy   |  |
|  +-------+--------+  +------------+-----------+  |
|          |                        |              |
|          +------------+-----------+              |
|                       v                          |
|  +----------------+  +------------------------+  |
|  | Knowledge Base |  | Data Source Connectors |  |
|  +-------+--------+  +------------+-----------+  |
|          |                        |              |
|          +------------+-----------+              |
|                       v                          |
|              +----------------+                  |
|              | Ranking Engine |                  |
|              +-------+--------+                  |
|                      v                           |
|              +----------------+                  |
|              | AI Explanation |                 |
|              | (optional)      |                 |
|              +-------+--------+                  |
+----------------------|---------------------------+
                       v
              +------------------+
              | Review & Approval|
              +---------+--------+
                        v
              +------------------+
              | Provider Adapter |
              +---------+--------+
                        v
              +------------------+
              | Manufacturing BOM|
              | + Reports        |
              +------------------+
```

Ancillary Fusion migration tooling is a separate path:

```text
Approved explicit design change
        |
        v
Migration Plan / swaps.json
        |
        v
Fusion Script Generator
        |
        v
Engineer Review
        |
        v
Manual or Explicit Execution
        |
        v
Read-Back Verification
```

A BOM selection shall not automatically enter this path.

## 5. Architectural Components

### 5.1 ECAD Ingestion Adapters

An ingestion adapter reads source-specific design information and produces raw component records.

Initial adapters:

- live Fusion Electronics reader over the existing local HTTP interface
- Fusion BOM or parts-file importer
- generic CSV importer

Future adapters may support KiCad, Altium, OrCAD, and other sources.

Responsibilities:

- preserve reference designators and quantities
- preserve source attributes and original text
- identify exact MPN constraints
- identify grouped components
- expose source provenance
- report unavailable or ambiguous source fields

An ingestion adapter shall not select components or apply provider policy.

### 5.2 Requirements Normalizer and Validator

The normalizer creates the canonical Requirements BOM.

Responsibilities:

- normalize units and numeric notation
- normalize packages, footprints, tolerances, and manufacturer aliases
- classify component category
- distinguish mandatory constraints from preferences
- preserve original values beside normalized values
- detect malformed or conflicting requirements
- assign stable requirement identifiers

Validation results are categorized as:

- blocking error
- warning
- informational notice

### 5.3 Canonical Requirements BOM

The Requirements BOM is the stable boundary between ECAD-specific ingestion and provider-independent resolution.

A requirement item should represent:

```yaml
requirement_id:
reference_designators:
quantity:
category:
mandatory:
  value:
  package:
  footprint:
  tolerance:
  voltage_rating:
  current_rating:
  power_rating:
  temperature_range:
  dielectric:
  polarity:
  manufacturer:
  manufacturer_part_number:
preferred:
  manufacturers:
  part_families:
  attributes:
source:
  adapter:
  design_id:
  original_record:
notes:
```

The schema is now defined in `hendley.domain.model` (`RequirementsBom` /
`RequirementLine` / `SpecKey`) and versioned via `requirementsBomVersion`
(currently 1), enforced on read.

### 5.4 Component Data Source Connectors

Data Source Connectors return component facts.

Initial sources include:

- JLCPCB/LCSC live component API
- the existing alternate-discovery index, used only for discovery
- local component cache
- user-maintained knowledge records

Future sources may include distributor and manufacturer services.

Responsibilities:

- discover candidates
- retrieve manufacturer identity and MPN
- retrieve electrical and mechanical attributes
- retrieve provider identifiers
- retrieve inventory, price, lifecycle, and assembly classification
- attach provenance and retrieval time
- distinguish verified live facts from discovery-index data

Discovery data must not be presented as live authoritative inventory. Current JLC verification behavior should be preserved.

### 5.5 Hard Constraint Engine

The Hard Constraint Engine deterministically rejects incompatible candidates.

Examples:

- wrong nominal value
- tolerance outside requirement
- insufficient voltage, current, or power rating
- incompatible package or footprint
- polarity mismatch
- mandatory manufacturer or MPN mismatch
- unsupported temperature range
- provider ineligibility

Hard filtering occurs before ranking and does not depend on AI.

### 5.6 Provider Strategy

A Provider Strategy supplies manufacturing-context policy.

Interface responsibilities:

- identify eligible Data Source Connectors
- build provider-specific candidate queries
- determine provider eligibility
- define stock thresholds
- contribute ranking factors and weights
- describe provider-specific warnings

The strategy returns policy results; it does not format the final BOM.

#### JLCPCB/LCSC Strategy

Uses JLC/LCSC component data and may consider:

- assembly eligibility
- Basic/Extended classification when relevant
- available quantity for the planned build
- JLC/LCSC provider identifiers
- provider-specific cost implications
- previously approved JLC parts

#### PCBWay Strategy

Represents a broader manufacturer/distributor sourcing workflow and may consider:

- manufacturer part numbers
- multiple supported inventory sources
- provider sourcing notes
- approved alternates
- provider confirmation requirements

Implementing both early is an architectural test against JLC-specific coupling.

### 5.7 Ranking Engine

The Ranking Engine orders candidates that have passed hard validation and provider eligibility.

Potential score contributions:

- exact match to preferred attributes
- sufficient inventory margin
- lifecycle quality
- prior engineer approval
- successful project history
- multi-source availability
- provider preference
- cost and MOQ
- data confidence

The ranking result must be decomposable into visible score contributions.

Example:

```text
Mandatory constraints passed
Prior successful use                 +20
Sufficient JLC stock                 +20
Preferred provider classification    +10
Multi-source availability            +10
Higher unit cost                      -3
```

The ranking engine should be deterministic for identical input data and configuration.

### 5.8 Knowledge Store

The Knowledge Store records decisions and context.

Records may include:

- requirement signature
- selected candidate
- rejected candidates
- reason and engineer comments
- project and provider context
- data snapshot or references
- approval identity and time
- production-use evidence
- superseded decisions

Initial scopes:

- project-local
- user-local

Organization-wide sharing is future work.

Knowledge can influence ranking only after current hard validation and provider eligibility pass.

### 5.9 AI Assistance

AI is optional and operates on structured resolver results.

Appropriate functions:

- interpret ambiguous source text
- propose normalized fields for confirmation
- summarize candidate differences
- explain ranking
- identify unusual or missing constraints
- assist with exceptions

The AI layer must:

- identify assumptions
- distinguish sourced facts from interpretation
- expose uncertainty
- use structured output where possible
- fail without blocking deterministic resolution

### 5.10 Review and Approval

The review layer presents:

- normalized requirement
- ranked candidates
- hard-validation status
- source provenance and freshness
- stock and lifecycle data
- prior usage
- score explanation
- AI summary
- warnings and exceptions

Engineer actions:

- approve
- reject and record a reason
- choose another valid candidate
- manually specify an exact part
- defer
- change ranking preferences and rerun
- explicitly confirm a permitted bulk approval

The approval state is persisted and gates final release.

### 5.11 Provider Adapter

The Provider Adapter receives approved results.

Responsibilities:

- validate required provider fields
- map internal fields to provider columns
- include provider-specific identifiers
- produce upload-ready files
- produce adapter-specific warnings
- include adapter version in the audit record

Adapters do not discover, filter, or rank components.

### 5.12 Reporting and Audit

Outputs include:

- provider-specific Manufacturing BOM
- generic Manufacturing BOM
- alternate-parts report
- exception report
- resolution and ranking report
- approval record
- provenance and freshness report

A release should record:

- Requirements BOM version
- selected Provider Strategy and version
- ranking configuration
- data retrieval times
- approved candidates
- unresolved exceptions
- approving engineer
- Provider Adapter and version

## 6. Core Domain Objects

### RequirementItem

A normalized provider-independent statement of engineering intent.

### CandidateComponent

A manufacturer part assembled from one or more sourced records.

### SourceRecord

A fact set from a named source with retrieval time and verification state.

### EligibilityResult

The deterministic result of hard and provider-specific validation.

### ScoreContribution

A named ranking contribution with value and rationale.

### ResolutionResult

The ranked candidates, warnings, exceptions, explanation, and approval state for one requirement.

### KnowledgeRecord

A prior approval, rejection, or production observation with scope and provenance.

### ManufacturingSelection

An engineer-approved candidate in a particular provider and project context.

## 7. Extension Contracts

The target extension points are conceptual until their schemas are finalized.

```text
IngestionAdapter.read(source_context) -> RawComponentRecords

RequirementsNormalizer.normalize(records) -> RequirementsBOM

DataSource.search(requirement, query_context) -> SourceRecords

ProviderStrategy.query_context(requirement, project) -> QueryContext
ProviderStrategy.evaluate(candidate, requirement, project) -> ProviderEligibility
ProviderStrategy.score(candidate, requirement, project) -> ScoreContributions

KnowledgeStore.find(requirement, project) -> KnowledgeRecords
KnowledgeStore.record(decision) -> KnowledgeRecord

AIProvider.analyze(resolution_context) -> AIAnalysis

ProviderAdapter.validate(selections) -> ValidationResult
ProviderAdapter.export(selections, configuration) -> OutputArtifacts
```

Persisted and plugin-facing contracts should use versioned schemas. Internal Python interfaces may evolve more freely.

The implemented names differ in places from the conceptual sketch above:
`RequirementsNormalizer.normalize` → `requirements_from_design()`
(`hendley.requirements.normalizer`); `DataSource.search` → `verify()` +
`discover()` (`hendley.datasources.base`); `KnowledgeStore.find` →
`lookup()` (`hendley.knowledge.base`); `AIProvider.analyze` →
`Interpreter.interpret_part` (`hendley.ai.interpreter`, ADR-0005);
`SourceRecord` → `PartFact`. `ProviderStrategy` and `ProviderAdapter`
(`hendley.providers.base`) match the sketch closely.

## 8. Persistence and Caching

The implementation shall separate:

- project state
- user knowledge
- provider/component cache
- audit records
- credentials

Local structured data uses SQLite — the recorded decision (ADR-0002), implemented in `hendley.knowledge.partsdb`.

Caching rules:

- engineering metadata may use a longer lifetime
- inventory and provider eligibility require shorter freshness windows
- final export should support a refresh of critical provider facts
- offline results must display staleness
- authoritative and discovery-only records must remain distinguishable

## 9. Error Handling

Errors are categorized as:

- ingestion error
- normalization error
- missing or conflicting requirement
- data-source failure
- stale or incomplete data
- hard-constraint rejection
- provider ineligibility
- ranking warning
- AI failure
- output validation failure

Safe behavior:

- failure on one line does not discard unrelated results
- unknown data is not converted into a false value
- AI failure leaves deterministic results usable
- unresolved items remain explicit
- no error path automatically approves a selection

## 10. Security and Privacy

- JLC and other credentials remain outside source control.
- External AI use requires explicit configuration.
- The system should minimize project data sent externally.
- Logs must not expose credentials or secrets.
- Provider access should use least privilege.
- Existing `.keys` behavior may be preserved while credential handling is abstracted for additional providers.

## 11. Deployment

Version 1 should remain usable as a local Python application.

Expected surfaces:

- command-line interface for automation and testing
- local review interface or generated review artifact
- local project and knowledge storage
- provider/data-source connectors
- import/export files

A richer desktop or local web UI is possible, but the specific UI framework is not yet decided.

## 12. Testing

### Unit Tests

- normalization and unit conversion
- hard constraints
- provider eligibility
- score contributions
- knowledge precedence
- adapter formatting

### Contract Tests

- ingestion adapters
- data sources
- Provider Strategies
- Provider Adapters
- AI structured output

### Integration Tests

- live or fixture Fusion data to Requirements BOM
- Requirements BOM to JLC candidates
- Requirements BOM to PCBWay candidates
- approval to provider-specific BOM
- knowledge reuse across projects

### Regression Tests

- known BOM fixtures
- ranking stability for preserved data snapshots
- provider output snapshots
- current JLC authentication and response handling
- discovery followed by authoritative JLC verification

### AI Tests

- unsupported claims are rejected
- missing data remains visible
- structured output validates
- AI outage does not block deterministic workflow

## 13. Target Repository Boundaries

A possible target structure is:

```text
src/hendley/
├── cli/
├── app/
├── domain/
├── ingestion/
│   ├── fusion/
│   └── csv/        (future)
├── requirements/
├── resolver/
│   ├── constraints/
│   ├── ranking/
│   └── orchestration/
├── datasources/
│   └── jlc/
├── providers/
│   ├── jlcpcb/
│   └── pcbway/
├── knowledge/
├── ai/
├── reporting/
└── migration/
    └── fusion_script/
```

This is a direction, not a mandate. It should be adapted to the current repository rather than imposed through a wholesale rewrite.

## 14. Decisions Still Required

Decided so far (see `docs/adr/`):

- ~~ranking model~~ — **ADR-0001**: computed ranking for newly discovered
  candidates only; the approved AVL rank is deliberate and never reordered.
- ~~persistence technology and migrations~~ — **ADR-0002**: SQLite, numbered
  single-transaction migrations, file backup before destructive changes.
- ~~UI form (model level)~~ — **ADR-0003**: app-first over a shared library
  and versioned JSON documents; CLI/agent is the secondary surface.
- ~~concrete app form~~ — **ADR-0004**: a local stdlib web app served by the
  CLI (`hendley app`, `src/hendley/app/`).
- ~~AI interpretation~~ — **ADR-0005**: the replaceable `Interpreter`
  protocol (`hendley.ai`), `claude -p` as the first implementation, judgments
  cached in the DB (schema v4) with provenance.
- ~~discovery/search composition~~ — **ADR-0006**: judgment belongs to the
  agent and the engineer; searches are human-fired, deterministic
  auto-discovery only.
- ~~canonical Requirements BOM schema~~ — implemented and versioned in
  `hendley.domain.model` (`requirementsBomVersion: 1`); see §5.3.

The following remain intentionally unresolved:

- component taxonomy and category-specific constraints
- plugin packaging and discovery
- ranking configuration model (the weights/format engineers may edit)
- PCBWay data acquisition
- multi-vendor AI provider selection (the `Interpreter` seam exists per
  ADR-0005; alternatives beyond `claude -p` are unexplored)
- project/user/organization knowledge precedence
- requirement-signature algorithm
- open-source license and transition plan

These decisions should be documented in `docs/adr/` when made.

## 15. Architectural Invariants

1. Engineering intent remains independent of provider-specific sourcing.
2. The Resolver Core contains no board-house-specific policy.
3. Hard validation precedes ranking and AI.
4. Provider Strategies affect selection but not output formatting.
5. Provider Adapters format approved output but do not select parts.
6. AI remains advisory and optional.
7. Engineer approval gates release.
8. Historical use influences ranking but never eligibility.
9. Facts retain provenance and freshness.
10. Existing Fusion migration tools remain explicit, separate, and engineer-initiated.
