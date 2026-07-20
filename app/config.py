"""Application configuration via Pydantic Settings."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── GitHub App ──────────────────────────────────────────
    github_app_id: str = ""
    github_private_key_path: str = ""
    github_app_installation_id: str = ""
    github_webhook_secret: str = ""

    # ── Server ──────────────────────────────────────────────
    host: str = "0.0.0.0"
    port: int = 8000


settings = Settings()  # singleton
