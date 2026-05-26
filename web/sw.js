/* Service worker for the phonology engine web app.
 *
 * web/scripts/build.py stamps in BUILD_ID and PRECACHE at build
 * time. BUILD_ID changes when any shipped asset changes (it's a
 * hash of the precache list), so a new build means a new cache
 * name, which the activate handler garbage-collects.
 *
 * Caching strategy by URL class:
 *
 * - index.html: stale-while-revalidate. Serves the cached copy
 *   instantly (fast warm load), kicks off a background fetch to
 *   pick up a new build on the next visit. Without this, the
 *   user is permanently pinned to whichever build they first
 *   visited.
 *
 * - Locally-hashed assets (main.HASH.js, python_bundle.HASH.zip,
 *   etc.): cache-first. They're immutable per the content hash;
 *   if the bytes change the URL changes, and the new URL misses
 *   the cache and goes to network anyway.
 *
 * - Pyodide CDN (jsdelivr): cache-first. The URLs are pinned by
 *   version, so they're effectively immutable too. We don't
 *   precache them in install() because a transient CDN failure
 *   would break the SW install -- we cache on first successful
 *   fetch instead.
 *
 * - Anything else: pass through to the network. We don't want
 *   to be the cache for arbitrary URLs.
 *
 * Update semantics: a new SW installs in the background but does
 * NOT skipWaiting -- the audit advice was to avoid hot-swapping
 * bundles under a live Pyodide instance. Activation happens once
 * the user closes the last tab; until then the old SW stays in
 * charge of any open page.
 */

const BUILD_ID = "__BUILD_ID__";
const CACHE_NAME = `features-cache-${BUILD_ID}`;
const PRECACHE = __PRECACHE_LIST__;
const PYODIDE_ORIGIN = "https://cdn.jsdelivr.net";

self.addEventListener("install", (event) => {
    event.waitUntil(
        caches.open(CACHE_NAME).then((cache) => cache.addAll(PRECACHE))
    );
});

self.addEventListener("activate", (event) => {
    event.waitUntil(
        caches.keys().then((keys) =>
            Promise.all(
                keys
                    .filter((k) => k !== CACHE_NAME)
                    .map((k) => caches.delete(k))
            )
        )
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
        url.pathname.endsWith("/")
        || url.pathname.endsWith("/index.html")
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
        if (response.ok) {
            // Cache successful responses. Failed responses are
            // not cached so a transient 5xx doesn't pin us to
            // an error page until the cache is cleared.
            cache.put(req, response.clone());
        }
        return response;
    } catch (e) {
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
    // If we return the cached response, the background fetch is
    // still in flight. waitUntil keeps the SW alive until the
    // cache.put completes -- otherwise an idle eviction between
    // page close and fetch completion would lose the update, and
    // the user would see the stale build on the next visit too.
    event.waitUntil(networkPromise);
    return cached || networkPromise;
}
