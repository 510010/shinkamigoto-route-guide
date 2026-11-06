/* 上五島航路案内 Service Worker
   同一オリジンはネットワーク優先（オンライン時は常に最新を取得し、キャッシュを更新）、
   オフライン時のみキャッシュにフォールバックして時刻表を確認できるようにする */
const CACHE_NAME = 'kamigoto-route-guide-v11';
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

  // Leaflet 等の CDN はキャッシュ優先（取得できたら保存）。地図タイルは容量が大きく
  // 内容も変わらないため、ネットワーク優先にはしない
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

  // 同一オリジン（HTML/CSS/JS/data.json）はネットワーク優先：
  // 成功したらキャッシュを更新してそのまま返し、失敗（オフライン）時のみキャッシュを返す。
  // これにより公開後の更新がホーム画面追加した PWA でも次の起動で反映される
  event.respondWith(
    fetch(req).then((res) => {
      if (res.ok) {
        const copy = res.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(req, copy));
      }
      return res;
    }).catch(async () => {
      const hit = await caches.match(req, { ignoreSearch: true });
      if (hit) return hit;
      // ページ遷移でキャッシュにも無い場合はアプリシェルを返す
      if (req.mode === 'navigate') {
        const shell = await caches.match('./index.html');
        if (shell) return shell;
      }
      return Response.error();
    })
  );
});
