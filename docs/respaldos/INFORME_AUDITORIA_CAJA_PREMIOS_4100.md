# Auditoría y corrección — caja / premios por usuario

Fecha: 2026-11-17 · Alcance: todas las sucursales · **Sin deploy Render** · **Sin tocar APK 0.3.34**

## Respuestas (informe final)

### 1. ¿De quién son realmente los RD$4,100?

De **12345 (LA MAQUINA)**, BANCA PEGUERO, bolsa de **prueba**.

| Ticket | Vendedor | Estado | Pendiente |
|--------|----------|--------|-----------|
| 47 | 12345 | ganador | 3500.00 |
| 41 | 12345 | ganador | 400.00 |
| 40 | 12345 | ganador | 200.00 |
| **Total** | | | **4100.00** |

Su caja de prueba sigue en **RD$4,230** (efectivo en cajón). Los 4,100 son **premios confirmados sin pagar**, no el saldo de caja.

Evidencia: `docs/respaldos/audit_caja_premios_4100_20261117-010205.json`

### 2. ¿Por qué aparecían en la sesión del otro usuario?

Bug de **presentación del indicador** en `indicadores_caja` → `premios_por_pagar`.

El terminal (APK) muestra ese campo como **PAGAR**. La función `_premios_por_pagar_sucursal` sumaba tickets con:

- `Ticket.sucursal_vendedora_id == usuario.sucursal_id`
- **sin** filtrar `Ticket.usuario_id`

Cualquier cajero/admin de PEGUERO veía el total de la banca (4100), aunque su `mi_caja` fuera 0.

`MI CAJA` sí era individual (`saldo_caja` / `saldo_caja_prueba` del usuario autenticado).

### 3. ¿Error de presentación o de contabilidad?

**Presentación / indicador.**  
No se alteraron tickets, jugadas, pagos, fondos, entregas ni saldos históricos. La contabilidad por ticket y por movimiento de caja ya era por usuario; el header PAGAR mezclaba el agregado de sucursal.

### 4. ¿Qué se corrigió? (código local, pendiente de publicar)

Archivos:

- `apps/api/servicios.py` — `indicadores_caja` + `_premios_pendientes_filtro`
- `apps/web/app.js` — etiqueta de inicio distingue pendientes de sucursal vs propios
- `tests/test_cajas_privadas.py` — regresión: otro cajero ve PAGAR = 0

Comportamiento nuevo:

| Campo | Quién lo ve | Significado |
|-------|-------------|-------------|
| `premios_por_pagar` / `premios_pendientes_mios` | Todos (APK usa el primero) | Solo tickets del **usuario autenticado** |
| `premios_pendientes_sucursal` | admin / supervisor | Suma de la banca |
| `premios_pendientes_globales` | super_admin | Todas las sucursales |

Permisos de **pagar un ticket válido**: sin cambio arbitrario.

### 5. ¿Se verificó el aislamiento en todas las sucursales?

| Escenario | Resultado |
|-----------|-----------|
| A. 12345 | Caja prueba 4230; pendientes propios 4100 |
| B. 02191 (nuevo PEGUERO) | Tras fix: PAGAR propio **0** (antes veía 4100) |
| C. Admin Peguero | Tras fix: míos **0**; sucursal **4100** (campo separado) |
| D. Castillo `0000` | Pendientes propios **0**; no mezcla PEGUERO |
| E. Cambio de usuario | Causa no era caché de sesión; era query sin `usuario_id`. `mi_caja` ya era correcto |
| F. Multi-sorteo / parciales | Tests existentes OK (`test_pantalla_pago`, `test_pagos_parciales_multi_sorteo`) |

Simulación SQL post-fix: `docs/respaldos/sim_fix_premios_indicadores_20261117-010408.json`  
Pytest: **16 passed** (cajas privadas + pantalla pago + pagos parciales).

### 6. ¿Permanecieron intactos todos los datos históricos?

Sí (solo lectura + cambio de código no desplegado):

- tickets: 16  
- jugadas: 140  
- movimientos_cajera: 16  
- caja 12345 prueba: 4230.00  

No se borró, reinició ni recalculó saldos/tickets/premios.

---

## Importante

**LIVE en Render sigue con el código anterior** hasta que autorice el despliegue.  
En el teléfono, 02191 / admin pueden seguir viendo PAGAR 4100 hasta publicar este fix.

Cuando autorice: push + deploy Render **sin** tocar APK SUNMI 0.3.34.
