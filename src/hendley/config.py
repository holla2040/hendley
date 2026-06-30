"""Configuration and credential loading for Hendley.

Credentials live in a ``.keys`` file (git-ignored) at the project root. The
file is the one issued by JLCPCB and looks like::

    JLCAPI:
        AppID:     <your-app-id>
        Accesskey: <your-access-key>
        SecretKey: <your-secret-key>

Only these three fields are used. (The JLCPCB ``.keys`` file also contains an
RSA "Tokenization Key" block intended for encrypting sensitive order-placement
fields, but Hendley does not implement order placement and ignores it entirely.)
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

# JLCPCB global/overseas OpenAPI *API* host. Note: api.jlcpcb.com is the
# developer **portal** (docs/console); live API routes are served from
# open.jlcpcb.com (verified: valid signature -> 403 perms, bad signature -> 401).
# The China host baked into the Java SDK default is https://openapi.jlc.com.
DEFAULT_ENDPOINT = "https://open.jlcpcb.com"


def _project_root() -> Path:
    """Walk up from the cwd looking for a ``.keys`` file, else use cwd."""
    here = Path.cwd()
    for candidate in (here, *here.parents):
        if (candidate / ".keys").exists():
            return candidate
    return here


@dataclass(frozen=True)
class Credentials:
    app_id: str
    access_key: str
    secret_key: str


@dataclass(frozen=True)
class Settings:
    credentials: Credentials
    endpoint: str = DEFAULT_ENDPOINT


def _parse_keys(text: str) -> Credentials:
    """Parse the JLCPCB ``.keys`` file.

    Only the ``AppID`` / ``Accesskey`` / ``SecretKey`` pairs are read; any other
    blocks in the file (e.g. the RSA tokenization key) are ignored.
    """
    app_id = access_key = secret_key = None

    # Simple ``Label: value`` pairs (AppID / Accesskey / SecretKey).
    for key, attr in (("AppID", "app_id"), ("Accesskey", "access_key"), ("SecretKey", "secret_key")):
        m = re.search(rf"^\s*{key}\s*:\s*(\S+)\s*$", text, re.IGNORECASE | re.MULTILINE)
        if m:
            value = m.group(1)
            if attr == "app_id":
                app_id = value
            elif attr == "access_key":
                access_key = value
            else:
                secret_key = value

    missing = [n for n, v in (("AppID", app_id), ("Accesskey", access_key), ("SecretKey", secret_key)) if not v]
    if missing:
        raise ValueError(f".keys is missing required field(s): {', '.join(missing)}")

    return Credentials(
        app_id=app_id,
        access_key=access_key,
        secret_key=secret_key,
    )


def load_credentials(path: str | os.PathLike | None = None) -> Credentials:
    """Load credentials from a ``.keys`` file.

    Path resolution order: explicit ``path`` arg, then ``HENDLEY_KEYS`` env var,
    then a ``.keys`` file discovered by walking up from the cwd.
    """
    if path is None:
        path = os.environ.get("HENDLEY_KEYS")
    keys_path = Path(path) if path else _project_root() / ".keys"
    if not keys_path.exists():
        raise FileNotFoundError(
            f"No .keys file found at {keys_path}. Set HENDLEY_KEYS or run from the project root."
        )
    return _parse_keys(keys_path.read_text())


def _read_endpoint() -> str:
    """Endpoint override order: HENDLEY_ENDPOINT env, else the default API host.

    The project ``notes`` file holds the developer-portal URL, not the API host,
    so it is intentionally not used as the endpoint source.
    """
    env = os.environ.get("HENDLEY_ENDPOINT")
    if env:
        return env.rstrip("/")
    return DEFAULT_ENDPOINT


def load_settings(keys_path: str | os.PathLike | None = None) -> Settings:
    return Settings(credentials=load_credentials(keys_path), endpoint=_read_endpoint())
