from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from starlette.templating import Jinja2Templates

from personal_dashboard.config import settings
from personal_dashboard.core import web_push
from personal_dashboard.core.result import ModuleResult, Status
from personal_dashboard.core.sse import sse_bus
from personal_dashboard.database import core_session

logger = logging.getLogger(__name__)

_NOTIFY_STATUSES = {Status.WARNING, Status.CRITICAL}


class DashboardCoreImpl:
    def __init__(self, app: FastAPI, templates: Jinja2Templates) -> None:
        self._app = app
        self.templates = templates
        self.previous_status: dict[str, Status] = {}

    async def publish_module_result(self, module_name: str, result: ModuleResult) -> None:
        sse_bus.publish(f"{module_name}-update", result.to_dict())

        # TODO: replace app.state.module_policies lookup with whatever the
        # module loader exposes once policy registration is wired.
        policies: dict[str, str] = getattr(self._app.state, "module_policies", {})
        policy = policies.get(module_name, "warning_and_above")

        previous = self.previous_status.get(module_name)
        should_notify = False
        if policy == "never":
            should_notify = False
        elif policy == "critical_only":
            should_notify = result.status is Status.CRITICAL and previous is not Status.CRITICAL
        else:  # warning_and_above (default)
            should_notify = result.status in _NOTIFY_STATUSES and previous != result.status

        if should_notify:
            await self.notify(
                result.summary_text or module_name,
                result.detail_text or "",
                click_url=result.click_url,
                source=module_name,
            )

        self.previous_status[module_name] = result.status

    async def notify(
        self,
        title: str,
        body: str,
        *,
        image_url: str | None = None,
        click_url: str | None = None,
        source: str | None = None,
    ) -> None:
        try:
            await web_push.dispatch(
                title,
                body,
                image_url=image_url,
                click_url=click_url,
                source=source,
            )
        except Exception:
            logger.exception("notify dispatch failed (title=%r)", title)

    async def sse_publish(self, event: str, data: dict) -> None:
        sse_bus.publish(event, data)

    def get_templates(self) -> Jinja2Templates:
        return self.templates

    def get_db_session(self) -> Any:
        return core_session

    def module_data_dir(self, module_name: str) -> Path:
        path = settings.data_dir / "modules" / module_name
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def base_url(self) -> str:
        return settings.base_url
