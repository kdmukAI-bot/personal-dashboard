from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator, Callable


class SSEBus:
    def __init__(self) -> None:
        self._subscribers: list[asyncio.Queue] = []

    def subscribe(self) -> tuple[asyncio.Queue, Callable[[], None]]:
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers.append(queue)

        def cleanup() -> None:
            try:
                self._subscribers.remove(queue)
            except ValueError:
                pass

        return queue, cleanup

    def publish(self, event: str, data: dict) -> None:
        payload = {"event": event, "data": data}
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                pass

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)


sse_bus = SSEBus()


async def event_stream_generator(queue: asyncio.Queue) -> AsyncIterator[dict]:
    while True:
        payload = await queue.get()
        yield {"event": payload["event"], "data": json.dumps(payload["data"])}
