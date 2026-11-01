// Service worker (M3b): shows push messages and opens the app on tap. It caches
// nothing on purpose: the app always comes fresh from the server on the LAN.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()));

// Only paths of this app: '//other.host' or 'https://…' fall back to the start page.
function sameOrigin(u) {
  try {
    const url = new URL(typeof u === 'string' ? u : '/', self.location.origin);
    return url.origin === self.location.origin ? url.pathname + url.search + url.hash : '/';
  } catch { return '/'; }
}

self.addEventListener('push', (event) => {
  let d = {};
  try { d = event.data ? event.data.json() : {}; } catch { d = { body: event.data ? event.data.text() : '' }; }
  event.waitUntil(self.registration.showNotification(d.title || 'Blattwerk', {
    body: d.body || '',
    icon: '/icon-192.png',
    badge: '/icon-192.png',
    data: { url: sameOrigin(d.url) },
    tag: 'blattwerk',
    renotify: true,
  }));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const url = new URL(sameOrigin(event.notification.data.url), self.location.origin).href;
  event.waitUntil((async () => {
    const list = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    for (const c of list) {
      if (new URL(c.url).origin !== self.location.origin) continue;
      try { const moved = await c.navigate(url); if (moved) return moved.focus(); } catch { /* not controlled by us */ }
      break;  // a window we cannot steer: open a fresh one instead
    }
    return self.clients.openWindow(url);
  })());
});
