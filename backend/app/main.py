from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import db
from .agents.extractor import AdkQuestionExtractor
from .agents.verifier import AdkAnswerVerifier
from .config import settings
from .notebooklm.client import NotebookLMMCPClient, set_notebooklm_client
from .pipeline.orchestrator import PipelineOrchestrator, set_orchestrator
from .routes import events, health, uploads


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await db.init_db()
    cleanup_task = asyncio.create_task(db.nightly_cleanup_loop())
    nlm_client = NotebookLMMCPClient()
    orchestrator: PipelineOrchestrator | None = None
    try:
        await nlm_client.start()
        set_notebooklm_client(nlm_client)
        orchestrator = PipelineOrchestrator(
            extractor=AdkQuestionExtractor(),
            nlm=nlm_client,
            verifier=AdkAnswerVerifier(),
        )
        set_orchestrator(orchestrator)
        await orchestrator.start()
        yield
    finally:
        set_orchestrator(None)
        if orchestrator is not None:
            await orchestrator.stop()
        set_notebooklm_client(None)
        await nlm_client.stop()
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
