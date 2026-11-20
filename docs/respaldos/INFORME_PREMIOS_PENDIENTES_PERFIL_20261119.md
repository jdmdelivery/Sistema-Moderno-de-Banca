# INFORME — PREMIOS PENDIENTES en perfil del cajero

**Fecha:** 2026-11-19 (UTC−4)  
**Alcance:** LOCAL únicamente  
**Publicación Render:** **NO** (pendiente de autorización)  
**PostgreSQL producción / APK / SUNMI:** **NO tocados**

---

## Cambio

Octava tarjeta **PREMIOS PENDIENTES** en el detalle individual del cajero (`verDetalleCajero`), en escritorio y móvil.

### Orden (2 columnas × 4 filas)

| | Columna A | Columna B |
|---|---|---|
| Fila 1 | Ventas del ciclo | Premios del ciclo |
| Fila 2 | MI CAJA | Fondo asignado |
| Fila 3 | Entregas | Tickets vigentes |
| Fila 4 | Tickets anulados | **PREMIOS PENDIENTES** |

### Fuente de datos (sin nueva contabilidad)

- `detalle_ventas_cajero` expone `resumen.premios_pendientes` = `indicadores_caja.premios_pendientes_mios`
- También en `comision.premios_pendientes` = `_condiciones_cierre_ciclo.premios_pendientes`
- Misma regla: `_premios_pendientes_filtro` + `_premio_pendiente_valido` + `_importe_sin_cobrar` (incluye saldos parciales; excluye pagados / anulados / no ganadores / sin resultado válido / otros cajeros)

### UI

- Mismo tamaño/borde/altura de las tarjetas existentes
- Importe en color amarillo (`--amarillo`) + borde/fondo ámbar
- Grid forzado a 2 columnas también en escritorio (antes el media query usaba 4 columnas)

### Archivos tocados

- `apps/api/servicios.py` — campo en resumen + comision
- `apps/web/app.js` — octava tarjeta
- `apps/web/style.css` — estilo pendiente + 2 columnas desktop
- `apps/web/index.html` / `sw.js` — cache bust `premios-pendientes-1`
- `tests/test_premios_pendientes_perfil.py` — nuevo

---

## Pruebas locales

```
pytest tests/test_premios_pendientes_perfil.py -q
→ 7 passed
```

| # | Caso | Resultado |
|---|---|---|
| 1 | Sin pendientes | `RD$0.00` |
| 2 | Un premio pendiente | `600.00` (= cierre) |
| 3 | Varios pendientes | `1800.00` |
| 4 | Multi-lotería (solo confirmadas) | `600` → luego `900` |
| 5 | Parcial / completo | baja a `0` tras pago; reaparece saldo restante |
| 6 | Anulado + no ganador | `0.00` |
| 7 | Aislamiento cajero/sucursal | importes independientes |

Coincidencia con validación de cierre: `resumen.premios_pendientes == comision.premios_pendientes`.

---

## Capturas

Carpeta: `docs/respaldos/premios-pendientes-perfil/`

| Archivo | Vista |
|---|---|
| `captura-desktop-8-tarjetas.png` | Escritorio 900px — 8 tarjetas alineadas |
| `captura-iphone-8-tarjetas.png` | iPhone 390×844 — 2 columnas |
| `captura-android-8-tarjetas.png` | Android 360×800 — 2 columnas |
| `preview-ocho-tarjetas.html` | Preview local del layout |

---

## No modificado

MI CAJA, ventas/premios del ciclo, fondo, entregas, tickets, comisiones, pago de comisiones, cierre de ciclo, CONTROL DE CAJEROS, Banco General, APK, SUNMI, movimientos contables, registros de premios.

---

## Publicación

Listo en local. **No publicar en Render hasta autorización explícita.**
