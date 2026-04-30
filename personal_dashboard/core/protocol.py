from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Literal, Protocol

from fastapi import Request
from starlette.templating import Jinja2Templates

from personal_dashboard.core.result import ModuleResult


@dataclass
class RouteSpec:
    path: str
    handler: Callable[[Request], Awaitable[Any]]
    method: str = "GET"
    auth: Literal["bearer", None] = None
    template: str | None = None


class DashboardCore(Protocol):
    async def publish_module_result(self, module_name: str, result: ModuleResult) -> None: ...

    async def notify(
        self,
        title: str,
        body: str,
        *,
        image_url: str | None = None,
        click_url: str | None = None,
        source: str | None = None,
    ) -> None: ...

    async def sse_publish(self, event: str, data: dict) -> None: ...

    def get_templates(self) -> Jinja2Templates: ...

    def get_db_session(self) -> Any: ...

    def module_data_dir(self, module_name: str) -> Path: ...

    @property
    def base_url(self) -> str: ...


class Library(Protocol):
    display_name: str

    def __init__(self, config: dict) -> None: ...

    async def startup(self) -> None: ...

    async def shutdown(self) -> None: ...

    async def update(self) -> ModuleResult: ...

    async def get_data(self) -> dict: ...

    @property
    def routes(self) -> list[RouteSpec]: ...
