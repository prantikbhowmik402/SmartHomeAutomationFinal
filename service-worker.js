// service-worker.js
// Place this file in your /static/ folder
// Handles: PWA caching + Push Notifications

const CACHE_NAME = "smarthome-v2";
const URLS_TO_CACHE = [
  "/",
  "/static/style.css",
  "/static/script.js",
  "/static/manifest.json",
];

// ── INSTALL: Cache core files ──────────────────────────
self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      console.log("[SW] Caching core files");
      return cache.addAll(URLS_TO_CACHE);
    })
  );
  self.skipWaiting();
});

// ── ACTIVATE: Clean old caches ─────────────────────────
self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((key) => key !== CACHE_NAME)
          .map((key) => caches.delete(key))
      )
    )
  );
  self.clients.claim();
});

// ── FETCH: Serve from cache when offline ──────────────
self.addEventListener("fetch", (event) => {
  // Only cache GET requests
  if (event.request.method !== "GET") return;

  event.respondWith(
    fetch(event.request)
      .then((response) => {
        // Update cache with fresh response
        const clone = response.clone();
        caches.open(CACHE_NAME).then((cache) => {
          cache.put(event.request, clone);
        });
        return response;
      })
      .catch(() => {
        // Offline fallback
        return caches.match(event.request);
      })
  );
});

// ── PUSH NOTIFICATIONS ────────────────────────────────
self.addEventListener("push", (event) => {
  let data = { title: "Smart Home", body: "Something happened!", icon: "/static/icon-192.png", tag: "smarthome" };

  if (event.data) {
    try {
      data = { ...data, ...event.data.json() };
    } catch {
      data.body = event.data.text();
    }
  }

  const options = {
    body:    data.body,
    icon:    data.icon || "/static/icon-192.png",
    badge:   "/static/icon-192.png",
    tag:     data.tag  || "smarthome",
    vibrate: [200, 100, 200],
    data:    { url: data.url || "/" },
    actions: data.actions || [],
  };

  event.waitUntil(
    self.registration.showNotification(data.title, options)
  );
});

// ── NOTIFICATION CLICK ────────────────────────────────
self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = event.notification.data?.url || "/";

  event.waitUntil(
    clients.matchAll({ type: "window" }).then((windowClients) => {
      // If app is already open, focus it
      for (const client of windowClients) {
        if (client.url.includes(self.location.origin) && "focus" in client) {
          return client.focus();
        }
      }
      // Otherwise open new window
      if (clients.openWindow) {
        return clients.openWindow(url);
      }
    })
  );
});