from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Protocol, TypeVar

from .. import db
from ..events import bus
from ..models import UploadState
from . import prompts

logger = logging.getLogger(__name__)
T = TypeVar("T")

TRANSIENT_ERROR_MARKERS = (
    "503",
    "UNAVAILABLE",
    "high demand",
    "temporarily unavailable",
    "try again later",
)
MAX_TRANSIENT_ATTEMPTS = 4


class Extractor(Protocol):
    async def extract(self, image_bytes: bytes) -> list[dict[str, Any]]: ...


class NotebookLMClient(Protocol):
    async def ask(self, prompt: str) -> str: ...


class Verifier(Protocol):
    async def verify(
        self,
        question: dict[str, Any],
        draft_answer: Any,
        justification: str,
    ) -> dict[str, Any]: ...


@dataclass
class StageContext:
    upload_id: str
    image_bytes: bytes
    extractor: Extractor
    nlm: NotebookLMClient
    verifier: Verifier


@dataclass
class _ParsedAnswer:
    answer: Any
    justification: str


async def _transition(upload_id: str, state: UploadState, **kwargs: Any) -> None:
    await db.update_state(upload_id, state, **kwargs)
    await bus.publish(upload_id, "stage_changed", {"state": state})


def _is_transient_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(marker.lower() in message for marker in TRANSIENT_ERROR_MARKERS)


async def _retry_transient(label: str, func: Callable[[], Awaitable[T]]) -> T:
    delay = 2.0
    for attempt in range(1, MAX_TRANSIENT_ATTEMPTS + 1):
        try:
            return await func()
        except Exception as exc:
            if attempt == MAX_TRANSIENT_ATTEMPTS or not _is_transient_error(exc):
                raise
            logger.warning(
                "%s failed with transient error on attempt %s/%s; retrying in %.1fs: %s",
                label,
                attempt,
                MAX_TRANSIENT_ATTEMPTS,
                delay,
                exc,
            )
            await asyncio.sleep(delay)
            delay *= 2
    raise RuntimeError(f"{label} retry loop exited unexpectedly")


async def _extract(ctx: StageContext) -> list[dict[str, Any]]:
    questions = await _retry_transient(
        "extractor",
        lambda: ctx.extractor.extract(ctx.image_bytes),
    )
    qids = await db.insert_questions(ctx.upload_id, questions)
    items: list[dict[str, Any]] = []
    for qid, q in zip(qids, questions, strict=True):
        item = {
            "id": qid,
            "number": q["number"],
            "type": q["type"],
            "stem": q["stem"],
            "options": q.get("options"),
        }
        items.append(item)
        await bus.publish(ctx.upload_id, "question_extracted", item)
    return items


async def _query(ctx: StageContext, items: list[dict[str, Any]], *, strict: bool) -> str:
    prompt = prompts.build_notebooklm_prompt(items, strict=strict)
    return await _retry_transient("notebooklm query", lambda: ctx.nlm.ask(prompt))


def _parse_response(raw: str) -> dict[int, _ParsedAnswer]:
    text = raw.strip()
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end < start:
        raise ValueError("no JSON array found in response")
    payload = json.loads(text[start : end + 1])
    if not isinstance(payload, list):
        raise ValueError("parsed JSON is not an array")
    out: dict[int, _ParsedAnswer] = {}
    for entry in payload:
        if not isinstance(entry, dict) or "q" not in entry or "answer" not in entry:
            raise ValueError("malformed entry in JSON array")
        out[int(entry["q"])] = _ParsedAnswer(
            answer=entry["answer"],
            justification=str(entry.get("justification", "")),
        )
    return out


async def _verify_one(
    ctx: StageContext,
    item: dict[str, Any],
    parsed: dict[int, _ParsedAnswer],
) -> None:
    p = parsed.get(item["number"])
    if p is None:
        result: dict[str, Any] = {
            "correct_answer": None,
            "reasoning": "NotebookLM did not return an answer for this question.",
            "confidence": "low",
            "flagged": True,
        }
    else:
        result = await _retry_transient(
            f"verifier q{item['number']}",
            lambda: ctx.verifier.verify(item, p.answer, p.justification),
        )

    await db.update_question_answer(
        item["id"],
        correct_answer=result.get("correct_answer"),
        reasoning=result.get("reasoning"),
        confidence=result.get("confidence"),
        flagged=bool(result.get("flagged", False)),
    )
    await bus.publish(
        ctx.upload_id,
        "question_completed",
        {
            "id": item["id"],
            "number": item["number"],
            "correct_answer": result.get("correct_answer"),
            "reasoning": result.get("reasoning"),
            "confidence": result.get("confidence"),
            "flagged": bool(result.get("flagged", False)),
        },
    )


async def run_pipeline(ctx: StageContext) -> None:
    """Drive a single upload through extracting → querying → parsing → verifying → done.

    On parse failure, retry once with a strict-JSON preamble. A second failure marks
    the upload as `error` and persists the raw NotebookLM response.
    """
    raw_last: str = ""
    try:
        await _transition(ctx.upload_id, "extracting")
        items = await _extract(ctx)
        if not items:
            msg = "No questions were detected in the uploaded image."
            raw_last = "Extractor returned no questions; NotebookLM was not queried."
            await db.update_state(
                ctx.upload_id,
                "error",
                error_message=msg,
                raw_notebooklm_response=raw_last,
            )
            await bus.publish(ctx.upload_id, "stage_changed", {"state": "error"})
            await bus.publish(
                ctx.upload_id,
                "error",
                {"message": msg, "raw_notebooklm_response": raw_last},
            )
            return

        await _transition(ctx.upload_id, "querying")
        raw_last = await _query(ctx, items, strict=False)

        await _transition(ctx.upload_id, "parsing")
        try:
            parsed = _parse_response(raw_last)
        except Exception as first_err:
            logger.info("parse failed, retrying with strict preamble: %s", first_err)
            await _transition(ctx.upload_id, "querying")
            raw_last = await _query(ctx, items, strict=True)
            await _transition(ctx.upload_id, "parsing")
            try:
                parsed = _parse_response(raw_last)
            except Exception as second_err:
                msg = f"parse failed after retry: {second_err}"
                await db.update_state(
                    ctx.upload_id,
                    "error",
                    error_message=msg,
                    raw_notebooklm_response=raw_last,
                )
                await bus.publish(ctx.upload_id, "stage_changed", {"state": "error"})
                await bus.publish(ctx.upload_id, "error", {"message": msg})
                return

        await _transition(ctx.upload_id, "verifying")
        await asyncio.gather(*(_verify_one(ctx, item, parsed) for item in items))

        await _transition(ctx.upload_id, "done")
        await bus.publish(ctx.upload_id, "complete", {"upload_id": ctx.upload_id})
    except Exception as e:
        logger.exception("pipeline crashed for %s", ctx.upload_id)
        await db.update_state(
            ctx.upload_id,
            "error",
            error_message=str(e),
            raw_notebooklm_response=raw_last or None,
        )
        await bus.publish(ctx.upload_id, "stage_changed", {"state": "error"})
        await bus.publish(ctx.upload_id, "error", {"message": str(e)})
