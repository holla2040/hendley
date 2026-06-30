"""Hendley — JLCPCB parts inventory client and Fusion Electronics BOM helper.

Named for James Garner's character in *The Dirty Dozen*.
"""

from .client import JLCClient, JLCError
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
