from __future__ import annotations

import json
import uuid
from typing import Any, cast

from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from pydantic import BaseModel


class AgentJsonError(ValueError):
    """Raised when an ADK agent returns malformed structured JSON."""


class OneShotAgentRunner:
    """Run a no-tools ADK agent once and return its structured JSON payload."""

    def __init__(self, *, agent: Agent, app_name: str, output_key: str) -> None:
        self._agent = agent
        self._app_name = app_name
        self._output_key = output_key
        self._session_service = cast(
            Any,
            InMemorySessionService(),  # type: ignore[no-untyped-call]
        )
        self._runner = Runner(
            app_name=app_name,
            agent=agent,
            session_service=self._session_service,
        )

    async def run_json(self, parts: list[types.Part]) -> Any:
        user_id = "single-user"
        session_id = str(uuid.uuid4())
        await self._session_service.create_session(
            app_name=self._app_name,
            user_id=user_id,
            session_id=session_id,
        )

        final_text = ""
        state_value: Any = None
        async for event in self._runner.run_async(
            user_id=user_id,
            session_id=session_id,
            new_message=types.Content(role="user", parts=parts),
        ):
            if self._output_key in event.actions.state_delta:
                state_value = event.actions.state_delta[self._output_key]
            if event.is_final_response() and event.content and event.content.parts:
                final_text = "".join(
                    part.text or ""
                    for part in event.content.parts
                    if part.text and not part.thought
                )

        if state_value is not None:
            return state_value
        return _loads_json(final_text)


def parse_json_payload(payload: Any, schema: type[BaseModel] | None = None) -> Any:
    value = _loads_json(payload) if isinstance(payload, str) else payload
    if schema is None:
        return value
    return schema.model_validate(value).model_dump()


def _loads_json(text: str) -> Any:
    stripped = text.strip()
    if not stripped:
        raise AgentJsonError("agent returned an empty response")
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        start = min(
            (i for i in (stripped.find("{"), stripped.find("[")) if i != -1),
            default=-1,
        )
        end = max(stripped.rfind("}"), stripped.rfind("]"))
        if start == -1 or end == -1 or end < start:
            raise AgentJsonError("agent response did not contain JSON") from None
        return json.loads(stripped[start : end + 1])
