const CACHE_NAME = 'emergencias-cache-v1';

// Archivos básicos que quieres que estén disponibles offline
const OFFLINE_URLS = [
  '/',
  '/offline',
  '/static/css/styles.css',          // ajusta a tus archivos reales
  '/static/js/app.js',              // si tienes
  '/static/icons/icon-192x192.png',
  '/static/icons/icon-512x512.png'
];

self.addEventListener('install', (event) => {
  console.log('[SW] Install');
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(OFFLINE_URLS);
    })
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  console.log('[SW] Activate');
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

self.addEventListener('fetch', (event) => {
  // Estrategia: network first, fallback a cache
  event.respondWith(
    fetch(event.request)
      .then((response) => {
        // Guardar copia en cache
        const respClone = response.clone();
        caches.open(CACHE_NAME).then((cache) => {
          cache.put(event.request, respClone);
        });
        return response;
      })
      .catch(() => {
        // Si falla red → intentar cache
        return caches.match(event.request).then((cached) => {
          if (cached) return cached;

          // Si es navegación y no hay nada, mostrar /offline
          if (event.request.mode === 'navigate') {
            return caches.match('/offline');
          }
        });
      })
  );
});
