"""HMAC-SHA-256 signature validation for GitHub webhook payloads."""

from __future__ import annotations

import hashlib
import hmac
import logging

logger = logging.getLogger(__name__)


def verify_signature(payload: bytes, signature_header: str, secret: str) -> bool:
    """Constant-time comparison of ``X-Hub-Signature-256`` against the payload HMAC."""
    logger.debug(f"Validating webhook signature (payload_size={len(payload)} bytes)")

    if not signature_header or not signature_header.startswith("sha256="):
        logger.warning(f"Invalid signature header format (missing or malformed): {signature_header[:20] if signature_header else 'empty'}")
        return False

    try:
        expected = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
        received = signature_header.removeprefix("sha256=")

        is_valid = hmac.compare_digest(expected, received)
        if is_valid:
            logger.debug("✓ Webhook signature validation passed")
        else:
            logger.warning("✗ Webhook signature mismatch (possible tampering or wrong secret)")
        return is_valid
    except Exception as e:
        logger.error(f"✗ Signature validation error: {type(e).__name__}: {e}")
        return False
