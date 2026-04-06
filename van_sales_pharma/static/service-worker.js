const CACHE_NAME = 'van-sales-v2';
const ASSETS_TO_CACHE = [
    '/van_sales_pharma/static/img/icon-192.png',
    '/van_sales_pharma/static/img/icon-512.png',
];

self.addEventListener('install', event => {
    self.skipWaiting();
    event.waitUntil(
        caches.open(CACHE_NAME).then(cache => {
            return cache.addAll(ASSETS_TO_CACHE);
        })
    );
});

self.addEventListener('activate', event => {
    event.waitUntil(
        caches.keys().then(cacheNames => {
            return Promise.all(
                cacheNames.filter(name => name !== CACHE_NAME)
                    .map(name => caches.delete(name))
            );
        })
    );
    self.clients.claim();
});

self.addEventListener('fetch', event => {
    const url = new URL(event.request.url);

    // Dynamic routes and API calls (e.g. /van/client, /van/pos) -> Network First
    if (url.pathname.startsWith('/van/')) {
        event.respondWith(
            fetch(event.request).then(networkResponse => {
                // If we get a valid response, optionally we could cache it, but for these we want fresh
                return networkResponse;
            }).catch(() => {
                // Fallback to cache if offline
                return caches.match(event.request).then(cachedResponse => {
                    return cachedResponse || new Response('Offline', { status: 503 });
                });
            })
        );
        return;
    }

    // Static assets (images, etc) -> Cache First
    if (event.request.destination === 'image') {
        event.respondWith(
            caches.match(event.request).then(cachedResponse => {
                if (cachedResponse) {
                    fetch(event.request).then(networkResponse => {
                        caches.open(CACHE_NAME).then(cache => {
                            cache.put(event.request, networkResponse);
                        });
                    }).catch(() => { });
                    return cachedResponse;
                }

                return fetch(event.request).then(networkResponse => {
                    const clonedRes = networkResponse.clone();
                    caches.open(CACHE_NAME).then(cache => {
                        cache.put(event.request, clonedRes);
                    });
                    return networkResponse;
                }).catch(() => {
                    return new Response();
                });
            })
        );
    } else {
        // Default generic route handling
        event.respondWith(
            fetch(event.request)
                .catch(() => caches.match(event.request))
        );
    }
});
