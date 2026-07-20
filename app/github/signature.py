"""HMAC-SHA-256 signature validation for GitHub webhook payloads."""

from __future__ import annotations

import hashlib
import hmac


def verify_signature(payload: bytes, signature_header: str, secret: str) -> bool:
    """Constant-time comparison of ``X-Hub-Signature-256`` against the payload HMAC."""
    if not signature_header or not signature_header.startswith("sha256="):
        return False

    expected = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    received = signature_header.removeprefix("sha256=")

    return hmac.compare_digest(expected, received)
