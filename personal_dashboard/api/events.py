from __future__ import annotations

from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

from personal_dashboard.core.sse import event_stream_generator, sse_bus

router = APIRouter()


@router.get("/events")
async def events(request: Request):
    queue, cleanup = sse_bus.subscribe()

    async def gen():
        try:
            async for evt in event_stream_generator(queue):
                if await request.is_disconnected():
                    break
                yield evt
        finally:
            cleanup()

    return EventSourceResponse(gen(), ping=10)
