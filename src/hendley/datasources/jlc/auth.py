"""Request signing for the JLCPCB OpenAPI (the ``JOP`` scheme).

Reverse-engineered from the official Java SDK
(``com.jlc.openapi.core.client.auth.authorization.SignAuthorization``).

The string to sign is::

    METHOD \n CANONICAL_URI \n TIMESTAMP \n NONCE \n PAYLOAD \n

where ``CANONICAL_URI`` is the raw request path (plus ``?query`` if present),
``TIMESTAMP`` is integer seconds since the epoch, ``NONCE`` is a 32-char random
token, and ``PAYLOAD`` is the exact request body (empty string for GET).

The signature is ``Base64(HMAC_SHA256(secret_key, string_to_sign))`` and the
resulting header is::

    Authorization: JOP appid="..",accesskey="..",timestamp="..",nonce="..",signature=".."
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import string
import time

_NONCE_ALPHABET = string.ascii_letters + string.digits


def make_nonce(length: int = 32) -> str:
    return "".join(secrets.choice(_NONCE_ALPHABET) for _ in range(length))


def build_string_to_sign(method: str, canonical_uri: str, timestamp: str, nonce: str, payload: str) -> str:
    return f"{method.upper()}\n{canonical_uri}\n{timestamp}\n{nonce}\n{payload}\n"


def sign(secret_key: str, string_to_sign: str) -> str:
    digest = hmac.new(secret_key.encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha256).digest()
    return base64.b64encode(digest).decode("ascii")


def authorization_header(
    *,
    app_id: str,
    access_key: str,
    secret_key: str,
    method: str,
    canonical_uri: str,
    payload: str = "",
    timestamp: str | None = None,
    nonce: str | None = None,
) -> str:
    """Build the full ``Authorization`` header value for a request."""
    timestamp = timestamp or str(int(time.time()))
    nonce = nonce or make_nonce()
    sts = build_string_to_sign(method, canonical_uri, timestamp, nonce, payload)
    signature = sign(secret_key, sts)
    return (
        f'JOP appid="{app_id}",accesskey="{access_key}",'
        f'timestamp="{timestamp}",nonce="{nonce}",signature="{signature}"'
    )
