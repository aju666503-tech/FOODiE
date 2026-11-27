const CACHE = 'foodie-shell-v6';
const SHELL = [
  '/', '/static/manifest.json', '/static/icons/foodie.svg',
  '/static/icons/icon-192.png', '/static/icons/icon-512.png',
  '/static/icons/apple-touch-icon.png',
  ...Array.from({ length: 12 }, (_, i) => `/static/images/products/${i + 1}.webp`)
];
self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', event => {
  event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(key => key !== CACHE).map(key => caches.delete(key)))).then(() => self.clients.claim()));
});
self.addEventListener('fetch', event => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== 'GET' || url.origin !== self.location.origin) return;
  if (url.pathname.endsWith('/css/style.css') || url.pathname.endsWith('/js/app.js')) {
    event.respondWith(fetch(request, { cache: 'no-store' }).then(response => {
      if (response.ok) caches.open(CACHE).then(cache => cache.put(request, response.clone()));
      return response;
    }).catch(() => caches.match(request)));
    return;
  }
  if (url.pathname.startsWith('/static/images/') || url.pathname.startsWith('/static/icons/')) {
    event.respondWith(caches.match(request).then(cached => cached || fetch(request).then(response => {
      if (response.ok) caches.open(CACHE).then(cache => cache.put(request, response.clone()));
      return response;
    })));
    return;
  }
  if (request.mode === 'navigate') {
    event.respondWith(fetch(request).catch(() => caches.match('/')));
  }
});
