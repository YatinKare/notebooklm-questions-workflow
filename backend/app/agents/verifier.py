from __future__ import annotations

import json
from typing import Any, Literal, cast

from google.adk.agents import Agent
from google.genai import types
from pydantic import BaseModel, Field, field_validator

from ..config import settings
from ._runner import OneShotAgentRunner, parse_json_payload

VERIFIER_INSTRUCTION = """
You verify NotebookLM draft answers to extracted exam questions.

Return ONLY strict JSON matching this object shape:
{
  "correct_answer": <string or array>,
  "reasoning": <string>,
  "confidence": "high"|"low",
  "flagged": <boolean>
}

Input includes:
- question: extracted stem, type, and options
- notebooklm_answer: NotebookLM's draft answer
- notebooklm_justification: NotebookLM's stated support

Rules:
- Prefer the NotebookLM answer when the justification is coherent and fits the question.
- Correct obvious formatting issues, such as returning "B" instead of the full option text for MCQ.
- For SELECT_MULTIPLE and MATCHING, correct_answer may be an array.
- For other question types, use a string when possible.
- Use 1-2 concise sentences for reasoning.
- Set confidence to "high" only when the draft answer is supported by the provided source material.
- Set confidence to "low" and flagged to true if the draft is missing, ambiguous, contradictory,
  unsupported by the justification, or does not match the question/options.
- Set confidence to "low" and flagged to true if NotebookLM says the answer is not derived from,
  not found in, not supported by, or irrelevant to the provided sources, even when the answer is
  generally correct from outside knowledge.
- Do not call external tools or invent source evidence.
""".strip()

UNSUPPORTED_SOURCE_MARKERS = (
    "not derived from",
    "not found in",
    "not supported by",
    "not in the provided source",
    "not in the source",
    "outside knowledge",
    "outside the provided source",
    "provided sources do not",
    "irrelevant to the provided source",
    "irrelevance of the provided source",
)


class VerificationResult(BaseModel):
    correct_answer: str | list[str] | None = None
    reasoning: str = Field(min_length=1)
    confidence: Literal["high", "low"]
    flagged: bool

    @field_validator("reasoning")
    @classmethod
    def _clean_reasoning(cls, value: str) -> str:
        return value.strip()


verifier_agent = Agent(
    name="verifier_agent",
    model=settings.verifier_model,
    instruction=VERIFIER_INSTRUCTION,
    output_schema=VerificationResult,
    output_key="verification",
    tools=[],
    include_contents="none",
    generate_content_config=types.GenerateContentConfig(
        temperature=0,
        response_mime_type="application/json",
    ),
)


class AdkAnswerVerifier:
    def __init__(self, agent: Agent = verifier_agent) -> None:
        self._runner = OneShotAgentRunner(
            agent=agent,
            app_name="notebooklm_answer_verifier",
            output_key="verification",
        )

    async def verify(
        self,
        question: dict[str, Any],
        draft_answer: Any,
        justification: str,
    ) -> dict[str, Any]:
        payload = {
            "question": question,
            "notebooklm_answer": draft_answer,
            "notebooklm_justification": justification,
        }
        result = await self._runner.run_json(
            [
                types.Part.from_text(
                    text="Verify this NotebookLM draft answer:\n"
                    + json.dumps(payload, ensure_ascii=True)
                )
            ]
        )
        parsed = parse_json_payload(result, VerificationResult)
        if _mentions_unsupported_source(justification, str(parsed.get("reasoning", ""))):
            parsed["confidence"] = "low"
            parsed["flagged"] = True
        if parsed["confidence"] == "low":
            parsed["flagged"] = True
        return cast(dict[str, Any], parsed)


def _mentions_unsupported_source(*texts: str) -> bool:
    combined = " ".join(texts).lower()
    return any(marker in combined for marker in UNSUPPORTED_SOURCE_MARKERS)
