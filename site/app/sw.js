// Offline + instant load. The page and the job feed come from cache first and refresh in the background;
// fonts and the pdf.js reader are cached once. Nothing personal passes through here (it lives in localStorage).
const CACHE = "ie-app-v1";
const SHELL = ["./", "index.html", "manifest.webmanifest", "icon-192.png", "icon-512.png", "prep.json"];
const ONCE = /^https:\/\/(fonts\.gstatic\.com|fonts\.googleapis\.com|cdnjs\.cloudflare\.com\/ajax\/libs\/pdf\.js\/)/;

self.addEventListener("install", e => {
  // One missing file (e.g. icons not deployed yet) must not block the rest.
  e.waitUntil(caches.open(CACHE).then(c => Promise.all(SHELL.map(u => c.add(u).catch(() => {})))).then(() => self.skipWaiting()));
});

self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});

// Fetch and, in the same tick, keep a copy for next time; the worker stays alive until the copy is stored.
function network(e) {
  let copy = null;
  const res = fetch(e.request).then(r => { copy = r.ok && r.type !== "opaque" ? r.clone() : null; return r; });
  e.waitUntil(res.then(() => copy && caches.open(CACHE).then(c => c.put(e.request, copy))).catch(() => {}));
  return res;
}

self.addEventListener("fetch", e => {
  const req = e.request, url = new URL(req.url);
  if (req.method !== "GET") return;
  const app = url.origin === location.origin && (url.pathname.startsWith(new URL("./", location).pathname) || url.pathname.endsWith("/feed.json"));
  // App and feed: stale-while-revalidate (cached answer now, refreshed for next time). Fonts/pdf.js: cache once.
  if (app) e.respondWith(caches.match(req, { ignoreSearch: true }).then(hit => { const net = network(e); return hit || net; }));
  else if (ONCE.test(req.url)) e.respondWith(caches.match(req).then(hit => hit || network(e)));
});
