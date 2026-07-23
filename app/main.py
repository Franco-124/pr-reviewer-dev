"""FastAPI application — mounts routers and lifecycle hooks."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.webhooks import router as webhook_router
from app.config import settings
from app.logging_config import configure_logging
from app.storage.findings import init_findings_db
from app.storage.idempotency import init_db

configure_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── startup ────────────────────────────────────────────
    try:
        logger.info("Starting PR Review Agent service (v0.1.0)")
        logger.debug(f"Environment: LLM model={settings.llm_model_name}, host={settings.host}:{settings.port}")

        logger.info("Initializing idempotency database...")
        await init_db()
        logger.info("✓ Idempotency database initialized successfully")

        logger.info("Initializing findings database...")
        await init_findings_db()
        logger.info("✓ Findings database initialized successfully")

        logger.info("🚀 PR Review Agent service started successfully")
    except Exception as e:
        logger.exception("Failed to initialize service during startup")
        raise

    yield

    # ── shutdown ────────────────────────────────────────────
    logger.info("Shutting down PR Review Agent service")


app = FastAPI(
    title="PR Review Agent",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(webhook_router, prefix="/webhooks", tags=["webhooks"])

logger.info("FastAPI app configured")
