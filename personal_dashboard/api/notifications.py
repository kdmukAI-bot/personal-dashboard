from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from personal_dashboard.database import get_core_db
from personal_dashboard.models.notification import Notification

router = APIRouter()

_PAGE_SIZE = 50


@router.get("/widgets/notifications")
async def notifications_widget(
    request: Request,
    db: AsyncSession = Depends(get_core_db),
):
    stmt = select(Notification).order_by(Notification.sent_at.desc()).limit(5)
    rows = list((await db.scalars(stmt)).all())
    templates = request.app.state.templates
    return templates.TemplateResponse(
        request,
        "notifications/widget.html",
        {"notifications": rows},
    )


@router.get("/notifications")
async def notifications_detail(
    request: Request,
    page: int = Query(1, ge=1),
    db: AsyncSession = Depends(get_core_db),
):
    total = await db.scalar(select(func.count()).select_from(Notification)) or 0
    total_pages = max(1, (total + _PAGE_SIZE - 1) // _PAGE_SIZE)
    page = min(page, total_pages)
    offset = (page - 1) * _PAGE_SIZE
    stmt = (
        select(Notification)
        .order_by(Notification.sent_at.desc())
        .offset(offset)
        .limit(_PAGE_SIZE)
    )
    rows = list((await db.scalars(stmt)).all())
    templates = request.app.state.templates
    return templates.TemplateResponse(
        request,
        "notifications/detail.html",
        {"notifications": rows, "page": page, "total_pages": total_pages},
    )
