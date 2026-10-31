const CACHE_PREFIX = "desvinculaciones-pwa-";
const CACHE_NAME = `${CACHE_PREFIX}shell-v2`;
const OFFLINE_URL = new URL("offline.html", self.registration.scope);

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => cache.add(OFFLINE_URL))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((key) =>
            (key.startsWith(CACHE_PREFIX) && key !== CACHE_NAME)
            || key === "desvinculaciones-shell-v1"
          )
          .map((key) => caches.delete(key))
      )
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET" || new URL(request.url).origin !== self.location.origin) {
    return;
  }

  event.respondWith(
    fetch(request).catch(async () => {
      if (request.mode === "navigate") {
        const cache = await caches.open(CACHE_NAME);
        return (await cache.match(OFFLINE_URL.href)) || Response.error();
      }
      return Response.error();
    })
  );
});
