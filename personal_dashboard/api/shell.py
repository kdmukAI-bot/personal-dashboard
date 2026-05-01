from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from personal_dashboard.config import settings
from personal_dashboard.database import get_core_db
from personal_dashboard.models.notification import Notification

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/")
async def dashboard(request: Request, db: AsyncSession = Depends(get_core_db)):
    templates = request.app.state.templates
    loaded_modules = getattr(request.app.state, "loaded_modules", [])

    notifications_rows = list(
        (
            await db.scalars(
                select(Notification).order_by(Notification.sent_at.desc()).limit(5)
            )
        ).all()
    )

    rendered_widgets: dict[str, str] = {}
    for lm in loaded_modules:
        try:
            data = await lm.library.get_data()
            tpl = templates.env.get_template(f"{lm.name}/widget.html")
            rendered_widgets[lm.name] = tpl.render(request=request, data=data)
        except Exception:
            logger.exception("module %s: pre-render of widget failed", lm.name)
            rendered_widgets[lm.name] = ""

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "vapid_public_key": settings.vapid_public_key,
            "loaded_modules": loaded_modules,
            "notifications": notifications_rows,
            "rendered_widgets": rendered_widgets,
        },
    )
