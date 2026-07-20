"""GitHub App authentication — JWT generation & installation access tokens."""

from __future__ import annotations

import time

import httpx
import jwt

from app.config import settings

GITHUB_API_URL = "https://api.github.com"


def generate_app_jwt() -> str:
    """Create a signed JWT for the GitHub App (RS256, 10 min expiry)."""
    with open(settings.github_private_key_path, "rb") as key_file:
        private_key = key_file.read()

    now = int(time.time())
    payload = {
        "iat": now - 60,  # allow for clock drift
        "exp": now + (10 * 60),
        "iss": settings.github_app_id,
    }
    return jwt.encode(payload, private_key, algorithm="RS256")


async def get_installation_token(installation_id: str) -> str:
    """Exchange the App JWT for an installation-scoped access token.

    NOTE: installation tokens expire after 1 hour. This function does not
    cache the token — a naive cache (e.g. a module-level variable keyed only
    by installation_id) risks handing out an expired token to a caller,
    causing intermittent 401s from the GitHub API under load or on long-lived
    processes. If caching is added later, it must track the token's `expires_at`
    and only serve cached tokens with sufficient remaining validity, refreshing
    proactively (e.g. a few minutes before expiry) rather than reactively.
    """
    app_jwt = generate_app_jwt()

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{GITHUB_API_URL}/app/installations/{installation_id}/access_tokens",
            headers={
                "Authorization": f"Bearer {app_jwt}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        response.raise_for_status()
        return response.json()["token"]
