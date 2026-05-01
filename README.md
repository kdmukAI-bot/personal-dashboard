# personal-dashboard

A self-hosted personal dashboard with Web Push notifications, server-sent events for live widgets, a GridStack-based draggable home layout, and an external-plugin system. Designed to run as a `systemd --user` service behind Cloudflare Tunnel + Cloudflare Access (browser auth) with a single bearer token gating the `/api/notify` write endpoint.

For architectural rationale, design decisions, current open work, and future-module ideas, see [`docs/PLAN.md`](docs/PLAN.md).

## What you get

- **Home dashboard** at `/` — GridStack tile layout, plugin widgets render in tiles.
- **PWA** — installable from Chrome (desktop) and Android. Service worker registered at site root.
- **Web Push** — VAPID-signed; works through Cloudflare Tunnel + Access.
- **Server-Sent Events** at `/events` — live widget updates without polling.
- **Bearer-authenticated `/api/notify`** — accepts JSON; pushes to all subscribed clients.
- **Plugin entry points** — third-party packages declare `personal_dashboard.modules` entry points and ship their own routes/templates/static files.

## Repo layout

```
personal_dashboard/
  main.py             FastAPI app
  cli.py              `personal-dashboard` and `pd-notify` console scripts
  config.py           pydantic-settings (loads .env)
  api/                /api/notify, /api/push, SSE, etc.
  core/               module loader, web push, SSE, bearer auth
  models/             SQLAlchemy models for subscriptions + notifications
templates/            Home + base layout
static/               JS/CSS (GridStack, htmx, sw.js, push.js)
systemd/              user service unit
docs/knowledge/       debug journals (kept local; gitignored)
```

## Install

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
```

## First-time setup

1. **Generate VAPID keys** (used to sign Web Push messages):
   ```sh
   personal-dashboard generate-vapid --write-env
   ```
   Writes `VAPID_PRIVATE_KEY` / `VAPID_PUBLIC_KEY` to `./.env`.

2. **Copy and edit env:**
   ```sh
   cp .env.example .env
   # Set NOTIFY_API_KEY (e.g. `python -c "import secrets; print(secrets.token_urlsafe(32))"`)
   # Set VAPID_SUBJECT to a mailto: URL you control
   # Optionally set BASE_URL if running behind a public hostname
   ```

3. **Run the server:**
   ```sh
   uvicorn personal_dashboard.main:app --host 127.0.0.1 --port 8421 \
     --reload \
     --reload-dir /home/kdmukai/dev/tools/personal-dashboard/personal_dashboard \
     --reload-dir /home/kdmukai/dev/tools/personal-dashboard-modules
   ```
   Or install the systemd unit at `systemd/personal-dashboard.service` to `~/.config/systemd/user/`:
   ```sh
   systemctl --user daemon-reload
   systemctl --user enable --now personal-dashboard.service
   ```

4. **Subscribe a browser to push.** Open the dashboard, click "Enable notifications", grant permission. The browser registers `/sw.js` and posts its push subscription to the server. From then on, `/api/notify` calls deliver to that browser.

## Sending notifications

`pd-notify` is the CLI:

```sh
NOTIFY_API_KEY=... pd-notify "Hello" "from the CLI" --click-url https://example.com
```

Or write the token to `~/.config/personal-dashboard/config.toml`:

```toml
[core]
notify_api_key = "..."
```

Or POST directly:

```sh
curl -X POST http://localhost:8421/api/notify \
  -H "Authorization: Bearer $NOTIFY_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"title":"Hello","body":"from curl","source":"manual"}'
```

## Plugins

Plugins are ordinary Python packages that declare a `personal_dashboard.modules` entry point. The first such plugin is [`cron-summary`](https://github.com/kdmukAI-bot/cron-summary). Skeleton:

```toml
[project.entry-points."personal_dashboard.modules"]
my-module = "my_module.analyzer:Analyzer"
```

Module classes implement `update()` (returns a `ModuleResult` for the home widget), and may register custom FastAPI routes and Jinja templates via the protocol in `personal_dashboard/core/protocol.py`. Install the plugin into the dashboard's venv (`pip install -e ../path/to/plugin`) and restart — the loader picks it up automatically.

## Development notes

- **Static-asset cache busting is disabled in dev.** `asset_v` (the `?v=…` token appended to every `<link>` / `<script>` URL) is currently a callable that returns `int(time.time())` per render, so browsers re-fetch CSS/JS on every page load. This means CSS-only edits go live without a service restart. Once the dev pace settles, swap the lambda back to `str(int(time.time()))` at [`personal_dashboard/main.py`](personal_dashboard/main.py) (the line is comment-marked) to restore once-per-process caching.

## Deploying behind Cloudflare Tunnel + Access

The dashboard binds to `127.0.0.1` by default. Put `cloudflared` in front, plus a Cloudflare Access policy on the hostname so only your identity can reach the UI. The bearer token on `/api/notify` is the second layer (so cron jobs / scripts can post without a browser session).

If you see SSE instability through Cloudflare, check `docs/knowledge/sse-through-cloudflare-tunnel.md` (kept local in this repo, not published).

### Android push reliability caveat

Web Push delivery to Android is reliable while the PWA has been opened recently, but can be silently dropped after long idle (~24h+) — FCM accepts the push, but Android Doze + Chrome service-worker eviction can swallow it. `pd-notify` returning `delivered: N, failed: 0` does not guarantee on-device display. Opening the PWA wakes the service worker; subsequent pushes work. See `docs/knowledge/android-push-after-idle.md` (local-only) for the full diagnosis. A second SMS-based channel for truly urgent notifications is on the roadmap (see [`docs/PLAN.md`](docs/PLAN.md) → "Open core work").

## Configuration reference

See `.env.example` for the full set. Most-used:

| Var | Purpose |
|---|---|
| `NOTIFY_API_KEY` | Bearer token for `/api/notify` |
| `VAPID_PUBLIC_KEY` / `VAPID_PRIVATE_KEY` | Web Push keypair |
| `VAPID_SUBJECT` | `mailto:` URL you control (required by Web Push spec) |
| `HOST` / `PORT` | Bind address (default `127.0.0.1:8421`) |
| `BASE_URL` | Public origin if running behind a tunnel/proxy |
| `DEBUG` | Verbose logging |
