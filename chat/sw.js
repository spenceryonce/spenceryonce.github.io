// Free AI service worker: offline shell + cached libraries. Model weights are cached by the voice libraries themselves.
const V = 'fac-v1';
const SHELL = ['./', './manifest.webmanifest', './icon-192.png', './icon-512.png', './apple-touch-icon.png'];
self.addEventListener('install', e => { self.skipWaiting(); e.waitUntil(caches.open(V).then(c => c.addAll(SHELL)).catch(() => {})); });
self.addEventListener('activate', e => e.waitUntil((async () => {
  for (const k of await caches.keys()) if (k !== V && k.startsWith('fac-')) await caches.delete(k);
  await self.clients.claim();
})()));
self.addEventListener('fetch', e => {
  const req = e.request; if (req.method !== 'GET') return;
  const u = new URL(req.url);
  // The app page: always try the network first so updates arrive, fall back to the cached copy offline.
  if (req.mode === 'navigate' && u.origin === location.origin && u.pathname.startsWith('/chat')) {
    e.respondWith(fetch(req).then(r => { const c = r.clone(); caches.open(V).then(x => x.put('./', c)); return r; }).catch(() => caches.match('./')));
    return;
  }
  // Our own versioned vendor bundles never change either.
  if (u.origin === location.origin && u.pathname.startsWith('/chat/vendor/')) {
    e.respondWith(caches.open(V).then(async c => { const hit = await c.match(req); if (hit) return hit; const r = await fetch(req); if (r.ok) c.put(req, r.clone()); return r; }));
    return;
  }
  // Versioned libraries from CDNs never change: serve from cache after the first download.
  if ((u.hostname === 'cdnjs.cloudflare.com' || u.hostname === 'cdn.jsdelivr.net') && /@\d|\/\d+\.\d+/.test(u.pathname)) {
    e.respondWith(caches.open(V).then(async c => {
      const hit = await c.match(req); if (hit) return hit;
      const r = await fetch(req); if (r.ok && r.type !== 'opaque') c.put(req, r.clone()); return r;
    }));
  }
});
