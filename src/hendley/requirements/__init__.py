"""Requirements capture — normalize ECAD extractions into the canonical BOM."""

from .normalizer import requirements_from_design

__all__ = ["requirements_from_design"]
