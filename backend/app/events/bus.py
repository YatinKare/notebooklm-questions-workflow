from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any

# In-process pub/sub: per-job_id fan-out to N subscriber queues.
_subscribers: dict[str, set[asyncio.Queue[dict[str, Any]]]] = defaultdict(set)
_lock = asyncio.Lock()


async def subscribe(job_id: str) -> asyncio.Queue[dict[str, Any]]:
    q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    async with _lock:
        _subscribers[job_id].add(q)
    return q


async def unsubscribe(job_id: str, q: asyncio.Queue[dict[str, Any]]) -> None:
    async with _lock:
        _subscribers[job_id].discard(q)
        if not _subscribers[job_id]:
            _subscribers.pop(job_id, None)


async def publish(job_id: str, event: str, data: dict[str, Any]) -> None:
    payload = {"event": event, "data": data}
    async with _lock:
        targets = list(_subscribers.get(job_id, ()))
    for q in targets:
        await q.put(payload)
