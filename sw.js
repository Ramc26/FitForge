const CACHE_NAME = 'fitforge-v13';
const ASSETS = [
    '/',
    '/index.html',
    '/css/app.css',
    '/js/api.js',
    '/js/app.js',
    '/data.json',
    '/manifest.json',
    '/images/fitnesscoach.png',
    '/images/forge-icon.svg',
    '/images/forge-icon-180.png',
    '/images/forge-icon-192.png',
    '/images/forge-icon-512.png',
];

self.addEventListener('install', (event) => {
    self.skipWaiting();
    event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(ASSETS.map((url) => new Request(url, { cache: 'reload' })))));
});

self.addEventListener('activate', (event) => {
    event.waitUntil((async () => {
        const keys = await caches.keys();
        await Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key)));
        await self.clients.claim();
    })());
});

async function networkFirst(request) {
    try {
        const response = await fetch(request, { cache: 'no-cache' });
        const copy = response.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(request, copy));
        return response;
    } catch (err) {
        const cached = await caches.match(request);
        if (cached) return cached;
        throw err;
    }
}

self.addEventListener('fetch', (event) => {
    const url = new URL(event.request.url);
    if (event.request.method !== 'GET') return;
    if (url.origin !== self.location.origin) return;
    if (url.pathname.startsWith('/api/')) return;

    const fresh = event.request.mode === 'navigate'
        || url.pathname === '/'
        || url.pathname.endsWith('.html')
        || url.pathname.endsWith('.css')
        || url.pathname.endsWith('.js')
        || url.pathname.endsWith('data.json')
        || url.pathname.endsWith('sw.js');
    if (fresh) {
        event.respondWith(networkFirst(event.request));
        return;
    }
    event.respondWith(caches.match(event.request).then((cached) => cached || fetch(event.request)));
});
