from __future__ import annotations

from io import BytesIO

from google.adk.agents import Agent
from google.genai import types
from PIL import Image
from pydantic import BaseModel, Field, field_validator

from ..config import settings
from ..models import QuestionType
from ._runner import OneShotAgentRunner, parse_json_payload

QUESTION_TYPES: tuple[str, ...] = (
    "TF",
    "MCQ",
    "SELECT_MULTIPLE",
    "MATCHING",
    "SHORT_ANSWER",
    "SHORT_ANSWER_MATH",
    "LONG_ANSWER",
)

EXTRACTOR_INSTRUCTION = """
You extract exam questions from screenshots.

Return ONLY strict JSON. Do not use markdown, comments, prose, or code fences.
The JSON must be an array of question objects:
[
  {"number": 1, "type": "MCQ", "stem": "Question text", "options": ["A choice", "B choice"]},
  {"number": 2, "type": "TF", "stem": "Question text"}
]

Rules:
- Extract 3-5 questions when present, preserving the visible numbering.
- Use exactly one of these type values: TF, MCQ, SELECT_MULTIPLE, MATCHING,
  SHORT_ANSWER, SHORT_ANSWER_MATH, LONG_ANSWER.
- Put the question prompt in "stem"; do not include answer choices in the stem.
- For MCQ and SELECT_MULTIPLE, "options" must be an array of choice text in display order.
- For TF, include options only if True/False choices are explicitly printed.
- For MATCHING, put each visible match item/choice as one option string.
- For short or long answer questions, omit "options" unless choices are printed.
- If text is ambiguous, still extract the best readable version and choose the closest type.
- If there are no exam questions, return [].
""".strip()


class ExtractedQuestion(BaseModel):
    number: int = Field(ge=1)
    type: QuestionType
    stem: str = Field(min_length=1)
    options: list[str] | None = None

    @field_validator("stem")
    @classmethod
    def _clean_stem(cls, value: str) -> str:
        return value.strip()

    @field_validator("options")
    @classmethod
    def _clean_options(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        cleaned = [item.strip() for item in value if item.strip()]
        return cleaned or None


extractor_agent = Agent(
    name="extractor_agent",
    model=settings.extractor_model,
    instruction=EXTRACTOR_INSTRUCTION,
    output_schema=list[ExtractedQuestion],
    output_key="questions",
    tools=[],
    include_contents="none",
    generate_content_config=types.GenerateContentConfig(
        temperature=0,
        response_mime_type="application/json",
    ),
)


class AdkQuestionExtractor:
    def __init__(self, agent: Agent = extractor_agent) -> None:
        self._runner = OneShotAgentRunner(
            agent=agent,
            app_name="notebooklm_question_extractor",
            output_key="questions",
        )

    async def extract(self, image_bytes: bytes) -> list[dict[str, object]]:
        mime_type = _detect_image_mime_type(image_bytes)
        payload = await self._runner.run_json(
            [
                types.Part.from_text(text="Extract the exam questions from this screenshot."),
                types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
            ]
        )
        questions = parse_json_payload(payload)
        if not isinstance(questions, list):
            raise ValueError("extractor_agent returned a non-array payload")
        return [
            ExtractedQuestion.model_validate(question).model_dump(exclude_none=True)
            for question in questions
        ]


def _detect_image_mime_type(image_bytes: bytes) -> str:
    with Image.open(BytesIO(image_bytes)) as image:
        fmt = (image.format or "").lower()
    if fmt in {"jpeg", "jpg"}:
        return "image/jpeg"
    if fmt == "png":
        return "image/png"
    if fmt == "webp":
        return "image/webp"
    if fmt == "gif":
        return "image/gif"
    return "application/octet-stream"
