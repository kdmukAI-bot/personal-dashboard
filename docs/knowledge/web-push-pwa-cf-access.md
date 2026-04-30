# Web Push + PWA gotchas behind Cloudflare Tunnel + Access

A series of non-obvious findings discovered while shipping the personal-dashboard v1 push notification pipeline. Each section is a debug-journal-style entry: symptom, root cause, fix, why it bit us.

## 1. Service Worker scope when served from `/static/`

**Symptom.** `SecurityError: Failed to register a ServiceWorker for scope ('https://host/') with script ('https://host/static/sw.js'): The path of the provided scope ('/') is not under the max scope allowed ('/static/').`

**Root cause.** Browsers restrict an SW's max scope to the path of the script that registered it. `sw.js` served from `/static/sw.js` has a default max scope of `/static/`. Asking for scope `/` is rejected unless the response includes a `Service-Worker-Allowed: /` header (which FastAPI's `StaticFiles` doesn't set).

**Fix.** Add a tiny FastAPI route at `/sw.js` (root path) that returns `static/sw.js` with `Service-Worker-Allowed: /` and `Cache-Control: no-cache`. Update the registration call in `push.js` to register `/sw.js` (not `/static/sw.js`). Once the script is served from root, scope `/` is the natural max scope; the explicit header is belt-and-braces.

**Why it bit us.** The "static asset agent" produced `static/sw.js` and `push.js` registered it under that path. That works fine for the SW's own subtree but the dashboard needs the SW to control the entire site (push, navigation focus, future fetch caching). Easy to miss when bootstrapping.

## 2. PWA manifest fetch through Cloudflare Access requires `crossorigin="use-credentials"`

**Symptom.** Browser console shows `Access to manifest at '<CF Access login URL>' (redirected from 'https://dashboard.../static/manifest.json') from origin 'https://dashboard...' has been blocked by CORS policy: No 'Access-Control-Allow-Origin' header is present on the requested resource.` The PWA install prompt never appears even though the manifest is otherwise valid.

**Root cause.** Browsers fetch `<link rel="manifest">` in CORS mode by default, which means *no credentials sent unless explicitly opted in*. CF Access sees no auth cookie on the manifest fetch, redirects to `<team>.cloudflareaccess.com/cdn-cgi/access/login/...`, and the cross-origin redirect on a CORS-mode request fails the CORS check.

**Fix.** Add `crossorigin="use-credentials"` to the manifest link tag:

```html
<link rel="manifest" href="/static/manifest.json?v={{ asset_v }}" crossorigin="use-credentials">
```

This tells the browser to attach cookies on the manifest fetch, CF Access sees auth, returns the manifest directly without redirect.

**Why it bit us.** The plan didn't account for any auth gate originally (Tailscale-only had no auth in the data path). When we pivoted to CF Access in front of CF Tunnel, the manifest path silently broke until we hit the install-prompt failure on phone.

## 3. VAPID private key encoding for `pywebpush`

**Symptom.** With private keys generated as base64-encoded PEM (the obvious-looking thing to do), `py_vapid.Vapid.from_string()` rejects the value with a parse error. Push dispatch fails.

**Root cause.** `py_vapid.Vapid.from_string()` expects a **base64url-encoded raw 32-byte ECDSA P-256 private key**, NOT base64-of-PEM. The two encodings look superficially similar (base64url string in `.env`) but `from_string` does a base64url-decode and then treats the result as raw key bytes — passing PEM there fails.

**Fix in [`personal_dashboard/cli.py`](../../personal_dashboard/cli.py):**

```python
raw_priv = vapid.private_key.private_numbers().private_value.to_bytes(32, "big")
private_b64 = base64.urlsafe_b64encode(raw_priv).rstrip(b"=").decode()
```

Public key: `vapid.public_key.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)` then base64url-encode → standard 65-byte uncompressed point.

**Why it bit us.** The first `cli.py` draft did `base64.urlsafe_b64encode(vapid.private_pem())` because PEM is what `webpush()` accepts when passed directly as a Python string. But our `.env` storage round-trips through `Vapid.from_string()`, which has different format expectations.

## 4. Asset cache-busting must cover SW push handler, manifest icons, and favicon

**Symptom.** After replacing icon files on disk, browsers continued showing the old icon in: PWA install prompt, push notifications, browser tab favicon. Even hard reload (Ctrl+Shift+R) didn't help on all surfaces.

**Root cause.** Three independent cache layers reference these paths and each has different invalidation behavior:

1. **HTML `<link rel="icon">` and `<link rel="apple-touch-icon">`** — browser caches favicons aggressively at the OS-tab level; doesn't refresh on soft reload.
2. **`manifest.json` icon paths** — Chrome caches the manifest itself; the install prompt uses the cached icon paths verbatim.
3. **SW `showNotification({icon: ...})`** — when the push handler fires, the browser fetches the icon URL through its standard HTTP cache.

**Fix.** Cache-bust *every* reference point:

