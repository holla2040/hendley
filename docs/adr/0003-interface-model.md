# ADR-0003 — Interface model: app-first, agent second

**Status:** Accepted
**Date:** 2026-07-10

## Context

The PRD requires an engineer review-and-approval interface (§12.8) but left
the "UI form" open (architecture.md §14). Historically the review surface has
been a Claude agent driving the CLI (the `/jlc` and order-bom skills). The
product owner has decided the main interaction should be through the product
itself, not through an agent session.

## Decision

1. **The app is the primary interface.** Browsing House Parts/AVLs, running
   resolutions, clearing the approval queue, and emitting order files all
   happen in the app. Its concrete form (local web app, TUI, desktop shell)
   is a separate decision — **ADR-0004**, taken at the start of the app phase;
   the current recommendation is a local web app served by the CLI
   (`hendley app`), with its dependencies in an optional `[app]` extra.
2. **Claude/agent access is the secondary use case** — headless runs,
   conversational part exploration, and scripted flows drive the same CLI.
3. **Both are thin peers over one library.** No business logic lives in the
   app or the CLI; every action is a library call. All review/approval
   artifacts (Requirements BOM, resolution document, approval queue, release
   snapshot) are **versioned JSON documents** — the app renders them, the
   agent reads them, and feature parity between the two surfaces follows by
   construction.

## Consequences

- Closes "UI form" in architecture.md §14 at the model level; the concrete
  app form is deferred to ADR-0004.
- The library API and the JSON document contracts are the stable surfaces;
  they must not assume an interactive terminal or an agent.
- The core package stays requests-only; app-only dependencies live in the
  `[app]` extra.
