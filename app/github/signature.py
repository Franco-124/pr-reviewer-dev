"""HMAC-SHA-256 signature validation for GitHub webhook payloads."""

from __future__ import annotations


def verify_signature(payload: bytes, signature_header: str, secret: str) -> bool:
    """Constant-time comparison of ``X-Hub-Signature-256`` against the payload HMAC."""
    ...
