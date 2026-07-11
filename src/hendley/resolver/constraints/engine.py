"""The Hard Constraint Engine — deterministic candidate rejection.

Runs BEFORE ranking and any AI involvement (architecture invariant 3): a
candidate that violates a mandatory constraint never reaches the ranked list,
and every rejection carries its reason (PRD §12.5 — deterministic, explained,
never silent).

V1 scope, deliberately honest about what is deterministic:

- **verification** — a candidate whose facts could not be live-verified is
  rejected (discovery-index numbers are a stale snapshot; unknown inventory
  is not zero inventory, but it is not orderable evidence either).
- **package** — exact string mismatch against the spec's package rejects
  (same-package-first is the standing sourcing bias, and a package change is
  a layout change — that promotion is an engineer's call, not a ranker's).
  Candidates with no package string are kept (unknown ≠ wrong) and flagged.

Value/tolerance/rating conformance is **not** checked here in v1: the
authoritative live ``parameters[]`` are category-specific free-form strings,
and interpreting them is judgment (PRD §9.1 examples vs. reality). The
parameters ride along on every candidate so the reviewer — engineer, app,
or agent — applies the value filter with the data in view.
"""

from __future__ import annotations

from ...domain.model import SpecKey


def filter_candidates(
    spec: SpecKey | None, candidates: list[dict]
) -> tuple[list[dict], list[dict]]:
    """Split candidates into (valid, rejected); rejected rows carry ``rejectedBecause``.

    Candidates are the verified rows of the discovery flow (``code``,
    ``verified``, ``package``, ``liveStock``, ``parameters`` …).
    """
    valid: list[dict] = []
    rejected: list[dict] = []
    for c in candidates:
        reasons: list[str] = []
        if not c.get("verified"):
            reasons.append("not live-verified against the catalog")
        pkg = c.get("package")
        if spec is not None and pkg and pkg != spec.package:
            reasons.append(f"package {pkg!r} != required {spec.package!r}")
        if reasons:
            rejected.append({**c, "rejectedBecause": reasons})
        else:
            out = dict(c)
            if spec is not None and not pkg:
                out.setdefault("caveats", []).append(
                    "package unknown — confirm before approving")
            valid.append(out)
    return valid, rejected
