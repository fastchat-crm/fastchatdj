const CACHE_NAME = 'fastchat-pwa-v1';
const OFFLINE_URL = '/offline/';

self.addEventListener('install', (event) => {
    event.waitUntil(
        caches.open(CACHE_NAME).then((cache) => cache.add(new Request(OFFLINE_URL, {cache: 'reload'})))
    );
    self.skipWaiting();
});

self.addEventListener('activate', (event) => {
    event.waitUntil(self.clients.claim());
});

self.addEventListener('fetch', (event) => {
    if (event.request.mode === 'navigate') {
        event.respondWith(
            fetch(event.request).catch(() => caches.match(OFFLINE_URL))
        );
    }
});
