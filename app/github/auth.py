"""GitHub App authentication — JWT generation & installation access tokens."""

from __future__ import annotations


def generate_app_jwt() -> str:
    """Create a signed JWT for the GitHub App (RS256, 10 min expiry)."""
    ...


def get_installation_token(installation_id: str) -> str:
    """Exchange the App JWT for an installation-scoped access token."""
    ...
