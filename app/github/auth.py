"""GitHub App authentication — JWT generation & installation access tokens."""

from __future__ import annotations

import logging
import time

import httpx
import jwt

from app.config import settings

logger = logging.getLogger(__name__)

GITHUB_API_URL = "https://api.github.com"


def _load_private_key() -> str:
    """Load the App's PEM private key from an env var (Render-friendly) or a local file."""
    if settings.github_private_key:
        logger.debug("Loading GitHub App private key from environment variable")
        return settings.github_private_key

    logger.debug(f"Loading GitHub App private key from file: {settings.github_private_key_path}")
    try:
        with open(settings.github_private_key_path, "rb") as key_file:
            key_data = key_file.read()
        logger.debug(f"✓ Private key loaded successfully ({len(key_data)} bytes)")
        return key_data
    except FileNotFoundError:
        logger.error(f"✗ Private key file not found: {settings.github_private_key_path}")
        raise
    except Exception as e:
        logger.error(f"✗ Failed to read private key file: {e}")
        raise


def generate_app_jwt() -> str:
    """Create a signed JWT for the GitHub App (RS256, 10 min expiry)."""
    logger.debug(f"Generating GitHub App JWT (app_id={settings.github_app_id})")
    try:
        private_key = _load_private_key()

        now = int(time.time())
        payload = {
            "iat": now - 60,  # allow for clock drift
            "exp": now + (10 * 60),
            "iss": settings.github_app_id,
        }
        token = jwt.encode(payload, private_key, algorithm="RS256")
        logger.debug("✓ GitHub App JWT generated successfully")
        return token
    except Exception as e:
        logger.error(f"✗ Failed to generate GitHub App JWT: {type(e).__name__}: {e}")
        raise


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
    logger.debug(f"Exchanging App JWT for installation token (installation_id={installation_id})")
    try:
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
            token_data = response.json()
            logger.debug(f"✓ Installation token obtained (expires_at={token_data.get('expires_at', 'unknown')})")
            return token_data["token"]
    except httpx.HTTPStatusError as e:
        logger.error(
            f"✗ GitHub API error exchanging JWT for token: "
            f"status={e.response.status_code}, response={e.response.text[:200]}"
        )
        raise
    except Exception as e:
        logger.error(f"✗ Failed to get installation token: {type(e).__name__}: {e}")
        raise
