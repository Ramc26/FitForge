const CACHE_NAME = 'fitforge-v4';
const ASSETS = [
    '/',
    '/index.html',
    '/data.json',
    '/manifest.json',
    '/forge-icon.svg',
    '/forge-icon-180.png',
    '/forge-icon-192.png',
    '/forge-icon-512.png',
];

self.addEventListener('install', (e) => {
    e.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(ASSETS)));
});

self.addEventListener('fetch', (e) => {
    const url = new URL(e.request.url);
    if (url.pathname.endsWith('data.json')) {
        e.respondWith(
            fetch(e.request)
                .then((response) => {
                    const clone = response.clone();
                    caches.open(CACHE_NAME).then((cache) => cache.put(e.request, clone));
                    return response;
                })
                .catch(() => caches.match(e.request))
        );
        return;
    }
    e.respondWith(caches.match(e.request).then((res) => res || fetch(e.request)));
});