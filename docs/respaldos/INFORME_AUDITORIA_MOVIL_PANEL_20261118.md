# Informe — Auditoría y corrección móvil Panel del Consorcio

**Fecha:** 2026-11-18  
**Proyecto:** Sistema de Banca Moderna  
**Entorno de prueba:** local `http://127.0.0.1:8765` (SQLite)  
**Producción Render:** **NO publicado** (sin autorización)

## 1. Causas verificadas

| Problema | Causa exacta |
|----------|--------------|
| Scroll vuelve al inicio al deslizar | En móvil, al ocultar/mostrar la barra URL el navegador dispara `resize`. El handler llamaba `sincronizarEstadoMenuInicial()` → `setMenuAbierto(false)` → `bloquearScrollFondo(false)` → **`window.scrollTo(0, MENU_SCROLL_Y)`** aunque el menú nunca estuvo abierto (`MENU_SCROLL_Y` = 0). |
| DESDE / HASTA / CONSULTAR ausentes en móvil | Existían en HTML pero con clase `solo-escritorio` (`display:none` bajo 640px). |
| Encabezado / marca cortados | `.marca` en móvil usaba `white-space:nowrap` + ellipsis; sesión y SALIR competían por el mismo renglón. |
| Tabla Usuarios ensancha / ilegible | Tabla ancha sin compactación específica; faltaba reforzar scroll horizontal local vs. scroll de página. |

## 2. Archivos modificados

| Archivo | Motivo |
|---------|--------|
| `apps/web/app.js` | Fix scroll: `MENU_SCROLL_BLOQUEADO`, `onResizeMenu` solo al cruzar 901px; no `scrollTo` si el fondo no estaba bloqueado. |
| `apps/web/index.html` | DESDE/HASTA/CONSULTAR visibles; bloque `inicio-rango`; SALIR; clase `cards-inicio`. |
| `apps/web/style.css` | Header móvil en grid; marca sin ellipsis; fechas móviles; cards 2 cols; Usuarios compacto + scroll H; `isolation:isolate`. |
| `tests/test_panel_iphone.py` | Actualiza expectativas: calendarios visibles + assertions del fix de scroll + Usuarios. |

## 3. Correcciones (detalle)

1. **Scroll:** `bloquearScrollFondo(false)` es no-op si no había bloqueo. `resize` solo re-sincroniza menú al cambiar escritorio↔móvil.
2. **Calendarios:** se reutilizan `#ini-desde` / `#ini-hasta` / `#ini-consultar` y `/reportes/inicio` (misma validación `HASTA < DESDE`, misma zona del servidor).
3. **Dashboard:** chips HOY/AYER/15 DÍAS conservados; tarjetas en 2 columnas móvil / 3 escritorio; valores y fórmulas intactas.
4. **Usuarios:** filas más compactas; `overflow-x` en `.tabla-scroll`; página sin ensancharse (`scrollWidth == clientWidth`).

## 4. Pruebas ejecutadas

### Automatizadas
`pytest tests/test_panel_iphone.py` → **7 passed**

### Emulación browser (CDP)
| # | Caso | Viewport | Resultado |
|---|------|----------|-----------|
| 1 | Dashboard responsive / marca / SALIR | iPhone 390×844 | OK |
| 2 | DESDE/HASTA visibles + CONSULTAR | 390 / 360 | OK |
| 3 | CONSULTAR rango real `2026-11-16→18` | local | OK · zona `America/Santo_Domingo` |
| 4 | HOY / AYER / 15 DÍAS | local | OK |
| 5 | Validación HASTA &lt; DESDE | local | OK mensaje error |
| 6 | Scroll: `resize` no vuelve a 0 | pad artificial | OK (`before=after`) |
| 7 | Abrir/cerrar menú restaura Y | local | OK (700→700) |
| 8 | Usuarios: scroll H interno, página 390 | 390 | OK (`pageScrollW=390`, wrap 358→901) |
| 9 | Menú móvil + escritorio 1280 | 1280 | sidebar abierto, sin overflow |
| 10 | Samsung 360×800 dashboard | 360 | OK |

Capturas: `docs/capturas/movil-usuarios-iphone390.png`, `docs/capturas/movil-dashboard-samsung360.png`

## 5. Pendiente en dispositivos reales

- Safari iOS físico (barra URL real + gesto).
- Chrome Android físico (Samsung).
- Orientación landscape en ambos.
- Confirmar visual del chip de sucursal con nombres largos.

## 6. Confirmaciones de seguridad

- **PostgreSQL / estructura:** no modificados.
- **Lógica de negocio** (ventas, tickets, premios, caja, comisiones, permisos, aislamiento): no modificados.
- **SUNMI / APK:** no tocados.
- **Render:** sin publish, sin restart, sin deploy.

## 7. Estado

Correcciones **solo locales**. Esperando autorización expresa antes de publicar.
