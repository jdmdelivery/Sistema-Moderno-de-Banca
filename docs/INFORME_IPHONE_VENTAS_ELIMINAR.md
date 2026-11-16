# Informe — Dashboard iPhone + Ventas por Cajero + Eliminar usuarios

**Fecha:** 2026-11-15  
**Entorno:** local http://127.0.0.1:8765 · MODO_DESARROLLO=true · SQLite de prueba  
**Publicación Render:** NO realizada (sin autorización)

## 1. Dashboard iPhone
- Encabezado compacto con menú hamburguesa, marca truncable y Salir.
- Tarjetas financieras en 2 columnas (≈180px c/u a 390px); sin overflow horizontal (scrollWidth == clientWidth == 390).
- Safe-area / viewport-fit=cover / PWA conservados.
- Escritorio sin cambios de layout previstos.

## 2. Ventas por Cajero
- Menú + sección **Ventas por Cajero**.
- Filtros: HOY / AYER / ESTA SEMANA / ESTE MES + rango + cajero + sucursal.
- Por cajero: ventas brutas/anulaciones/netas, premios pagados (por quien pagó), recaudación, fondo, entregas, MI CAJA, tickets, última operación, estado.
- **VER DETALLE:** resumen, tickets, premios pagados por ese cajero, movimientos de caja.

## 3. Eliminar usuario
- Acciones: EDITAR / BLOQUEAR / DESBLOQUEAR / ELIMINAR (rojo + confirmación).
- Sin historial → borrado físico; con historial → lógico (ELIMINADO), sesiones invalidadas, auditoría.
- No auto-eliminación, no último admin, supervisor/cajero sin permiso.
- DESBLOQUEAR no reactiva eliminados.
- Filtros: Operativos / ACTIVOS / BLOQUEADOS / ELIMINADOS / Todos.

## 4. Pruebas automatizadas (SQLite aislada)
`\
10 passed
- test_eliminar_sin_historial_es_fisica
- test_eliminar_con_historial_es_logica_y_conserva (incluye no desbloquear)
- test_no_eliminar_ultimo_admin_ni_a_si_mismo
- test_supervisor_no_elimina
- test_exige_confirmacion
- test_dos_cajeros_separados_y_premio_de_otro
- test_supervisor_no_ve_ventas_cajeros
- test_panel_tiene_seccion_ventas_cajeros
- test_css_iphone_sin_overflow_y_safe_area
- test_html_tiene_viewport_fit_cover_y_pwa
`\

## 5. Capturas (emulación Safari iPhone 390×844)
- `docs/capturas/iphone-dashboard-resumen.png`
- `docs/capturas/iphone-ventas-por-cajero.png`
- `docs/capturas/iphone-ventas-cajero-detalle-card.png`
- `docs/capturas/iphone-detalle-cajero.png`

## 6. Checklist manual / browser
| # | Caso | Resultado |
|---|------|-----------|
| 1 | Safari iPhone viewport 390 | OK — layout 2 cols, sin scroll H |
| 2 | PWA meta/viewport-fit | OK (test CSS/HTML) |
| 3–4 | Android/escritorio | No regresiones en CSS desktop |
| 5–11 | Ventas/cálculos/filtros | Cubierto por test_ventas_cajeros + UI local |
| 12 | Permisos | Admin OK / supervisor 403 |
| 13 | Sin scroll horizontal página | Verificado CDP |
| 14 | Módulos menú accesibles | Ventas por Cajero en nav |
| 15–20 | Eliminación | Cubierto por test_eliminar_* (DB aislada) |

**No se eliminaron usuarios de producción.** Esperando autorización para Render.
