/* Service worker del Panel. Solo cachea la cáscara estática.
   Nunca guarda tokens, tickets, saldos ni respuestas de la API. */
const CACHE = "banca-admin-shell-v8-perfil-ciclo";
const SHELL = [
  "/",
  "/static/style.css",
  "/static/style.css?v=perfil-ciclo-1",
  "/static/app.js",
  "/static/app.js?v=perfil-ciclo-1",
  "/static/icons/icon-192.png",
  "/static/icons/icon-512.png",
  "/manifest.webmanifest",
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  const url = new URL(req.url);
  if (req.method !== "GET") return;
  // API y autenticación: siempre red, sin cache.
  if (
    url.pathname.startsWith("/auth") ||
    url.pathname.startsWith("/usuarios") ||
    url.pathname.startsWith("/sucursales") ||
    url.pathname.startsWith("/terminal") ||
    url.pathname.startsWith("/panel") ||
    url.pathname.startsWith("/reportes") ||
    url.pathname.startsWith("/auditoria") ||
    url.pathname.startsWith("/health") ||
    url.pathname.startsWith("/sorteos") ||
    url.pathname.startsWith("/resultados") ||
    url.pathname.startsWith("/tickets") ||
    url.pathname.startsWith("/ganadores") ||
    url.pathname.startsWith("/caja") ||
    url.pathname.startsWith("/entregas") ||
    url.pathname.startsWith("/fondos") ||
    url.pathname.startsWith("/comisiones") ||
    url.pathname.startsWith("/limites") ||
    url.pathname.startsWith("/tabla") ||
    url.pathname.startsWith("/tipos") ||
    url.pathname.startsWith("/fuente") ||
    url.pathname.startsWith("/importaciones") ||
    req.headers.get("Authorization")
  ) {
    event.respondWith(fetch(req));
    return;
  }
  // Cáscara: red primero; si falla, cache.
  event.respondWith(
    fetch(req)
      .then((resp) => {
        const copia = resp.clone();
        if (resp.ok && (url.pathname === "/" || url.pathname.startsWith("/static") || url.pathname.endsWith("webmanifest"))) {
          caches.open(CACHE).then((c) => c.put(req, copia));
        }
        return resp;
      })
      .catch(() => caches.match(req))
  );
});
