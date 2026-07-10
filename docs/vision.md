# Vision Document

**Project:** AI-Assisted Manufacturing BOM Resolver
**Version:** 0.1 (Draft)
**Status:** Vision

---

# 1. Vision

The purpose of this project is to fundamentally separate **electronic design** from **manufacturing component selection**.

Current ECAD workflows tightly couple schematic design with procurement decisions, requiring engineers to select manufacturer or assembly-specific part numbers during the design process. This forces engineers to spend significant time performing repetitive supply-chain work rather than engineering design.

This project introduces an AI-assisted Manufacturing BOM Resolver that allows engineers to design using engineering intent while automatically resolving those requirements into manufacturing-ready BOMs through a transparent, reviewable workflow.

The objective is simple:

> **Free engineers to do design.**

The resolver never replaces engineering judgment.

Instead, it automates repetitive procurement work while keeping engineers responsible for all final decisions.

---

# 2. The Problem

Most ECAD systems require designers to assign specific manufacturer part numbers while creating schematics.

Although this simplifies downstream manufacturing, it introduces several problems:

* Procurement decisions become mixed with engineering decisions.
* Supply-chain changes require schematic maintenance.
* Engineers spend hours searching distributor inventories.
* Existing component knowledge is difficult to reuse.
* Manufacturing workflows become tightly coupled to a specific supplier strategy.

For many PCB designs, especially those using passive components, the engineering intent is considerably simpler than the manufacturing implementation.

For example, an engineer usually intends:

* 22 kΩ
* ±1%
* 0603
* 100 mW

—not a specific manufacturer's resistor.

Current tools force these concepts to become inseparable.

---

# 3. Why Now?

Modern AI systems fundamentally change what is practical.

Large language models, retrieval systems, and structured component databases can now:

* interpret engineering intent,
* search supplier inventories,
* evaluate alternates,
* explain trade-offs,
* rank component choices,
* preserve engineering preferences.

These capabilities make it practical to automate the repetitive portion of manufacturing BOM creation while keeping engineers in complete control.

---

# 4. Architectural Principle

The central architectural principle is **Separation of Concerns**.

The project intentionally separates four independent responsibilities.

## Engineering Design

Responsible for:

* schematic capture
* PCB layout
* electrical intent
* mechanical intent

Engineering tools remain the single source of truth for design intent.

---

## Component Resolution

Responsible for:

* interpreting engineering requirements
* identifying valid components
* finding alternates
* evaluating lifecycle
* evaluating availability
* evaluating supply risk

This responsibility belongs to the Manufacturing BOM Resolver.

---

## Manufacturing Optimization

Responsible for:

* selecting preferred components
* optimizing inventory usage
* minimizing sourcing effort
* maintaining manufacturing compatibility

Optimization policies may differ between manufacturing providers.

---

## Provider Integration

Responsible for converting resolved components into manufacturing-specific formats.

Examples include:

* JLCPCB / LCSC
* PCBWay
* future assembly providers
* internal corporate AVL systems

Each provider is implemented as an independent strategy/adapter.

The resolver core remains provider-independent.

---

# 5. Design Intent

Engineering intent represents long-lived knowledge.

Manufacturing information represents short-lived knowledge.

Engineering intent should remain stable even when:

* inventories change,
* prices change,
* suppliers disappear,
* new alternates become available.

This separation dramatically reduces unnecessary maintenance.

---

# 6. AI Philosophy

AI is an enabling technology—not the product.

The AI system exists to:

* remove repetitive work,
* explain recommendations,
* rank alternatives,
* accelerate decision making.

The AI never silently selects components.

The engineer always approves the final manufacturing BOM.

Guiding principle:

> **AI advises. Engineers decide.**

---

# 7. Reusable Engineering Knowledge

Every approved component represents valuable engineering knowledge.

The resolver should preserve this knowledge and reuse it intelligently.

Examples include:

* previously approved passive components,
* preferred resistor families,
* preferred capacitor families,
* frequently used footprints,
* manufacturing success history.

Future recommendations should prefer proven components whenever engineering requirements remain satisfied.

Historical usage should influence ranking without overriding engineering constraints.

---

# 8. Initial Manufacturing Target

The initial implementation targets the JLCPCB manufacturing workflow.

This is intentionally a first implementation—not a limitation of the architecture.

The JLC strategy should leverage the close integration between:

* JLCPCB
* LCSC

allowing the resolver to produce JLC-compatible manufacturing BOMs with minimal manual effort.

Future providers should require only new provider strategies rather than changes to the resolver core.

---

# 9. Provider Strategy Architecture

Different manufacturers optimize differently.

For example:

JLCPCB primarily operates within the LCSC ecosystem.

Another assembly provider may optimize using:

* DigiKey
* Mouser
* Arrow
* internal inventory
* approved vendor lists (AVLs)

Therefore the provider strategy determines:

* searchable inventory sources,
* optimization priorities,
* preferred identifiers,
* output formats,
* manufacturing constraints.

The resolver core remains independent of these decisions.

---

# 10. Success Criteria

A successful workflow should resemble the following:

1. Engineer completes schematic and PCB design.
2. Design Rule Check passes.
3. Engineer exports a requirements-based BOM.
4. Manufacturing BOM Resolver analyzes requirements.
5. AI generates ranked component recommendations.
6. Engineer reviews recommendations.
7. Resolver generates a manufacturing-ready BOM.
8. BOM is submitted directly to the selected assembly provider.

The manual component-resolution process should be reduced from hours to minutes.

---

# 11. Guiding Principles

* Engineering intent is the source of truth.
* Manufacturing data is transient.
* Separate design from procurement.
* Separate procurement from provider implementation.
* Preserve reusable engineering knowledge.
* Keep humans responsible for final approval.
* AI accelerates engineering workflows through transparent recommendations.
* Provider-specific behavior belongs in provider strategies, not in the resolver core.
* Build an open architecture that encourages community-contributed provider integrations.

---

# 12. Scope

This project focuses on manufacturing BOM generation after engineering design is complete.

The project is **not** intended to replace:

* ECAD tools,
* schematic capture,
* PCB layout,
* simulation,
* electrical verification.

It complements existing ECAD workflows by automating the repetitive transition from completed design to manufacturing-ready procurement.

---

# 13. Long-Term Vision

The Manufacturing BOM Resolver should become a provider-independent, open-source platform that enables engineers to move seamlessly from completed design to manufacturing without performing repetitive procurement work.

By separating engineering intent from manufacturing implementation, the platform creates a reusable knowledge system that improves over time while remaining transparent, reviewable, and under engineer control.

The long-term goal is not simply to automate BOM creation.

The goal is to redefine the interface between electronic design and electronic manufacturing.
