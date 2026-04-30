from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import db
from .config import settings
from .routes import events, health, uploads


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await db.init_db()
    cleanup_task = asyncio.create_task(db.nightly_cleanup_loop())
    try:
        yield
    finally:
        cleanup_task.cancel()
        try:
            await cleanup_task
        except (asyncio.CancelledError, Exception):
            pass


app = FastAPI(title="notebooklm-questions-workflow", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.cors_origin] if settings.cors_origin != "*" else ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(uploads.router)
app.include_router(events.router)
