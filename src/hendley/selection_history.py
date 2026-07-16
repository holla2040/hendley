"""Design-independent identity for reusable *search intent*, never part choices."""

from __future__ import annotations

import hashlib
import json
import re


_ADMIN_ATTRIBUTES = {
    "DNP", "LCSC", "JLC", "JLCPCB", "OLDLCSC", "MANUFACTURER", "MP", "MF",
}


def _text(value) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


def component_identity(line: dict) -> dict:
    lib = line.get("libraryIdentity")
    mixed = isinstance(lib, list) or bool(line.get("mixedLibraryIdentity"))
    lib = dict(lib) if isinstance(lib, dict) else {}
    attrs = {
        str(k).strip().upper(): _text(v)
        for k, v in dict(line.get("attributes") or {}).items()
        if str(k).strip().upper() not in _ADMIN_ATTRIBUTES and _text(v)
    }
    identity = {
        "deviceSetUrn": _text(lib.get("deviceSetUrn")),
        "libraryVersion": _text(lib.get("libraryVersion")),
        "deviceVariant": _text(lib.get("deviceVariant")),
        "packageVariant": _text(lib.get("packageVariant") or line.get("footprint")),
        "value": _text(line.get("comment") or line.get("value") or line.get("family")),
        "attributes": attrs,
        "footprint": _text(line.get("footprint")),
        "footprintHeadline": _text(line.get("footprintHeadline")),
    }
    stable = bool(identity["deviceSetUrn"])
    exact_eligible = stable and not mixed and not bool(lib.get("locallyModified"))
    exact_material = dict(identity)
    similar_material = dict(identity)
    similar_material.pop("libraryVersion", None)
    # Suggestions may bridge a missing/different URN using the remaining
    # engineering evidence. They never authorize an automatic search.
    similar_material.pop("deviceSetUrn", None)
    return {
        "identity": identity,
        "exactKey": _digest(exact_material) if exact_eligible else "",
        "similarityKey": _digest(similar_material),
        "exactEligible": exact_eligible,
        "suggestionReason": (
            "grouped components have mixed library identities" if mixed else
            "the library is locally modified" if lib.get("locallyModified") else
            "no stable Fusion device-set identity" if not stable else "library version differs"
        ),
    }


def _digest(value: dict) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()
