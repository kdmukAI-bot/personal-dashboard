from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates

from personal_dashboard.api.events import router as events_router
from personal_dashboard.api.notifications import router as notifications_router
from personal_dashboard.api.notify import router as notify_router
from personal_dashboard.api.push import router as push_router
from personal_dashboard.api.shell import router as shell_router
from personal_dashboard.config import settings
from personal_dashboard.core.module_loader import (
    discover_modules,
    mount_modules,
    start_scheduler,
)
from personal_dashboard.core.services import DashboardCoreImpl
from personal_dashboard.database import core_engine
from personal_dashboard.models.base import Base
from personal_dashboard.models.notification import Notification  # noqa: F401
from personal_dashboard.models.subscription import PushSubscription  # noqa: F401

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent


def days_ago(date_val) -> str:
    if not date_val:
        return ""
    try:
        if isinstance(date_val, datetime):
            dt = date_val
        else:
            dt = datetime.fromisoformat(str(date_val).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - dt
        total_seconds = int(delta.total_seconds())
        if total_seconds < 0:
            return "just now"
        hours = total_seconds // 3600
        if hours < 1:
            return "just now"
        if hours < 24:
            return f"{hours} hour{'s' if hours != 1 else ''} ago"
        days = delta.days
        if days == 1:
            return "yesterday"
        elif days < 30:
            return f"{days} days ago"
        elif days < 365:
            months = days // 30
            return f"{months} month{'s' if months != 1 else ''} ago"
        else:
            years = days // 365
            return f"{years} year{'s' if years != 1 else ''} ago"
    except (ValueError, TypeError):
        return str(date_val)[:10] if date_val else ""


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.data_dir.mkdir(parents=True, exist_ok=True)

    if not settings.notify_api_key:
        raise RuntimeError(
            "NOTIFY_API_KEY is required. Generate one and set it in .env."
        )
    if not settings.vapid_private_key or not settings.vapid_public_key:
        raise RuntimeError(
            "VAPID keys are required. Run `personal-dashboard generate-vapid` first."
        )

    async with core_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    core = DashboardCoreImpl(app, app.state.templates)
    app.state.core = core

    loaded = discover_modules()
    app.state.loaded_modules = loaded

    mount_modules(app, core, loaded)
    start_scheduler(app, core, loaded)

    try:
        for lm in loaded:
            try:
                await lm.library.startup()
            except Exception:
                logger.exception("module %s: startup() failed", lm.name)

        yield
    finally:
        for task in getattr(app.state, "scheduler_tasks", []):
            task.cancel()
        for task in getattr(app.state, "scheduler_tasks", []):
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

        for lm in loaded:
            try:
                await lm.library.shutdown()
            except Exception:
                logger.exception("module %s: shutdown() failed", lm.name)


app = FastAPI(title="Personal Dashboard", version="0.1.0", lifespan=lifespan)

app.state.templates = Jinja2Templates(directory=PROJECT_ROOT / "templates")
app.state.templates.env.auto_reload = True
app.state.templates.env.filters["days_ago"] = days_ago
app.state.templates.env.globals["asset_v"] = str(int(time.time()))

app.mount("/static", StaticFiles(directory=PROJECT_ROOT / "static"), name="static")


@app.get("/sw.js", include_in_schema=False)
async def service_worker():
    from fastapi.responses import FileResponse
    return FileResponse(
        PROJECT_ROOT / "static" / "sw.js",
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"},
    )


app.include_router(shell_router)
app.include_router(push_router)
app.include_router(notify_router)
app.include_router(events_router)
app.include_router(notifications_router)
