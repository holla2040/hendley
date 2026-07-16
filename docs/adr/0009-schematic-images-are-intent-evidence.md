# ADR-0009 — Schematic images are intent evidence

**Status:** Accepted
**Date:** 2026-07-15

## Context

Fusion's structured rows frequently omit meaning that the drawing communicates
through the symbol. A polarized capacitor, zener diode, Schottky diode, MOSFET
channel, or transistor family may be obvious on the sheet while its VALUE and
attributes remain generic. Encoding each discovery as another Python parser or
regular expression makes Hendley specific to the last design it encountered.

## Decision

Refresh activates the known-existing first sheet with `EDIT .S1`, enumerates
`electronics.Sheet`, selects only those returned sheets with `EDIT .S<n>`,
runs `WINDOW FIT`, pauses for Fusion's deferred drawing-context update, removes
any stale output, and exports each complete sheet with Fusion Electronics'
`EXPORT IMAGE` command. It also fits and exports the board after `BOARD`, with
the `UNROUTED` layer temporarily hidden so airwires cannot be mistaken for
package evidence. Each unresolved placement gets a centered 12 mm × 12 mm board
crop whose exact physical span is recorded in the manifest. Export is
best-effort and local; failure never invalidates the structured design read.
Refresh performs no model calls.

When the engineer opens an unresolved part, the existing lazy `read_part`
judgment receives the structured dossier plus the captured images. Codex gets
the local PNGs through `codex exec --image`. The prompt asks for a general
intent record—family, subtype, polarity/channel, mount, observed visual cues,
and uncertainty—rather than a component-specific Boolean or regex result.

Visual interpretation describes the requirement and creates executable intent
terms. It never proves that a candidate satisfies them. Live-verified
`firstTypeName` and `secondTypeName`, catalog parameters, physical dimensions,
stock, and price remain the proof. In particular, an electrolytic reading emits
a `secondTypeName` class term rather than trusting broken index flags.

When an exact catalog package is unknown, the reader may use a coarse keyword
net to get the intended class inside the discovery index's 100-row cap. The net
stays deliberately broad; every electrical, class, mount, and dimensional claim
is repeated in the live sieve. A dimensioned crop may support a diameter token
such as `D5`, while catalog `Diameter = 5 mm` supplies the proof.

The image digest and visual schema version are part of the lazy-read cache key.
Changing the drawing therefore triggers a new judgment; an unchanged drawing
reuses the cached result. User decisions retain higher provenance than an AI
reading.

## Consequences

- New schematics should not require C/D/Q-specific Python edits merely because
  their symbols convey a different subtype.
- Full sheets preserve nearby circuit context. The requested designator is
  included in the dossier so the model must locate the correct symbol.
- Generic or unreadable symbols remain uncertain and visible to the engineer.
- Board imagery supports package and mount evidence, but does not establish
  electrical class.
- Capture commands are deliberately settled and fresh-file checked. Separate
  asynchronous `WINDOW` and `EXPORT` calls produced stale full-board "crops"
  and identical sheet images; accepting an already-existing PNG hid the race.
- Fusion's display grid is useful on screen but is omitted by `EXPORT IMAGE`.
  Known crop bounds provide exportable scale instead.
- The Claude compatibility backend currently falls back to the text dossier;
  the implemented local-image transport is Codex `--image`.

The default cross-OS capture directory is
`C:\tmp\hendley-visual` in Fusion and `~/tmp/hendley-visual` in WSL. Override them with
`HENDLEY_FUSION_VISUAL_DIR` and `HENDLEY_VISUAL_DIR` respectively.
