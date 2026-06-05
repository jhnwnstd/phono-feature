/**
 * Service worker.
 *
 * BUILD_ID and PRECACHE are stamped in by web/scripts/build.py.
 * BUILD_ID is a hash of the precache list; any change in the
 * shipped file set bumps it, so a new build gets a new cache name
 * and the activate handler garbage-collects the old ones.
 *
 * Caching strategy:
 *
 *   index.html       stale-while-revalidate (so a new build is
 *                    picked up on the next visit, never deeper
 *                    than one visit's lag).
 *   hashed assets    cache-first (immutable per content hash;
 *                    a changed file means a changed URL).
 *   Pyodide CDN      cache-first, populated on first successful
 *                    fetch. NOT precached in install() because a
 *                    transient CDN failure would break the install.
 *   anything else    pass through.
 *
 * skipWaiting is intentionally not called: hot-swapping bundles
 * under a live Pyodide instance is hazardous. The new SW activates
 * once the user closes the last tab.
 */

const BUILD_ID = "__BUILD_ID__";
const CACHE_NAME = `features-cache-${BUILD_ID}`;
const PRECACHE = __PRECACHE_LIST__;
const PYODIDE_ORIGIN = "https://cdn.jsdelivr.net";

self.addEventListener("install", (event) => {
    event.waitUntil(
        caches.open(CACHE_NAME).then((cache) => cache.addAll(PRECACHE)),
    );
});

self.addEventListener("activate", (event) => {
    event.waitUntil(
        caches.keys().then((keys) =>
            Promise.all(
                keys
                    .filter((k) => k !== CACHE_NAME)
                    .map((k) => caches.delete(k)),
            )
        ),
    );
});

self.addEventListener("fetch", (event) => {
    const req = event.request;
    if (req.method !== "GET") return;

    let url;
    try {
        url = new URL(req.url);
    } catch {
        return;
    }
    const sameOrigin = url.origin === self.location.origin;
    const pyodideCdn = url.origin === PYODIDE_ORIGIN;
    if (!sameOrigin && !pyodideCdn) return;

    const isIndexHtml = sameOrigin && (
        url.pathname.endsWith("/") || url.pathname.endsWith("/index.html")
    );

    if (isIndexHtml) {
        event.respondWith(staleWhileRevalidate(event, req));
    } else {
        event.respondWith(cacheFirst(req));
    }
});

async function cacheFirst(req) {
    const cache = await caches.open(CACHE_NAME);
    const cached = await cache.match(req);
    if (cached) return cached;
    try {
        const response = await fetch(req);
        // Don't cache error responses; a transient 5xx shouldn't
        // pin the user to an error page.
        if (response.ok) cache.put(req, response.clone());
        return response;
    } catch (_e) {
        return cached || Response.error();
    }
}

async function staleWhileRevalidate(event, req) {
    const cache = await caches.open(CACHE_NAME);
    const cached = await cache.match(req);
    const networkPromise = fetch(req)
        .then((response) => {
            if (response.ok) cache.put(req, response.clone());
            return response;
        })
        .catch(() => cached || Response.error());
    // waitUntil keeps the SW alive long enough for the cache.put
    // to land, even when we return the cached response immediately.
    // Without it, an idle eviction between page close and fetch
    // completion would drop the update and the user would see the
    // stale build for an extra visit.
    event.waitUntil(networkPromise);
    return cached || networkPromise;
}
