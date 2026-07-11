"""AI assistance — judgment calls the deterministic core must not make.

Per PRD §13 and architecture §5.9: AI here is advisory, optional, and
replaceable. It interprets what humans wrote ad hoc (part values like
``47u/50V``, 25 years of library footprint names like ``C-E-5``) into the
canonical vocabulary — it never invents inventory, never approves parts,
and the app runs fully without it (uninterpreted lines become one-time
confirm cards).

Every interpretation is cached in the knowledge store with provenance;
each unique string is judged once, ever.
"""

from .interpreter import Interpretation, Interpreter

__all__ = ["Interpretation", "Interpreter"]
