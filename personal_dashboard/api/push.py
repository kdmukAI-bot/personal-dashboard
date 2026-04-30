from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from personal_dashboard.config import settings
from personal_dashboard.database import get_core_db
from personal_dashboard.models.subscription import PushSubscription

router = APIRouter(prefix="/api/push")


class SubscribeKeys(BaseModel):
    p256dh: str
    auth: str


class SubscribeBody(BaseModel):
    endpoint: str
    keys: SubscribeKeys
    user_agent: str | None = None


class UnsubscribeBody(BaseModel):
    endpoint: str


@router.get("/vapid-public-key")
async def vapid_public_key():
    return {"public_key": settings.vapid_public_key}


@router.post("/subscribe")
async def subscribe(
    body: SubscribeBody,
    request: Request,
    db: AsyncSession = Depends(get_core_db),
):
    existing = await db.scalar(
        select(PushSubscription).where(PushSubscription.endpoint == body.endpoint)
    )
    if existing is not None:
        return {"id": existing.id, "created": False}

    user_agent = body.user_agent or request.headers.get("user-agent")
    sub = PushSubscription(
        endpoint=body.endpoint,
        p256dh_key=body.keys.p256dh,
        auth_key=body.keys.auth,
        user_agent=user_agent,
    )
    db.add(sub)
    await db.commit()
    await db.refresh(sub)
    return {"id": sub.id, "created": True}


@router.post("/unsubscribe")
async def unsubscribe(
    body: UnsubscribeBody,
    db: AsyncSession = Depends(get_core_db),
):
    existing = await db.scalar(
        select(PushSubscription).where(PushSubscription.endpoint == body.endpoint)
    )
    if existing is None:
        return {"deleted": False}
    await db.delete(existing)
    await db.commit()
    return {"deleted": True}


@router.post("/test")
async def test_send(request: Request):
    core = request.app.state.core
    await core.notify(
        "Test",
        "If you see this, push is working",
        source="manual",
    )
    return {"ok": True}
