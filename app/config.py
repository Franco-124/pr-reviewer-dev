"""Application configuration via Pydantic Settings."""

from __future__ import annotations

import sys

from pydantic import ValidationError
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
    github_private_key_path: str
    github_app_installation_id: str

    # ── LLM (required) ──────────────────────────────────────
    openai_api_key: str
    llm_model_name: str = "gpt-4.1-mini"

    # ── Server ──────────────────────────────────────────────
    host: str = "0.0.0.0"
    port: int = 8000

    # ── Storage ─────────────────────────────────────────────
    db_path: str = "idempotency.db"


try:
    settings = Settings()  # singleton
except ValidationError as exc:
    missing = ", ".join(str(error["loc"][0]) for error in exc.errors() if error["type"] == "missing")
    sys.exit(f"Missing required environment variable(s): {missing}" if missing else str(exc))
