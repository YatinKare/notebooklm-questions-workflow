from __future__ import annotations

from typing import Any

import pytest

from app import db
from app.config import settings
from app.pipeline import prompts
from app.pipeline.stages import StageContext, run_pipeline


class StubExtractor:
    async def extract(self, image_bytes: bytes) -> list[dict[str, Any]]:
        return [
            {
                "number": 1,
                "type": "MCQ",
                "stem": "Which letter is correct?",
                "options": ["A", "B", "C", "D"],
            }
        ]


class EmptyExtractor:
    async def extract(self, image_bytes: bytes) -> list[dict[str, Any]]:
        return []


class MalformedNotebookLM:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def ask(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if len(self.prompts) == 1:
            return "not json"
        return "still not json"


class UnusedVerifier:
    def __init__(self) -> None:
        self.calls = 0

    async def verify(
        self,
        question: dict[str, Any],
        draft_answer: Any,
        justification: str,
    ) -> dict[str, Any]:
        self.calls += 1
        return {
            "correct_answer": draft_answer,
            "reasoning": justification,
            "confidence": "low",
            "flagged": True,
        }


@pytest.mark.asyncio
async def test_pipeline_strict_json_retry_persists_raw_response(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "app.db"))
    await db.init_db()
    upload_id = await db.create_upload()
    nlm = MalformedNotebookLM()
    verifier = UnusedVerifier()

    await run_pipeline(
        StageContext(
            upload_id=upload_id,
            image_bytes=b"fake-image",
            extractor=StubExtractor(),
            nlm=nlm,
            verifier=verifier,
        )
    )

    upload = await db.get_upload_full(upload_id)
    assert upload is not None
    assert upload.state == "error"
    assert upload.error_message is not None
    assert "parse failed after retry" in upload.error_message
    assert upload.raw_notebooklm_response == "still not json"
    assert len(nlm.prompts) == 2
    assert prompts.STRICT_JSON_PREAMBLE.strip() not in nlm.prompts[0]
    assert nlm.prompts[1].startswith(prompts.STRICT_JSON_PREAMBLE)
    assert verifier.calls == 0


@pytest.mark.asyncio
async def test_pipeline_errors_when_extractor_finds_no_questions(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "app.db"))
    await db.init_db()
    upload_id = await db.create_upload()
    nlm = MalformedNotebookLM()
    verifier = UnusedVerifier()

    await run_pipeline(
        StageContext(
            upload_id=upload_id,
            image_bytes=b"blank-image",
            extractor=EmptyExtractor(),
            nlm=nlm,
            verifier=verifier,
        )
    )

    upload = await db.get_upload_full(upload_id)
    assert upload is not None
    assert upload.state == "error"
    assert upload.error_message == "No questions were detected in the uploaded image."
    assert upload.raw_notebooklm_response == (
        "Extractor returned no questions; NotebookLM was not queried."
    )
    assert upload.questions == []
    assert nlm.prompts == []
    assert verifier.calls == 0
