from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from sse_starlette.sse import EventSourceResponse

from .. import db
from ..events import bus
from ..models import Question, Upload

router = APIRouter()


@router.get("/events/{job_id}")
async def events(job_id: str, request: Request) -> EventSourceResponse:
    upload = await db.get_upload_full(job_id)
    if upload is None:
        raise HTTPException(status_code=404, detail="upload not found")

    return EventSourceResponse(_event_stream(job_id, request), ping=15)


def _sse(event: str, data: dict[str, Any]) -> dict[str, str]:
    return {"event": event, "data": json.dumps(data)}


def _question_extracted_event(question: Question) -> dict[str, Any]:
    return {
        "id": question.id,
        "number": question.number,
        "type": question.type,
        "stem": question.stem,
        "options": question.options,
    }


def _question_completed_event(question: Question) -> dict[str, Any]:
    return {
        "id": question.id,
        "number": question.number,
        "correct_answer": question.correct_answer,
        "reasoning": question.reasoning,
        "confidence": question.confidence,
        "flagged": question.flagged,
    }


def _has_answer(question: Question) -> bool:
    return (
        question.correct_answer is not None
        or question.reasoning is not None
        or question.confidence is not None
        or question.flagged
    )


async def _snapshot_events(upload: Upload) -> AsyncIterator[dict[str, str]]:
    yield _sse("stage_changed", {"state": upload.state})

    for question in upload.questions:
        yield _sse("question_extracted", _question_extracted_event(question))

    for question in upload.questions:
        if _has_answer(question):
            yield _sse("question_completed", _question_completed_event(question))

    if upload.state == "done":
        yield _sse("complete", {"upload_id": upload.id})
    elif upload.state == "error":
        yield _sse(
            "error",
            {
                "message": upload.error_message or "upload failed",
                "raw_notebooklm_response": upload.raw_notebooklm_response,
            },
        )


def _is_terminal_event(payload: dict[str, Any]) -> bool:
    return payload["event"] in {"complete", "error"}


async def _event_stream(job_id: str, request: Request) -> AsyncIterator[dict[str, str]]:
    queue = await bus.subscribe(job_id)
    try:
        # Subscribe before reading the snapshot so events published during the DB read
        # still arrive through the live queue. Duplicate events are harmless for clients.
        upload = await db.get_upload_full(job_id)
        if upload is None:
            yield _sse("error", {"message": "upload not found"})
            return

        async for event in _snapshot_events(upload):
            yield event
        if upload.state in {"done", "error"}:
            return

        while True:
            if await request.is_disconnected():
                return
            try:
                payload = await asyncio.wait_for(queue.get(), timeout=1)
            except TimeoutError:
                continue

            yield _sse(payload["event"], payload["data"])
            if _is_terminal_event(payload):
                return
    finally:
        await bus.unsubscribe(job_id, queue)
