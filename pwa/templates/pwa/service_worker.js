const CACHE_NAME = 'fastchat-pwa-v3';
const OFFLINE_URL = '/offline/';

self.addEventListener('install', (event) => {
    event.waitUntil(
        caches.open(CACHE_NAME).then((cache) => cache.add(new Request(OFFLINE_URL, {cache: 'reload'})))
    );
    self.skipWaiting();
});

self.addEventListener('activate', (event) => {
    event.waitUntil((async () => {
        const keys = await caches.keys();
        await Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)));
        await self.clients.claim();
    })());
});

self.addEventListener('fetch', (event) => {
    if (event.request.mode === 'navigate') {
        event.respondWith(
            fetch(event.request).catch(() => caches.match(OFFLINE_URL))
        );
    }
});

self.addEventListener('push', (event) => {
    let payload = {};
    if (event.data) {
        try { payload = event.data.json(); }
        catch (e) { payload = {head: 'Notification', body: event.data.text()}; }
    }
    const title = payload.head || payload.title || 'Notification';
    const options = {
        body: payload.body || '',
        icon: payload.icon || '/static/images/icons/icon-192x192.png',
        badge: payload.badge || '/static/images/icons/icon-96x96.png',
        image: payload.image || undefined,
        tag: payload.tag || undefined,
        renotify: !!payload.tag,
        requireInteraction: payload.requireInteraction === true,
        vibrate: payload.vibrate || [200, 100, 200],
        data: {url: payload.url || '/', extra: payload.extra || null},
        actions: payload.url ? [{action: 'open_url', title: 'Open'}] : []
    };
    event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', (event) => {
    event.notification.close();
    const targetUrl = (event.notification.data && event.notification.data.url) || '/';
    event.waitUntil((async () => {
        const all = await clients.matchAll({type: 'window', includeUncontrolled: true});
        for (const c of all) {
            try {
                const u = new URL(c.url);
                if (u.origin === self.location.origin) {
                    await c.focus();
                    c.postMessage({type: 'NOTIFICATION_CLICK', url: targetUrl});
                    if ('navigate' in c) { try { await c.navigate(targetUrl); } catch (e) {} }
                    return;
                }
            } catch (e) {}
        }
        await clients.openWindow(targetUrl);
    })());
});
