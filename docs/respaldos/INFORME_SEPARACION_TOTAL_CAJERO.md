# Separación total de ventas y premios por cajero

Fecha: 2026-11-17 · **Sin deploy Render** · **Sin APK 0.3.34** · Datos históricos intactos

## 1. Auditoría (antes de tocar más código)

### Hallazgo principal (ya identificado)
`premios_por_pagar` (PAGAR en terminal) sumaba por `sucursal_id` sin `usuario_id` → 02191 veía RD$4,100 de 12345.

### Estado del resto de endpoints terminal (operador)

| Endpoint | Filtro personal | Riesgo residual |
|----------|-----------------|-----------------|
| `/terminal/sorteos` (MI CAJA / MI VENTA / PAGAR) | `usuario.id` | Corregido |
| `/terminal/entregas*` | dueño = sesión | OK |
| `/terminal/caja/transacciones` | `usuario_id` sesión | OK |
| `/terminal/caja/cuadre` | limitado a operador | OK |
| `/terminal/reportes/dia\|mes` | `alcance=cajero` | Spoof ahora forzado |
| `/terminal/reportes/resumen` | `propio=operador.id` | PREMIOS PAGADOS alineados a **pagador** |
| `/terminal/reportes/pendientes` | `propio=operador.id` | OK |
| `/terminal/tickets/pagar` | paga quien autentica; no se restringe al vendedor | **Sin cambio** (requisito) |
| Panel web `/reportes/*` | admin/sucursal | Operador no tiene token panel |

### Ejemplo LIVE (solo lectura)
- 12345: pendientes propios **4100** · caja prueba **4230**
- 02191: pendientes propios **0**
- Admin Peguero: míos **0** · sucursal **4100** (campo aparte)
- Castillo `0000`: **0**

## 2. Cambios realizados (código local)

### `apps/api/servicios.py`
- `indicadores_caja`: `premios_por_pagar` = solo del autenticado; campos `premios_pendientes_sucursal` / `_globales`; alias `mi_venta` (= `ventas_dia`).
- `_premios_pendientes_filtro`: filtro opcional `usuario_id` / `sucursal_id`.
- `_bloque_periodo` y `reporte_resumen`: **ventas/pendientes = vendedor**; **premios pagados = quien cobró** (`_premios_pagados_por_cajero` / `_premios_pagados_sucursal`).

### `apps/api/main.py`
- `/terminal/reportes/dia` y `/mes`: si `rol==operador`, **fuerza** `alcance="cajero"` (ignora spoof por query).

### `apps/web/app.js`
- Etiqueta de inicio: “Premios pendientes sucursal” para admin vs propios.

### Tests
- `tests/test_cajas_privadas.py`: aislamiento PAGAR, multi-sucursal, spoof alcance, pagador ≠ vendedor.

## 3. Reglas contables (sin cambiar permisos de pago)

| Concepto | Atribución |
|----------|------------|
| MI VENTA / pendientes PAGAR | Cajero que **vendió** |
| MI CAJA / PREMIOS PAGADOS (reportes personales) | Cajero que **pagó** (movimiento de caja) |
| Resumen admin sucursal | Toda la banca autorizada |
| Global | Solo JDMCASHNOW (`super_admin`) |

## 4. Pruebas

```
23 passed  (test_cajas_privadas + pantalla_pago + pagos_parciales + test_caja)
```

Escenarios cubiertos:
- Dos cajeros misma banca: ventas/caja/PAGAR aislados.
- Spoof `alcance=sucursal`: no revela ajenos.
- Sucursales distintas: sin mezcla.
- B paga ticket de A: pendiente de A → 0; PREMIOS PAGADOS del día van a B; permiso de pago intacto.
- Regresión multi-sorteo / pagos parciales: OK.

Fingerprints LIVE (sin escritura destructiva): tickets 16 · jugadas 140 · mov. caja 16 · caja 12345 = 4230.

## 5. Pendiente de su autorización

LIVE en Render **sigue con el código anterior** hasta que autorice publicar.  
Tras el deploy (sin APK), 02191 verá PAGAR **0** y 12345 verá **4100**.