- Server: expose `asset_v = str(int(time.time()))` as a Jinja global at process startup. Each `--reload` restart gets a fresh value.
- Templates: append `?v={{ asset_v }}` to the manifest, favicon, apple-touch-icon, and every `<script src>` / `<link rel="stylesheet">` URL in `base.html`.
- `manifest.json`: hardcode `?v=N` on icon `src` paths (bump N when icons change). Or, better, render manifest as a Jinja template too — deferred until icons need to change frequently.
- `sw.js`: hardcode `?v=N` on the icon URL inside the push handler. Bump N when icons change.

A simpler-feeling alternative — no-cache headers on `/static/*` — doesn't reliably override the OS-tab favicon cache or Chrome's manifest cache. Versioned URLs do.

**Why it bit us.** Cache-busting only on `<script>`/`<link rel="stylesheet">` URLs (the obvious places) seemed sufficient until icon updates needed to propagate.

## 5. Same-tag push notifications go silent without `renotify: true`

**Symptom.** First push notification with `source="manual"` arrives and alerts. Subsequent pushes with the same source arrive but don't buzz/alert; they appear in Notification Center on macOS or the shade on Android, but no banner.

**Root cause.** The Notifications spec: when a `tag` matches an existing notification, the new one *replaces* the old in place. `renotify: false` (the default) means "replace silently" — no alert sound, no vibration. Our SW set `tag: payload.source || undefined`, which made every notification with the same source a silent replacement.

**Fix.** In [`static/sw.js`](../../static/sw.js), pair the tag with `renotify: true` so the alert fires every time:

```js
tag: payload.source || undefined,
renotify: !!payload.source,
```

`renotify` requires `tag` to be set; with no source, no tag, no renotify needed.

**Why it bit us.** Tags are useful for grouping (e.g., notification center stacks all `cron-summary` alerts together). The default behavior of "silent replace" is reasonable for replacing the *same* notification (e.g., progress updates), but for distinct events with the same source, we want each to alert.

## 6. macOS splits Chrome notification permissions into two entries — both must be enabled

**Symptom.** Push notifications were "delivered" (relay returned 2xx, DB row recorded) but never appeared on macOS — no banner, not even in Notification Center.

**Root cause.** macOS Sonoma+ sometimes shows TWO entries for "Google Chrome" under System Settings → Notifications. One handles native Chrome notifications (sign-in prompts, update alerts); the other handles web push from Chrome's PWAs / sites. If the web-push entry is disabled, web pushes are silently suppressed even with permission granted in the browser.

**Fix.** System Settings → Notifications → ensure BOTH "Google Chrome" entries are enabled, both set to **Alerts** (persistent) rather than **Banners** (auto-dismiss).

**Why it bit us.** Easy to assume a single Chrome entry. Disabled by default for one reason or another (Chrome update? OS upgrade?), invisibly breaking web push without any error surface.

## 7. macOS Chrome `requireInteraction: true` conflicts with platform "Alerts" style

**Symptom.** After setting `requireInteraction: true` in the SW push handler (intending to make notifications persist until clicked), notifications stopped appearing as banners on macOS — they went straight to Notification Center silently. Reverting `requireInteraction` to `false` (default) restored visible banners.

**Root cause.** When macOS Chrome's notification style is set to **Alerts** (persistent until dismissed), passing `requireInteraction: true` in the notification options conflicts with the platform-level persistence handling — Chrome appears to silently drop the notification rather than reconciling. Removing `requireInteraction` from the options lets the platform-level "Alerts" setting handle persistence.

**Fix.** Default `requireInteraction` to `false` in the SW. Plugins that want a persistent notification regardless of platform settings can opt in by including `requireInteraction: true` in their push payload:

```js
requireInteraction: !!payload.requireInteraction,
```

**Why it bit us.** "Make notifications persistent" sounds like a code-side concern, but persistence on macOS is platform-controlled. Setting it in code AND in the OS conflict; best to defer to the OS unless overriding for a specific plugin.

## 8. Android 14+ notification cooldown / spam detection

**Symptom.** After ~6 test pushes from the same `source="manual"` in ~30 minutes, Android labels subsequent notifications "possible spam" and silently routes them to a spam category instead of alerting.

**Root cause.** Android 14 introduced a per-app notification cooldown that auto-flags rapid-fire notifications from the same source/tag as spam. Triggers around ~5-6 notifications in a short window from the same channel.

**Fix during testing:** vary the `--source` label across test pushes (`--source test-1`, `--source test-2`, etc.). Production usage won't trigger this — real plugins use cadences (cron-summary fires daily, system-monitor uses sustained-condition alerting with hysteresis).

**Why it bit us.** Heavy testing with the same source name burned through the cooldown threshold quickly. Easy to confuse "Android flagged it" with "the push pipeline broke" without checking notification settings.

## 9. macOS Notification Center entries persist after auto-dismiss; banner ≠ delivery

**Useful debugging fact**, not exactly a bug: when a notification's banner auto-dismisses on macOS (style set to "Banners"), the notification still appears in Notification Center until the user clears it. Use `Notification Center` (click date/time in menu bar) as ground truth for "did the push reach the OS." If the entry is in Notification Center but the banner missed, the push pipeline is fine; the issue is banner-display behavior (Focus mode, foreground app suppression, banner-vs-alert style).
