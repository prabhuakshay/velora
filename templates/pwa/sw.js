// Pages are never cached: they hold signed-in data that must not outlive logout.
// Only the offline page and its stylesheet are kept, for navigations that fail.
const OFFLINE_URL = "{% url 'offline' %}";
const CSS_URL = "{% static 'css/app.css' %}";
// Named after the hashed stylesheet, so a new build replaces the cache.
const CACHE = `offline ${CSS_URL}`;

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll([OFFLINE_URL, CSS_URL])));
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))),
  );
  self.clients.claim();
});

self.addEventListener("fetch", (e) => {
  if (e.request.mode === "navigate") {
    e.respondWith(fetch(e.request).catch(() => caches.match(OFFLINE_URL, { ignoreVary: true })));
  } else if (new URL(e.request.url).pathname === CSS_URL) {
    e.respondWith(fetch(e.request).catch(() => caches.match(CSS_URL)));
  }
});
