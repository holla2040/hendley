# Writing a provider

How to add a board house / procurement target to Hendley. PCBWay
(`src/hendley/providers/pcbway/`, ~100 lines total) is the reference
implementation and the anti-coupling proof — read it alongside this guide.
The contracts live in `src/hendley/providers/base.py`.

## The two roles — strategies select, adapters format

A provider is two small classes with deliberately separate jobs
(architecture invariants 4/5, `docs/architecture.md` §15):

- a **`ProviderStrategy`** influences *resolution* — which refs to
  live-verify, whether a fact is orderable for a line at the order's
  quantity, and provider-flavored scoring input for candidate ranking;
- a **`ProviderAdapter`** turns an *approved* resolution into the provider's
  upload files. It never selects parts.

A strategy must never format output; an adapter must never make a selection
decision. If you find yourself passing selection state into `export()`, the
logic belongs in the strategy (or the resolver).

## The strategy contract

```python
class MyStrategy:
    provider = "myprovider"          # the registry key, e.g. "jlcpcb"
    offer_type = "my-offer"          # stamped on every resolved line
    requires_live_stock = False      # True only with a real live-stock source

    def query_context(self, requirements, candidate_refs) -> list[str]: ...
    def evaluate(self, line, fact, required_qty) -> tuple[bool, list[Check]]: ...
    def score(self, candidate, required_qty) -> list[dict]: ...
```

There are two honest shapes, and everything follows from which one your
provider is:

**Live-verified (JLCPCB).** The provider has a catalog API that can confirm
stock. `requires_live_stock = True`; `query_context` returns the refs to
verify (the resolver makes ONE batched `DataSource.verify` call with them);
`evaluate` rejects a line when the fact is missing, not in the catalog, or
short of `required_qty` — each rejection carries a named `Check`.

**Honest-unverified (PCBWay).** The provider has no public parts/stock API.
Do **not** scrape and do **not** invent inventory. `requires_live_stock =
False`; `query_context` returns `[]` (nothing is live-verifiable — never
pretend otherwise); `evaluate` accepts any line with a usable identity (an
MPN, or a recorded provider ref) and attaches an `unverified` **warning** —
the provider confirms sourcing on their side. Resolved lines keep
`liveStock: None`; unknown inventory is not zero inventory (invariant 9).

Rules that hold for both:

- **Checks come from the authority table.** Build every check with
  `make_check()` (`hendley.domain.model`); it refuses names missing from
  `CHECKS`, where each name has a fixed severity (error blocks the upload,
  warning doesn't). Reuse the existing names (`unverified`,
  `no-code-uncheckable`, `not-in-catalog`, `insufficient-stock`, …); a
  genuinely new failure mode means adding a row to `CHECKS` — a domain
  change to make deliberately, not a side effect.
- **`score()` is display-flavored, not policy.** It returns
  `{"factor", "weight", "why"}` contributions for *newly discovered*
  candidates only (ADR-0001 — the approved AVL rank is deliberate and never
  computed). Generic factors (stock margin, price, prior approval) belong to
  the ranking engine; add only what is provider-specific. Fee attributes
  like JLC's Basic/Extended are surfaced with `weight: 0.0` — displayed for
  the engineer's judgment, never selected on.

## Identity: how the AVL speaks your provider's language

Part Choices in the house-parts DB are provider-neutral: identity is
MPN + manufacturer first, plus per-provider refs in `choice_provider_ids`
(the LCSC code is simply the `jlcpcb` ref; `record(..., lcsc=…)` is
shorthand for `provider_refs={"jlcpcb": …}`). The resolver hands your
strategy what it finds via two lookups:

- AVL choices: `choice["providerRefs"].get(provider)` — record a ref for
  your provider with `record(..., provider_refs={"myprovider": ref})`;
- explicit lines: `line.provider_ref(provider)` — a Requirements BOM line
  can pin a ref per provider in its `providerRefs` map.

