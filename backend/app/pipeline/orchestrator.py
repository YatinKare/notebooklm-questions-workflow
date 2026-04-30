from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from .stages import Extractor, NotebookLMClient, StageContext, Verifier, run_pipeline

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _Job:
    upload_id: str
    image_bytes: bytes


class PipelineOrchestrator:
    """Single-worker asyncio queue that drives uploads through the pipeline."""

    def __init__(
        self, extractor: Extractor, nlm: NotebookLMClient, verifier: Verifier
    ) -> None:
        self.extractor = extractor
        self.nlm = nlm
        self.verifier = verifier
        self._queue: asyncio.Queue[_Job] = asyncio.Queue()
        self._worker: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self._run_worker(), name="pipeline-worker")

    async def stop(self) -> None:
        if self._worker is None:
            return
        self._worker.cancel()
        try:
            await self._worker
        except (asyncio.CancelledError, Exception):
            pass
        self._worker = None

    async def enqueue(self, upload_id: str, image_bytes: bytes) -> None:
        await self._queue.put(_Job(upload_id=upload_id, image_bytes=image_bytes))

    async def join(self) -> None:
        """Wait until all queued jobs have been processed (used by tests)."""
        await self._queue.join()

    async def _run_worker(self) -> None:
        while True:
            job = await self._queue.get()
            try:
                ctx = StageContext(
                    upload_id=job.upload_id,
                    image_bytes=job.image_bytes,
                    extractor=self.extractor,
                    nlm=self.nlm,
                    verifier=self.verifier,
                )
                await run_pipeline(ctx)
            except Exception:
                logger.exception("pipeline crashed for %s", job.upload_id)
            finally:
                self._queue.task_done()


_orchestrator: PipelineOrchestrator | None = None


def set_orchestrator(o: PipelineOrchestrator | None) -> None:
    global _orchestrator
    _orchestrator = o


def get_orchestrator() -> PipelineOrchestrator:
    if _orchestrator is None:
        raise RuntimeError("orchestrator not initialized")
    return _orchestrator
