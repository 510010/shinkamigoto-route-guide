/* 上五島航路案内 Service Worker
   静的ファイルと data.json をキャッシュし、オフラインでも時刻表を確認できるようにする */
const CACHE_NAME = 'kamigoto-route-guide-v1';
const APP_SHELL = [
  './',
  './index.html',
  './style.css',
  './app.js',
  './data.json',
  './manifest.json',
  './icon.svg'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => cache.addAll(APP_SHELL))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);

  // Leaflet 等の CDN はキャッシュ優先（取得できたら保存）
  if (url.origin !== self.location.origin) {
    event.respondWith(
      caches.match(req).then((hit) => hit || fetch(req).then((res) => {
        const copy = res.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(req, copy));
        return res;
      }))
    );
    return;
  }

  // data.json は stale-while-revalidate（まずキャッシュを返し、裏で更新）
  if (url.pathname.endsWith('data.json')) {
    event.respondWith(
      caches.open(CACHE_NAME).then((cache) =>
        cache.match(req).then((hit) => {
          const network = fetch(req).then((res) => {
            if (res.ok) cache.put(req, res.clone());
            return res;
          }).catch(() => hit);
          return hit || network;
        })
      )
    );
    return;
  }

  // その他の同一オリジンはキャッシュ優先
  event.respondWith(
    caches.match(req, { ignoreSearch: true }).then((hit) => hit || fetch(req).then((res) => {
      const copy = res.clone();
      caches.open(CACHE_NAME).then((cache) => cache.put(req, copy));
      return res;
    }))
  );
});
