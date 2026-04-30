# Plugin Custom Routes and Core Access

## The non-obvious bit

The dashboard's [module_loader](../../personal_dashboard/core/module_loader.py) injects the `DashboardCoreImpl` into the auto-mounted `/widget`, `/data`, and `/` route handlers via closure (see `_make_widget_handler`, `_make_detail_handler` — both take `core` as an argument). **Custom routes declared via `library.routes` do not get this treatment.** The wrapper at `_make_custom_handler(spec)` calls `await spec.handler(request)` with only the request — no core injection.

This means a plugin's custom route handler cannot directly call `core.publish_module_result(...)`, `core.notify(...)`, or any other dashboard service via a parameter. The plugin's `__init__(config)` doesn't get a core ref either, so capturing it at construction time is also impossible.

## How to access core from a custom route

The core instance is exposed on the FastAPI app's state at startup:

```python
# personal_dashboard/main.py:87
app.state.core = core
```

So plugin handlers reach core via `request.app.state.core`:

```python
class Analyzer:
    @property
    def routes(self) -> list[RouteSpec]:
        analyzer = self  # closure capture for self.update()

        async def run_now_handler(request: Request) -> JSONResponse:
            result = await analyzer.update()
            core = getattr(request.app.state, "core", None)
            if core is not None:
                await core.publish_module_result("cron-summary", result)
            return JSONResponse({"summary_text": result.summary_text})

        return [RouteSpec(path="/run-now", handler=run_now_handler,
                          method="POST", auth="bearer")]
```

The `getattr(..., None)` guard is defensive — `app.state.core` is set in the lifespan startup, so by the time route handlers fire it should always be present, but missing it shouldn't crash the handler.

## Why this matters for SSE-driven UI

The scheduled-update path (`module_loader._interval_loop` / `_daily_loop` / `_weekly_loop`) calls `await library.update()` and then publishes via core itself, so the SSE event fires and dashboard widgets refresh live. Custom routes (e.g. a `/run-now` manual trigger) won't trigger SSE unless the handler explicitly calls `publish_module_result` itself — which is why every "force a refresh" handler needs the `request.app.state.core` lookup above.

## If this gets refactored

A cleaner contract would be for custom-route handlers to receive `(request, core)` from `_make_custom_handler`. Easy change in `module_loader.py:132-137` if there's appetite for it; until then, every plugin pays the `request.app.state.core` tax.
