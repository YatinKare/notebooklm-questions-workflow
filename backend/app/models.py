from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

QuestionType = Literal[
    "TF",
    "MCQ",
    "SELECT_MULTIPLE",
    "MATCHING",
    "SHORT_ANSWER",
    "SHORT_ANSWER_MATH",
    "LONG_ANSWER",
]

UploadState = Literal["extracting", "querying", "parsing", "verifying", "done", "error"]
Confidence = Literal["high", "low"]


class Question(BaseModel):
    id: str
    upload_id: str
    number: int
    type: QuestionType
    stem: str
    options: list[str] | None = None
    correct_answer: str | list[str] | None = None
    reasoning: str | None = None
    confidence: Confidence | None = None
    flagged: bool = False


class Upload(BaseModel):
    id: str
    created_at: datetime
    state: UploadState
    error_message: str | None = None
    raw_notebooklm_response: str | None = None
    questions: list[Question] = Field(default_factory=list)


class UploadSummary(BaseModel):
    id: str
    created_at: datetime
    state: UploadState
    question_count: int


class SSEEvent(BaseModel):
    event: Literal[
        "stage_changed", "question_extracted", "question_completed", "complete", "error"
    ]
    data: dict[str, Any]
