// Fleet Manager Service Worker v1
const CACHE_NAME = 'fleetmgr-v1';

// Static assets to pre-cache on install
const PRECACHE_URLS = [
    'https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css',
    'https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css',
    'https://cdn.jsdelivr.net/npm/flatpickr/dist/flatpickr.min.css',
    'https://code.jquery.com/jquery-3.7.1.min.js',
    'https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js',
    'https://cdn.jsdelivr.net/npm/flatpickr',
    'https://cdn.jsdelivr.net/npm/select2@4.1.0-rc.0/dist/js/select2.min.js',
];

// Install: pre-cache key static assets
self.addEventListener('install', function(event) {
    event.waitUntil(
        caches.open(CACHE_NAME).then(function(cache) {
            return Promise.allSettled(
                PRECACHE_URLS.map(function(url) {
                    return cache.add(url).catch(function() {});
                })
            );
        })
    );
    self.skipWaiting();
});

// Activate: clear old caches
self.addEventListener('activate', function(event) {
    event.waitUntil(
        caches.keys().then(function(cacheNames) {
            return Promise.all(
                cacheNames
                    .filter(function(name) { return name !== CACHE_NAME; })
                    .map(function(name) { return caches.delete(name); })
            );
        })
    );
    self.clients.claim();
});

// Fetch strategy
self.addEventListener('fetch', function(event) {
    var request = event.request;
    var url;
    try { url = new URL(request.url); } catch(e) { return; }

    // Only handle GET
    if (request.method !== 'GET') return;

    // Skip browser-extension requests
    if (url.protocol !== 'http:' && url.protocol !== 'https:') return;

    // Skip API, admin, and auth routes — always fresh
    var skipPaths = ['/api/', '/login', '/logout', '/backup'];
    if (skipPaths.some(function(p) { return url.pathname.startsWith(p); })) return;

    // Cache-first for CDN assets (external origin)
    if (url.hostname !== self.location.hostname) {
        event.respondWith(
            caches.match(request).then(function(cached) {
                if (cached) return cached;
                return fetch(request).then(function(response) {
                    if (response && response.ok) {
                        var clone = response.clone();
                        caches.open(CACHE_NAME).then(function(cache) {
                            cache.put(request, clone);
                        });
                    }
                    return response;
                }).catch(function() { return caches.match(request); });
            })
        );
        return;
    }

    // Network-first for same-origin pages (always latest data)
    // Falls back to cache if offline
    event.respondWith(
        fetch(request).then(function(response) {
            if (response && response.ok && response.type === 'basic') {
                var clone = response.clone();
                caches.open(CACHE_NAME).then(function(cache) {
                    cache.put(request, clone);
                });
            }
            return response;
        }).catch(function() {
            return caches.match(request).then(function(cached) {
                if (cached) return cached;
                // Offline fallback for navigation
                if (request.destination === 'document') {
                    return new Response(
                        '<html><body style="font-family:sans-serif;text-align:center;padding:40px;">' +
                        '<h2>You are offline</h2>' +
                        '<p>Please check your internet connection.</p>' +
                        '<button onclick="location.reload()" style="padding:12px 24px;font-size:1rem;cursor:pointer;">Retry</button>' +
                        '</body></html>',
                        { headers: { 'Content-Type': 'text/html' } }
                    );
                }
            });
        })
    );
});
