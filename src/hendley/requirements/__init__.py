"""Requirements capture — normalize ECAD extractions into the canonical BOM."""

from .normalizer import has_zener_evidence, requirements_from_design

__all__ = ["has_zener_evidence", "requirements_from_design"]
