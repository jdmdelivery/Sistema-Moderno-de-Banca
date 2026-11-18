# Informe — Fix urgente Usuarios iPhone (tarjetas + scroll)

**Fecha:** 2026-11-18  
**Render:** **NO publicado** (esperando autorización)  
**Base previa LIVE:** `fe09417` (insuficiente en iPhone real)

## 1. Causas verificadas

### A) Sigue la tabla en el iPhone
1. **CSS desktop-first:** `.usu-lista-movil{display:none}` y `.usu-tabla-escritorio{display:block}` por defecto. Las tarjetas solo aparecían dentro de `@media(max-width:640px)`.
2. **Doble montaje en el DOM:** JS pintaba tarjetas **y** tabla. Si el CSS móvil no aplicaba (caché SW/HTML antiguo, Safari, PWA), el usuario veía **solo la tabla**.
3. **Tabla ancha en móvil:** `.tabla-scroll table{min-width:720px}` generaba filas enormes / espacios vacíos y scroll horizontal anidado (síntoma de la captura).
4. **Caché:** `index.html` enlazaba `/static/app.js` y `style.css` **sin query**; SW v2 podía dejar cáscara vieja en Safari iOS hasta hard-refresh.

### B) Scroll vuelve arriba
Reproducción con instrumentación de `scrollTo` + `resize` (emulación iPhone):
- Con la **tabla ancha** montada, Safari + barra URL / reflow produce saltos.
- `innerHTML` de `#usu-tabla` al refrescar la lista colapsa altura y el viewport cae a 0.
- `focus()` implícito al editar puede disparar `scrollIntoView`.

**Causa operativa:** tabla móvil + re-render sin preservar `scrollY` + posible menú/resize.  
Tras el fix: 60 s al final de la lista + 8× `resize` → **Y estable** (`4404 → 4404`), `suspiciousToTop: 0`.

## 2. Correcciones (locales)

| Archivo | Cambio |
|---------|--------|
| `apps/web/app.js` | `pintarUsuarios`: en `<901px` **solo tarjetas** en DOM; en escritorio **solo tabla**. Preserva `scrollY`. `editarUsuario` sin focus forzado. `onResizeMenu` re-pinta solo al cruzar breakpoint. |
| `apps/web/style.css` | Mobile-first: tarjetas visibles por defecto; tabla `display:none`; escritorio ≥901px. `overflow-anchor:none` en `#usu-tabla`. |
| `apps/web/index.html` | Cache-bust `?v=usuarios-elite-3` en CSS/JS. |
| `apps/web/sw.js` | Cache `banca-admin-shell-v3-usuarios-fix`. |
| `tests/test_panel_iphone.py` | Assertions del nuevo contrato. |

**No tocado:** Dashboard, calendarios, API, PostgreSQL, ventas/premios/caja/comisiones, SUNMI/APK.

## 3. Pruebas (JS ejecutándose)

| Caso | Resultado |
|------|-----------|
| 360 / 375 / 390 / 430 | Tarjetas, `tables=0`, sin overflow página |
| 1280 | Tabla 8 columnas, `cards=0` |
| Scroll al final + 60 s + resize×6 | Y estable |
| Abrir/cerrar menú al final | Y restaurada |
| EDITAR (sin operación destructiva) | Formulario se llena; no salta a 0 |
| `pytest tests/test_panel_iphone.py` | **7 passed** |

Capturas:
- `docs/capturas/usuarios-elite3-cards-390.png`
- `docs/capturas/usuarios-elite3-cards-430.png`
- `docs/capturas/usuarios-elite3-tabla-1280.png`

## 4. Pendiente en iPhone físico
Tras publicar: hard-refresh / reabrir PWA para tomar SW v3. Confirmar tarjetas y scroll 60 s en Safari real.

## 5. Estado
Corregido y probado **en local**. **Sin despliegue en Render.** Esperando autorización expresa.