A provider that orders by MPN (PCBWay) needs no refs of its own — MPN
identity on the choice is enough. An AVL choice with *only* another
provider's ref (e.g. LCSC-coded, no MPN) is unusable for you; `evaluate`
should reject it and let the resolver escalate (`avl-exhausted`).

## The datasource question

A `DataSource` (`hendley.datasources.base`) is a separate seam from the
provider: `verify()` returns authoritative `PartFact`s with provenance and
freshness; `discover()` returns advisory candidate rows. Only build one if
the provider (or a third party) offers a real queryable catalog — JLC has
one (`hendley.datasources.jlc`); PCBWay deliberately has none. Never
conflate discovery-index numbers with verified facts, and never order
against the DB's advisory stock/price cache.

## The adapter contract

```python
class MyAdapter:
    provider = "myprovider"

    def validate(self, resolution: dict) -> list[Check]: ...
    def export(self, resolution: dict, outdir: Path) -> list[Path]: ...
```

- **`validate` is the blocking gate.** Return the error-severity checks that
  refuse the export: collect `severity == "error"` checks off the
  resolution's lines, and synthesize an `unresolved` error for any populated
  line missing the identity your upload format needs (PCBWay: no MPN and no
  ref). Warnings (`unverified`, `substitution`) pass the gate — they warn,
  they don't block.
- **`export` formats, writes, and returns the paths.** Skip DNP lines from
  the output (they stay in the resolution document). Mind the quantity
  convention: PCBWay's template wants **per-board** quantities
  (`len(designators) * quantityPer`); the at-order quantity (× board count)
  was already enforced by the strategy at resolve time. Match what *your*
  provider's template expects and say so in the module docstring.
- **Snapshots are not your job.** The emit layers (`hendley bom -o`, the
  app's export) write the immutable Release Snapshot beside a clean emit
  (`hendley.reporting.snapshot`); the adapter neither writes nor suppresses
  it.

## Wiring it in

There is no plugin registry yet (plugin packaging is an open decision,
`docs/architecture.md` §14) — providers are selected by name in three
places, each a small `if provider == …` dispatch you extend:

- `src/hendley/cli/knowledge.py` (`hendley resolve --provider …`)
- `src/hendley/cli/manufacturing.py` (`hendley bom --provider …`)
- `src/hendley/app/server.py` (`_strategy()` / the emit handler)

Also add the new value to the `--provider` choices in
`src/hendley/cli/__init__.py`. Keep the imports lazy (inside the branch), as
the existing dispatches do — that is what keeps the isolation proof (below)
honest.

## Layering rules (enforced by tests and review)

- `providers/<name>/` may import `domain`, `datasources.base`, and its own
  datasource — never another provider's, and never `datasources/jlc` unless
  JLC *is* your data source.
- Nothing under `resolver/`, `knowledge/`, or `domain/` may import your
  concrete provider — the resolver sees only the `ProviderStrategy` /
  `DataSource` protocols, injected.
- Facts stay honest: provenance and freshness on every `PartFact`; no
  invented stock; `unverified` where you cannot verify.

## The tests a provider must pass

Mirror `tests/test_providers.py` (all offline — fake datasources, tmp
paths):

1. **Adapter render** — the exact header row and a representative line of
   your upload format; DNP lines absent.
2. **Adapter gate** — `validate` returns `[]` on a clean resolution, and
   error checks (with the right `check` names) on an identity-less line;
   warnings do not block.
3. **Strategy resolution** — `resolve()` with your strategy over a seeded
   `PartsDb`: the happy path (right identity, right `offerType`, honest
   checks), and the escalation path (unusable AVL → `avl-exhausted`).
4. **The isolation proof** — a subprocess runs a full resolution + export
   with your provider and asserts no unrelated provider/datasource module
   was ever imported (`test_pcbway_path_never_imports_jlc_modules` is the
   template). This is the test that keeps "provider-independent" true.
