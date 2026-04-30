from __future__ import annotations

import asyncio
import json
import logging
import shlex
import shutil
import sys
from contextlib import AsyncExitStack
from datetime import timedelta
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import CallToolResult

from ..config import settings

logger = logging.getLogger(__name__)


class NotebookLMError(RuntimeError):
    """Raised when the NotebookLM MCP subprocess or tool call fails."""


class NotebookLMMCPClient:
    """Async MCP stdio client for the `notebooklm-mcp-cli` server."""

    def __init__(
        self,
        *,
        notebook_id: str = settings.notebook_id,
        cookie_path: str = settings.nlm_cookie_path,
        query_timeout: float = settings.notebooklm_query_timeout,
        command: str = settings.nlm_mcp_command,
        command_args: str = settings.nlm_mcp_args,
    ) -> None:
        self.notebook_id = notebook_id
        self.cookie_path = cookie_path
        self.query_timeout = query_timeout
        self.command = command
        self.command_args = command_args
        self._lock = asyncio.Lock()
        self._stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None

    @property
    def is_running(self) -> bool:
        return self._session is not None

    async def start(self) -> None:
        async with self._lock:
            await self._ensure_started_locked()

    async def stop(self) -> None:
        async with self._lock:
            await self._stop_locked()

    async def ask(self, prompt: str) -> str:
        """Ask the configured NotebookLM notebook and return the answer text."""
        if not prompt.strip():
            raise ValueError("NotebookLM prompt must not be empty")

        async with self._lock:
            await self._ensure_started_locked()
            try:
                return await self._call_notebook_query_locked(prompt)
            except Exception as first_error:
                logger.warning(
                    "NotebookLM MCP call failed; restarting subprocess once: %s",
                    first_error,
                )
                await self._stop_locked()
                await self._ensure_started_locked()
                try:
                    return await self._call_notebook_query_locked(prompt)
                except Exception as second_error:
                    raise NotebookLMError(
                        f"NotebookLM MCP call failed after restart: {second_error}"
                    ) from second_error

    async def health_check(self) -> bool:
        """Return true when the MCP session responds to a lightweight tools call."""
        async with self._lock:
            if self._session is None:
                return False
            try:
                await asyncio.wait_for(self._session.list_tools(), timeout=5)
                return True
            except Exception:
                logger.exception("NotebookLM MCP health check failed")
                return False

    async def _ensure_started_locked(self) -> None:
        if self._session is not None:
            return
        if not self.notebook_id:
            raise NotebookLMError("NOTEBOOK_ID is not configured")

        command, args = self._server_command()
        env = self._server_env()
        server = StdioServerParameters(command=command, args=args, env=env)

        stack = AsyncExitStack()
        try:
            read_stream, write_stream = await stack.enter_async_context(
                stdio_client(server, errlog=sys.stderr)
            )
            session = await stack.enter_async_context(ClientSession(read_stream, write_stream))
            await asyncio.wait_for(session.initialize(), timeout=30)
        except Exception:
            await stack.aclose()
            raise

        self._stack = stack
        self._session = session
        logger.info("started notebooklm-mcp subprocess: %s %s", command, " ".join(args))

    async def _stop_locked(self) -> None:
        self._session = None
        if self._stack is not None:
            await self._stack.aclose()
            self._stack = None

    async def _call_notebook_query_locked(self, prompt: str) -> str:
        if self._session is None:
            raise NotebookLMError("NotebookLM MCP session is not started")

        timeout = max(self.query_timeout, 1.0)
        result = await asyncio.wait_for(
            self._session.call_tool(
                "notebook_query",
                {
                    "notebook_id": self.notebook_id,
                    "query": prompt,
                    "timeout": timeout,
                },
                read_timeout_seconds=timedelta(seconds=timeout + 15),
            ),
            timeout=timeout + 30,
        )
        return _extract_answer(result)

    def _server_command(self) -> tuple[str, list[str]]:
        if self.command:
            return self.command, shlex.split(self.command_args)
        if shutil.which("notebooklm-mcp"):
            return "notebooklm-mcp", []
        return "uvx", ["--from", "notebooklm-mcp-cli", "notebooklm-mcp"]

    def _server_env(self) -> dict[str, str]:
        env: dict[str, str] = {
            "NOTEBOOKLM_QUERY_TIMEOUT": str(self.query_timeout),
        }
        cookie_path = Path(self.cookie_path).expanduser()
        if not cookie_path.exists():
            raise NotebookLMError(f"NLM_COOKIE_PATH does not exist: {cookie_path}")

        profile_env = _profile_env_from_cookie_path(cookie_path)
        if profile_env:
            env.update(profile_env)
        else:
            env["NOTEBOOKLM_COOKIES"] = _load_cookie_header(str(cookie_path))
        return env


