"""Core domain objects — provider-neutral, ECAD-neutral.

Nothing in this package may import from ``hendley.providers.*`` or
``hendley.datasources.*`` (concrete implementations); the domain is the
vocabulary every other layer speaks.
"""

from .model import (
    CHECK_SEVERITIES,
    CHECKS,
    ERROR_CHECKS,
    REQUIREMENTS_BOM_VERSION,
    Check,
    RequirementLine,
    RequirementsBom,
    SpecKey,
    make_check,
)

__all__ = [
    "CHECK_SEVERITIES",
    "CHECKS",
    "ERROR_CHECKS",
    "REQUIREMENTS_BOM_VERSION",
    "Check",
    "RequirementLine",
    "RequirementsBom",
    "SpecKey",
    "make_check",
]
