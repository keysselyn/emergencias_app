// Nombre de caché (incrementa la versión al cambiar archivos)
const CACHE_NAME = 'emergencias-cache-v1';

// Recursos críticos a precachear (carga inicial + offline)
const PRECACHE_URLS = [
  '/',              // home
  '/offline',       // página offline
  '/manifest.webmanifest',
  // Bootstrap desde CDN no se puede precachear aquí; se cacheará dinámicamente
];

// Instalar SW: precache
self.addEventListener('install', event => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE_NAME);
    await cache.addAll(PRECACHE_URLS);
    self.skipWaiting();
  })());
});

// Activar SW: limpiar versiones viejas
self.addEventListener('activate', event => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(
      keys.map(k => (k !== CACHE_NAME ? caches.delete(k) : null))
    );
    self.clients.claim();
  })());
});

// Estrategia: Network First para páginas, Cache First para estáticos
self.addEventListener('fetch', event => {
  const req = event.request;
  const url = new URL(req.url);

  // Solo GET (no interferir en POST/PUT/DELETE)
  if (req.method !== 'GET') return;

  // Requests a HTML (navegación): Network First con fallback a caché/offline
  if (req.headers.get('accept') && req.headers.get('accept').includes('text/html')) {
    event.respondWith(networkFirst(req));
    return;
  }

  // Estáticos (CSS/JS/IMG): Cache First con fallback a red
  if (url.pathname.startsWith('/static/') || /\.(css|js|png|jpg|jpeg|gif|svg|webp|ico)$/.test(url.pathname)) {
    event.respondWith(cacheFirst(req));
    return;
  }

  // Otros: intentar red y si falla, caché
  event.respondWith(networkFirst(req));
});

async function cacheFirst(req) {
  const cache = await caches.open(CACHE_NAME);
  const cached = await cache.match(req);
  if (cached) return cached;
  const fresh = await fetch(req);
  cache.put(req, fresh.clone());
  return fresh;
}

async function networkFirst(req) {
  const cache = await caches.open(CACHE_NAME);
  try {
    const fresh = await fetch(req);
    // Cachear copia si es exitoso
    if (fresh && fresh.status === 200) {
      cache.put(req, fresh.clone());
    }
    return fresh;
  } catch (e) {
    const cached = await cache.match(req);
    if (cached) return cached;
    // Fallback genérico a la página offline si es navegación
    if (req.mode === 'navigate' || (req.headers.get('accept') || '').includes('text/html')) {
      const offline = await cache.match('/offline');
      if (offline) return offline;
    }
    // Último recurso: respuesta vacía
    return new Response('', { status: 503, statusText: 'Offline' });
  }
}
