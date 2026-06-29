"""Tests for the JOP request-signing scheme.

Pinned against the exact algorithm in the Java SDK
(SignAuthorization + HmacSHA256Signer): the signature is
Base64(HMAC_SHA256(secret, "METHOD\\nURI\\nTS\\nNONCE\\nPAYLOAD\\n")).
"""

import base64
import hashlib
import hmac

from henley import auth


def _expected(secret, method, uri, ts, nonce, payload):
    sts = f"{method}\n{uri}\n{ts}\n{nonce}\n{payload}\n"
    digest = hmac.new(secret.encode(), sts.encode(), hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


def test_string_to_sign_layout():
    sts = auth.build_string_to_sign("POST", "/x", "1700000000", "abc", '{"a":1}')
    assert sts == 'POST\n/x\n1700000000\nabc\n{"a":1}\n'


def test_signature_matches_reference_hmac():
    sig = auth.sign("sekret", auth.build_string_to_sign("POST", "/x", "1700000000", "abc", "{}"))
    assert sig == _expected("sekret", "POST", "/x", "1700000000", "abc", "{}")


def test_authorization_header_is_deterministic_with_fixed_inputs():
    hdr = auth.authorization_header(
        app_id="APP",
        access_key="AK",
        secret_key="SK",
        method="post",  # lower-cased input should be upper-cased in the signed string
        canonical_uri="/overseas/openapi/component/getComponentLibraryList",
        payload='{"pageSize":1}',
        timestamp="1700000000",
        nonce="nonce123",
    )
    expected_sig = _expected(
        "SK", "POST", "/overseas/openapi/component/getComponentLibraryList",
        "1700000000", "nonce123", '{"pageSize":1}',
    )
    assert hdr == (
        f'JOP appid="APP",accesskey="AK",timestamp="1700000000",'
        f'nonce="nonce123",signature="{expected_sig}"'
    )


def test_nonce_is_32_chars_and_varies():
    a, b = auth.make_nonce(), auth.make_nonce()
    assert len(a) == 32 and len(b) == 32
    assert a != b


def test_file_upload_signs_empty_payload():
    # Multipart upload routes sign an empty payload (the file is not in the
    # string-to-sign) — verified against the live API.
    hdr = auth.authorization_header(
        app_id="APP", access_key="AK", secret_key="SK",
        method="POST", canonical_uri="/overseas/openapi/pcb/uploadGerber",
        payload="", timestamp="1700000000", nonce="nonce123",
    )
    expected_sig = _expected(
        "SK", "POST", "/overseas/openapi/pcb/uploadGerber", "1700000000", "nonce123", "",
    )
    assert f'signature="{expected_sig}"' in hdr
