// Personal Dashboard Service Worker
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', () => self.clients.claim());

self.addEventListener('push', (event) => {
  let payload = {};
  try { payload = event.data ? event.data.json() : {}; } catch { payload = { title: 'Notification', body: event.data ? event.data.text() : '' }; }
  const title = payload.title || 'Personal Dashboard';
  const options = {
    body: payload.body || '',
    icon: '/static/icons/icon-192.png?v=2',
    image: payload.image || undefined,
    data: { click_url: payload.click_url || '/', source: payload.source || null },
    tag: payload.source || undefined,
    renotify: !!payload.source,
    requireInteraction: !!payload.requireInteraction,
  };
  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const target = (event.notification.data && event.notification.data.click_url) || '/';
  event.waitUntil((async () => {
    const clientsList = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    for (const c of clientsList) {
      if ('focus' in c) { c.navigate(target).catch(() => {}); return c.focus(); }
    }
    return self.clients.openWindow(target);
  })());
});
