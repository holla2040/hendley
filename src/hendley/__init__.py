"""Hendley — JLCPCB parts inventory client and Fusion Electronics BOM helper.

Named for James Garner's character in *The Great Escape*.
"""

from .config import Credentials, Settings, load_credentials, load_settings

__version__ = "0.1.0"
__all__ = [
    "JLCClient",
    "JLCError",
    "Credentials",
    "Settings",
    "load_credentials",
    "load_settings",
]


def __getattr__(name):
    # Lazy re-exports (PEP 562): `from hendley import JLCClient` still works,
    # but importing any hendley submodule no longer drags the JLC datasource
    # in eagerly — provider-independent paths (e.g. PCBWay resolution) must
    # run without touching datasources/jlc (architecture invariant 2; proven
    # by tests/test_providers.py::test_pcbway_path_never_imports_jlc_modules).
    if name in ("JLCClient", "JLCError"):
        from .datasources.jlc import client

        return getattr(client, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
