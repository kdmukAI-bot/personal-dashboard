from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from personal_dashboard.core.bearer_auth import require_bearer_token
from personal_dashboard.core import web_push

router = APIRouter()


class NotifyBody(BaseModel):
    title: str
    body: str | None = None
    image_url: str | None = None
    click_url: str | None = None
    source: str | None = None


@router.post("/api/notify", dependencies=[Depends(require_bearer_token)])
async def notify(body: NotifyBody, request: Request):
    delivered, failed = await web_push.dispatch(
        body.title,
        body.body,
        image_url=body.image_url,
        click_url=body.click_url,
        source=body.source,
    )
    return {"delivered": delivered, "failed": failed}
