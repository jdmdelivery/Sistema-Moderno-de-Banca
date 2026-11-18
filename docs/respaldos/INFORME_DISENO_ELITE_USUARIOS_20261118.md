# Informe — Diseño élite Usuarios (móvil tarjetas / escritorio tabla)

**Fecha:** 2026-11-18  
**Alcance:** Solo presentación visual de USUARIOS + pulido visual del menú  
**Render:** **NO publicado**

## Archivos modificados

| Archivo | Motivo |
|---------|--------|
| `apps/web/app.js` | Render dual: tarjetas móviles + tabla escritorio; mismas acciones (`editarUsuario` / `bloquearUsuario` / `desbloquearUsuario` / `eliminarUsuario`); iniciales robustas |
| `apps/web/index.html` | Hero azul USUARIOS; filtro con clase `usu-filtro` |
| `apps/web/style.css` | Estilos premium de tarjetas/hero; menú activo azul; show/hide móvil↔escritorio |
| `apps/web/sw.js` | Cache shell `v2-usuarios` para no servir JS/CSS viejo |
| `tests/test_panel_iphone.py` | Assertions del diseño dual |

## Qué se conservó

- Filtros, permisos, confirmaciones, endpoints y aislamiento por sucursal.
- Un solo `#usu-id` / formulario (sin IDs duplicados).
- Handlers globales únicos (sin listeners duplicados).

## Pruebas

### Automatizadas
`pytest tests/test_panel_iphone.py` → **7 passed**

### Emulación CDP
| Ancho | Vista | Resultado |
|------:|-------|-----------|
| 360 | Tarjetas | OK · sin overflow página |
| 375 | Tarjetas | OK |
| 390 | Tarjetas + EDITAR rellena formulario | OK · scroll estable |
| 430 | Tarjetas + menú activo Usuarios | OK |
| 1280 | Tabla completa (8 columnas) | OK · tarjetas ocultas |

Capturas:
- `docs/capturas/usuarios-hero-360.png`
- `docs/capturas/usuarios-tarjetas-390.png`
- `docs/capturas/usuarios-menu-430.png`
- `docs/capturas/usuarios-tabla-1280.png`

## Limitaciones

- Safari iOS / Chrome Android físicos pendientes de confirmación visual.
- El service worker cachea la cáscara: tras publicar, la v2 fuerza refresco; en local conviene hard-refresh una vez.

## Confirmaciones

- PostgreSQL / ventas / premios / caja / comisiones / SUNMI / APK: **no tocados**
- Sin despliegue en Render
