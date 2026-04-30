from __future__ import annotations

from fastapi import APIRouter, Request

from personal_dashboard.config import settings

router = APIRouter()


@router.get("/")
async def dashboard(request: Request):
    templates = request.app.state.templates
    loaded_modules = getattr(request.app.state, "loaded_modules", [])
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "vapid_public_key": settings.vapid_public_key,
            "loaded_modules": loaded_modules,
        },
    )
