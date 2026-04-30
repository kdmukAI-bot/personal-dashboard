# Server-Sent Events through Cloudflare Tunnel: stability findings

The personal-dashboard's `/events` SSE endpoint was unstable through Cloudflare Tunnel + CF Access until two non-obvious knobs were tuned. Both fixes accumulate; either alone is insufficient.

## Symptom

Browser console reports periodic `EventSource` errors:

- Initially: `GET /events net::ERR_QUIC_PROTOCOL_ERROR 200 (OK)`
- After disabling HTTP/3: `GET /events net::ERR_HTTP2_PROTOCOL_ERROR 200 (OK)` and occasional `502 Bad Gateway`

EventSource auto-reconnects, so push notifications still arrive (those don't traverse `/events` at all — they go via Mozilla/Apple/Google relays directly to the SW). But widget updates pause briefly during reconnect, and the console noise is real.

## Root cause #1: Cloudflare's HTTP/3 reaps long-lived streams

Cloudflare's HTTP/3 (QUIC) implementation appears to reap idle streams on a schedule independent of application-layer pings. We have `sse-starlette` configured to send `:ping\n\n` comment lines every 10s — those bytes do flow over the wire — but CF's HTTP/3 layer doesn't appear to count them toward keeping the stream "active." Stream gets reset after some interval, browser surfaces `ERR_QUIC_PROTOCOL_ERROR`.

### Fix

Disable HTTP/3 zone-wide in Cloudflare:

- Cloudflare dashboard → select zone → **Speed → Optimization → Protocol Optimization** OR **Network** → **HTTP/3 (with QUIC)** → toggle **off**.
- Or per-hostname: Transform Rule that sets `Alt-Svc: clear` for the hostname, instructing the browser to forget cached HTTP/3 advertisements.

For a single-zone personal setup, the zone-wide toggle is simplest and the marginal latency loss is invisible.

## Root cause #2: cloudflared's default `keepAliveTimeout` is 90s

Even with HTTP/2 between browser and CF edge, the upstream connection (cloudflared → uvicorn at `localhost:8421`) has its own idle behavior. Default `originRequest.keepAliveTimeout = 90s`. After 90 seconds, cloudflared drops idle upstream connections and re-establishes them on next request. Long-lived SSE streams can land mid-cycle and get reset, surfacing as `ERR_HTTP2_PROTOCOL_ERROR` or transient `502 Bad Gateway`.

### Fix

In `/etc/cloudflared/config.yml`, attach `originRequest` to the dashboard ingress entry:

```yaml
ingress:
  - hostname: dashboard.kdmukaibot.com
    service: http://localhost:8421
    originRequest:
      keepAliveTimeout: 30m
      proxyConnectTimeout: 30s
  - service: http_status:404
```

Then `sudo systemctl restart cloudflared`. (`systemctl reload` is not supported by this unit.)

The 30m timeout is generous; combined with sse-starlette's 10s pings, the upstream connection should never be idle long enough to be reaped.

## Why both fixes are needed

- HTTP/3 disable alone: removes QUIC stream reaping, but cloudflared's 90s upstream timeout still cycles the underlying connection.
- cloudflared timeout alone: extends upstream lifetime, but CF edge's HTTP/3 still reaps the browser-facing stream.

Applying both yields stable SSE through CF Tunnel + Access for the personal-dashboard's expected event rate.

## What we considered and rejected

- **Reducing sse-starlette ping interval to 5s or 3s**: didn't help when tested at 10s already. CF's reaping doesn't appear to be ping-frequency sensitive within reasonable ranges.
- **Replacing SSE with WebSocket**: CF is generally more tolerant of WebSocket long-lived connections, but this is a substantial frontend rewrite (HTMX SSE extension + sse-starlette + EventSource + visibility-aware reconnect → all replaced). Disproportionate for what's effectively a console-noise concern; revisit only if we hit a real product-blocking SSE failure.
- **Proxying `/events` through a Cloudflare Worker**: Workers have different streaming-response timeout characteristics. Adds infrastructure complexity for a single endpoint; not justified at v1.

## Auxiliary fact: push delivery is independent of `/events`

Worth being explicit since it caused some confusion during debugging: push notifications travel **browser ↔ Mozilla/Apple/Google push relays ↔ Service Worker**, completely bypassing the dashboard's `/events` endpoint. Even if SSE is broken or cloudflared is wedged, push notifications still arrive on subscribed devices because:

1. `pywebpush.webpush()` from the dashboard server POSTs encrypted payloads directly to `https://fcm.googleapis.com/...` (or equivalent) — outbound traffic from the origin, not via the tunnel.
2. The push relay holds the message and pushes it to the subscribed browser's persistent connection (which the browser maintains independently of any open dashboard tab).
3. The Service Worker wakes on the push event and calls `showNotification()` — purely local to the device.

`/events` is purely for live widget refresh in an open dashboard tab. Brief outages there are visible but not data-lossy: each widget re-fetches state on SSE reconnect via `hx-trigger="load, sse:<event>"`.

## File references

- [`personal_dashboard/api/events.py`](../../personal_dashboard/api/events.py) — `EventSourceResponse(gen(), ping=10)`
- [`/etc/cloudflared/config.yml`](file:///etc/cloudflared/config.yml) — ingress with `originRequest.keepAliveTimeout: 30m`
- [`personal_dashboard/core/sse.py`](../../personal_dashboard/core/sse.py) — in-process SSE bus
- [`static/js/sse-managed.js`](../../static/js/sse-managed.js) — visibility-aware EventSource wrapper for widget JS handlers