def _profile_env_from_cookie_path(cookie_path: Path) -> dict[str, str]:
    """Map a CLI profile cookie path to the env vars the MCP server already supports."""
    if cookie_path.name != "cookies.json":
        return {}
    profile_dir = cookie_path.parent
    profiles_dir = profile_dir.parent
    storage_dir = profiles_dir.parent
    if profiles_dir.name != "profiles":
        return {}
    env = {
        "NOTEBOOKLM_MCP_CLI_PATH": str(storage_dir),
    }
    if profile_dir.name:
        env["NLM_PROFILE"] = profile_dir.name
    return env


def _extract_answer(result: CallToolResult) -> str:
    payload = _result_payload(result)
    if result.isError:
        raise NotebookLMError(_payload_error(payload) or "notebook_query returned an error")

    if isinstance(payload, dict):
        if payload.get("status") == "error":
            raise NotebookLMError(_payload_error(payload) or "notebook_query failed")
        for key in ("answer", "response", "text", "message"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value
        return json.dumps(payload, ensure_ascii=True)

    if isinstance(payload, str) and payload.strip():
        return payload
    raise NotebookLMError("notebook_query returned an empty response")


def _result_payload(result: CallToolResult) -> Any:
    if result.structuredContent is not None:
        return result.structuredContent

    texts: list[str] = []
    for item in result.content:
        text = getattr(item, "text", None)
        if isinstance(text, str):
            texts.append(text)
    text_payload = "\n".join(texts).strip()
    if not text_payload:
        return ""
    try:
        return json.loads(text_payload)
    except json.JSONDecodeError:
        return text_payload


def _payload_error(payload: Any) -> str | None:
    if isinstance(payload, dict):
        parts = [str(payload[key]) for key in ("error", "hint") if payload.get(key)]
        return " ".join(parts) or None
    if isinstance(payload, str):
        return payload
    return None


def _load_cookie_header(cookie_path: str) -> str:
    path = Path(cookie_path).expanduser()
    if not path.exists():
        raise NotebookLMError(f"NLM_COOKIE_PATH does not exist: {path}")
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise NotebookLMError(f"NLM_COOKIE_PATH is empty: {path}")

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return _clean_cookie_header(text)

    cookie_header = _cookie_header_from_json(payload)
    if not cookie_header:
        raise NotebookLMError(
            "NLM_COOKIE_PATH must contain a raw cookie header or JSON with cookies"
        )
    return cookie_header


def _clean_cookie_header(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) == 1 and lines[0].lower().startswith("cookie:"):
        return lines[0].split(":", 1)[1].strip()
    return "; ".join(line.removeprefix("cookie:").strip() for line in lines)


def _cookie_header_from_json(payload: Any) -> str:
    if isinstance(payload, str):
        return _clean_cookie_header(payload)
    if isinstance(payload, list):
        return _join_cookie_items(payload)
    if not isinstance(payload, dict):
        return ""

    for key in ("cookie_header", "cookieHeader", "NOTEBOOKLM_COOKIES"):
        value = payload.get(key)
        if isinstance(value, str):
            return _clean_cookie_header(value)

    cookies = payload.get("cookies")
    if isinstance(cookies, str):
        return _clean_cookie_header(cookies)
    if isinstance(cookies, list):
        return _join_cookie_items(cookies)
    if isinstance(cookies, dict):
        return _join_cookie_mapping(cookies)

    return _join_cookie_mapping(payload)


def _join_cookie_items(items: list[Any]) -> str:
    pairs: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        value = item.get("value")
        if isinstance(name, str) and value is not None:
            pairs.append(f"{name}={value}")
    return "; ".join(pairs)


def _join_cookie_mapping(cookies: dict[str, Any]) -> str:
    pairs: list[str] = []
    for name, value in cookies.items():
        if name in {"csrf_token", "session_id", "email", "extracted_at"}:
            continue
        if isinstance(value, dict):
            value = value.get("value")
        if isinstance(value, str) and value:
            pairs.append(f"{name}={value}")
    return "; ".join(pairs)


_notebooklm_client: NotebookLMMCPClient | None = None


def set_notebooklm_client(client: NotebookLMMCPClient | None) -> None:
    global _notebooklm_client
    _notebooklm_client = client


def get_notebooklm_client() -> NotebookLMMCPClient:
    if _notebooklm_client is None:
        raise RuntimeError("NotebookLM MCP client not initialized")
    return _notebooklm_client
