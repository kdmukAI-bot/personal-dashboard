from __future__ import annotations

import asyncio
import inspect
import logging
import sys
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import FileSystemLoader

from personal_dashboard.core.bearer_auth import require_bearer_token
from personal_dashboard.core.protocol import RouteSpec
from personal_dashboard.core.services import DashboardCoreImpl

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

logger = logging.getLogger(__name__)


@dataclass
class LoadedModule:
    name: str
    library: Any
    config: dict
    source_dir: Path

    @property
    def display_name(self) -> str:
        return getattr(self.library, "display_name", self.name)

    @property
    def widget(self) -> dict:
        return self.config.get("widget") or {}


def discover_modules() -> list[LoadedModule]:
    loaded: list[LoadedModule] = []
    try:
        eps = entry_points(group="personal_dashboard.modules")
    except TypeError:  # pragma: no cover
        eps = entry_points().get("personal_dashboard.modules", [])

    for ep in eps:
        try:
            cls = ep.load()
        except Exception:
            logger.exception("failed to load entry point %s", ep.name)
            continue

        try:
            cls_file = Path(inspect.getfile(cls))
        except TypeError:
            logger.warning("could not resolve source file for %s", ep.name)
            continue

        source_dir = cls_file.parent.parent
        config_path = source_dir / "config.toml"
        if not config_path.is_file():
            logger.info("module %s: no config.toml at %s, skipping", ep.name, config_path)
            continue

        try:
            with config_path.open("rb") as f:
                config = tomllib.load(f)
        except Exception:
            logger.exception("module %s: failed to parse %s", ep.name, config_path)
            continue

        if not config.get("enabled", False):
            logger.info("module %s: enabled=false, skipping", ep.name)
            continue

        try:
            instance = cls(config)
        except Exception:
            logger.exception("module %s: __init__ failed", ep.name)
            continue

        loaded.append(
            LoadedModule(name=ep.name, library=instance, config=config, source_dir=source_dir)
        )

    return loaded


def _make_widget_handler(loaded: LoadedModule, core: DashboardCoreImpl):
    async def handler(request: Request):
        data = await loaded.library.get_data()
        return core.templates.TemplateResponse(
            request,
            f"{loaded.name}/widget.html",
            {"data": data, "module_name": loaded.name},
        )

    return handler


def _make_data_handler(loaded: LoadedModule):
    async def handler(request: Request):
        data = await loaded.library.get_data()
        return JSONResponse(data)

    return handler


def _make_detail_handler(loaded: LoadedModule, core: DashboardCoreImpl):
    detail_template = f"{loaded.name}/detail.html"

    async def handler(request: Request):
        if not (loaded.source_dir / "templates" / loaded.name / "detail.html").is_file():
            raise HTTPException(status_code=404)
        data = await loaded.library.get_data()
        return core.templates.TemplateResponse(
            request,
            detail_template,
            {"data": data, "module_name": loaded.name},
        )

    return handler


def _make_custom_handler(spec: RouteSpec):
    async def handler(request: Request):
        result = await spec.handler(request)
        return result if not isinstance(result, dict) else JSONResponse(result)

    return handler


def mount_modules(
    app: FastAPI,
    core: DashboardCoreImpl,
    loaded: list[LoadedModule],
) -> None:
    loader = core.templates.env.loader
    search_paths: list[str] = []
    if isinstance(loader, FileSystemLoader):
        search_paths = list(loader.searchpath)

    policies: dict[str, str] = {}

    for lm in loaded:
        templates_dir = lm.source_dir / "templates"
        if templates_dir.is_dir():
            search_paths.append(str(templates_dir))

        static_dir = lm.source_dir / "static"
        if static_dir.is_dir():
            app.mount(
                f"/static/{lm.name}",
                StaticFiles(directory=str(static_dir)),
                name=f"static-{lm.name}",
            )

        router = APIRouter(prefix=f"/modules/{lm.name}")
        router.add_api_route("/widget", _make_widget_handler(lm, core), methods=["GET"])
        router.add_api_route("/data", _make_data_handler(lm), methods=["GET"])
        router.add_api_route("/", _make_detail_handler(lm, core), methods=["GET"])

        try:
            custom_routes = lm.library.routes
        except AttributeError:
            custom_routes = []
        for spec in custom_routes or []:
            dependencies = []
            if spec.auth == "bearer":
                from fastapi import Depends

                dependencies = [Depends(require_bearer_token)]
            router.add_api_route(
                spec.path,
                _make_custom_handler(spec),
                methods=[spec.method],
                dependencies=dependencies,
            )

        app.include_router(router)

        policies[lm.name] = lm.config.get("notification_policy", "warning_and_above")

    if search_paths:
        core.templates.env.loader = FileSystemLoader(search_paths)

    app.state.module_policies = policies


async def _interval_loop(core: DashboardCoreImpl, lm: LoadedModule, seconds: float) -> None:
    while True:
        try:
            result = await lm.library.update()
            if result is not None:
                await core.publish_module_result(lm.name, result)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("module %s: scheduled update() failed", lm.name)
        await asyncio.sleep(seconds)


def _next_daily_fire(at_str: str) -> datetime:
    hh, mm = at_str.split(":")
    target = time(int(hh), int(mm))
    now = datetime.now()
    candidate = datetime.combine(now.date(), target)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


async def _daily_loop(core: DashboardCoreImpl, lm: LoadedModule, at_str: str) -> None:
    while True:
        next_fire = _next_daily_fire(at_str)
        delay = (next_fire - datetime.now()).total_seconds()
        if delay > 0:
            await asyncio.sleep(delay)
        try:
            result = await lm.library.update()
            if result is not None:
                await core.publish_module_result(lm.name, result)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("module %s: daily update() failed", lm.name)


async def _weekly_loop(
    core: DashboardCoreImpl, lm: LoadedModule, at_str: str, weekday: int
) -> None:
    while True:
        hh, mm = at_str.split(":")
        target = time(int(hh), int(mm))
        now = datetime.now()
        days_ahead = (weekday - now.weekday()) % 7
        candidate = datetime.combine(now.date(), target) + timedelta(days=days_ahead)
        if candidate <= now:
            candidate += timedelta(days=7)
        delay = (candidate - now).total_seconds()
        if delay > 0:
            await asyncio.sleep(delay)
        try:
            result = await lm.library.update()
            if result is not None:
                await core.publish_module_result(lm.name, result)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("module %s: weekly update() failed", lm.name)


def start_scheduler(
    app: FastAPI,
    core: DashboardCoreImpl,
    loaded: list[LoadedModule],
) -> None:
    tasks: list[asyncio.Task] = []
    for lm in loaded:
        schedule = lm.config.get("schedule") or {}
        stype = schedule.get("type")
        if stype == "interval":
            seconds = float(schedule.get("seconds", 0))
            if seconds <= 0:
                logger.warning("module %s: interval schedule requires positive seconds", lm.name)
                continue
            tasks.append(asyncio.create_task(_interval_loop(core, lm, seconds)))
        elif stype == "daily":
            at_str = schedule.get("at", "08:00")
            tasks.append(asyncio.create_task(_daily_loop(core, lm, at_str)))
        elif stype == "weekly":
            at_str = schedule.get("at", "08:00")
            weekday = int(schedule.get("weekday", 0))
            tasks.append(asyncio.create_task(_weekly_loop(core, lm, at_str, weekday)))
        elif stype is None:
            continue
        else:
            logger.warning("module %s: unknown schedule type %r", lm.name, stype)

    app.state.scheduler_tasks = tasks
