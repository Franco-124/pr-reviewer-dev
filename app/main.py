"""FastAPI application — mounts routers and lifecycle hooks."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.webhooks import router as webhook_router
from app.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── startup ────────────────────────────────────────────
    yield
    # ── shutdown ────────────────────────────────────────────


app = FastAPI(
    title="PR Review Agent",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(webhook_router, prefix="/webhooks", tags=["webhooks"])
