"""Application configuration via Pydantic Settings."""

from __future__ import annotations

import sys

from pydantic import ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── GitHub App (required) ──────────────────────────────
    github_app_id: str
    github_webhook_secret: str
    github_app_installation_id: str

    # Exactly one of these two must be set: `github_private_key` holds the
    # PEM contents directly (for PaaS deploys with an ephemeral filesystem,
    # e.g. Render — set it as an env var), `github_private_key_path` points
    # to a .pem file on disk (for local development).
    github_private_key: str = ""
    github_private_key_path: str = ""

    # ── LLM (required) ──────────────────────────────────────
    openai_api_key: str
    llm_model_name: str = "gpt-4.1-mini"

    # ── Server ──────────────────────────────────────────────
    host: str = "0.0.0.0"
    port: int = 8000

    # ── Storage ─────────────────────────────────────────────
    db_path: str = "idempotency.db"

    @model_validator(mode="after")
    def _require_private_key_source(self) -> Settings:
        if not self.github_private_key and not self.github_private_key_path:
            raise ValueError("set either GITHUB_PRIVATE_KEY or GITHUB_PRIVATE_KEY_PATH")
        return self


try:
    settings = Settings()  # singleton
except ValidationError as exc:
    missing = ", ".join(str(error["loc"][0]) for error in exc.errors() if error["type"] == "missing")
    if missing:
        sys.exit(f"Missing required environment variable(s): {missing}")
    sys.exit("; ".join(error["msg"] for error in exc.errors()))
