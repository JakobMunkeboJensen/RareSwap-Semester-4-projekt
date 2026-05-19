// Service Worker — giver offline-splash og PWA-installation
const CACHE = "rareswap-v1";
const OFFLINE = ["/", "/static/styles.css"];

self.addEventListener("install", function (e) {
  e.waitUntil(
    caches.open(CACHE).then(function (c) { return c.addAll(OFFLINE); })
  );
  self.skipWaiting();
});

self.addEventListener("activate", function (e) {
  e.waitUntil(
    caches.keys().then(function (keys) {
      return Promise.all(keys.filter(function (k) { return k !== CACHE; }).map(function (k) { return caches.delete(k); }));
    })
  );
  self.clients.claim();
});

self.addEventListener("fetch", function (e) {
  // Lad API-kald og POST gå direkte til netværket
  if (e.request.method !== "GET" || e.request.url.includes("/api/")) {
    return;
  }
  e.respondWith(
    fetch(e.request).catch(function () {
      return caches.match(e.request).then(function (r) { return r || caches.match("/"); });
    })
  );
});
