"""The Hard Constraint Engine — deterministic candidate rejection.

Runs BEFORE ranking and any AI involvement (architecture invariant 3): a
candidate that violates a mandatory constraint never reaches the ranked list,
and every rejection carries its reason (PRD §12.5 — deterministic, explained,
never silent).

Checks, in order of authority:

- **verification** — a candidate whose facts could not be live-verified is
  rejected (discovery-index numbers are a stale snapshot).
- **package / fit** — the check that keeps a part that physically cannot
  land on the board out of the ranked list:

  - chip-package specs (0402/0603/…): exact string match, as before.
  - non-chip specs (an interpreted library footprint like ``C-E-5``) with a
    physical **envelope** (`{"mount", "maxDiaMm", "maxLenMm",
    "leadSpacingMm"}` from the interpretation cache): candidate dimensions
    are parsed from the catalog strings (``D6.3xL7.7mm``, ``5x11mm``);
    within the envelope → pass, over → reject with the numbers, and
    **unparseable → the ``fit unconfirmed`` bucket** — surfaced separately,
    NEVER ranked (unknown fit is not a scoring problem, it's a blocker for
    proposing).

Value/tolerance conformance stays judgment: the authoritative live
``parameters[]`` ride along on every candidate for the reviewer.
"""

from __future__ import annotations

import re

from ...domain.model import SpecKey

_CHIP = re.compile(r"^(0201|0402|0603|0805|1206|1210|2010|2512)$")
_DIMS = re.compile(
    r"D?\s*(\d+(?:\.\d+)?)\s*[x×*]\s*L?\s*(\d+(?:\.\d+)?)\s*mm", re.IGNORECASE)


def is_chip_package(package: str | None) -> bool:
    return bool(package) and bool(_CHIP.match(package))


def candidate_dims_mm(candidate: dict) -> tuple[float, float] | None:
    """(dia/width, length/height) parsed from catalog strings, or None."""
    for text in (candidate.get("package"), candidate.get("description")):
        if not text:
            continue
        m = _DIMS.search(text)
        if m:
            return float(m.group(1)), float(m.group(2))
    return None


def filter_candidates(
    spec: SpecKey | None,
    candidates: list[dict],
    envelope: dict | None = None,
) -> tuple[list[dict], list[dict], list[dict]]:
    """Split candidates into (valid, rejected, fit_unconfirmed).

    Rejected rows carry ``rejectedBecause``; unconfirmed rows carry
    ``fitUnknownBecause``. Candidates are the verified rows of the discovery
    flow (``code``, ``verified``, ``package``, ``liveStock``,
    ``parameters`` …).
    """
    envelope = envelope or {}
    valid: list[dict] = []
    rejected: list[dict] = []
    unconfirmed: list[dict] = []
    spec_is_chip = spec is not None and is_chip_package(spec.package)

    for c in candidates:
        if not c.get("verified"):
            rejected.append({**c, "rejectedBecause":
                             ["not live-verified against the catalog"]})
            continue
        if spec is None:
            valid.append(dict(c))
            continue

        pkg = c.get("package")
        if spec_is_chip:
            if pkg and pkg != spec.package:
                rejected.append({**c, "rejectedBecause":
                                 [f"package {pkg!r} != required {spec.package!r}"]})
            elif not pkg:
                unconfirmed.append({**c, "fitUnknownBecause":
                                    ["catalog reports no package string"]})
            else:
                valid.append(dict(c))
            continue

        # Non-chip spec: the library footprint keys the spec; fit is physical.
        if pkg == spec.package:
            valid.append(dict(c))  # literally the same footprint name
            continue
        if is_chip_package(pkg):
            rejected.append({**c, "rejectedBecause":
                             [f"chip part ({pkg}) cannot land on the "
                              f"{spec.package} footprint"]})
            continue
        dims = candidate_dims_mm(c)
        if not envelope:
            unconfirmed.append({**c, "fitUnknownBecause":
                                [f"no physical envelope known for "
                                 f"{spec.package} — confirm fit by hand"]})
            continue
        if dims is None:
            unconfirmed.append({**c, "fitUnknownBecause":
                                ["catalog gives no parseable dimensions"]})
            continue
        dia, length = dims
        max_dia = envelope.get("maxDiaMm")
        max_len = envelope.get("maxLenMm")
        problems = []
        if max_dia and dia > float(max_dia):
            problems.append(f"body {dia}mm > max {max_dia}mm for {spec.package}")
        if max_len and length > float(max_len):
            problems.append(f"length {length}mm > max {max_len}mm for {spec.package}")
        if problems:
            rejected.append({**c, "rejectedBecause": problems})
        elif not max_dia and not max_len:
            unconfirmed.append({**c, "fitUnknownBecause":
                                ["envelope has no size limits to check against"]})
        else:
            valid.append({**c, "fit": f"{dia}x{length}mm within "
                          f"{max_dia or '—'}/{max_len or '—'}mm"})
    return valid, rejected, unconfirmed
