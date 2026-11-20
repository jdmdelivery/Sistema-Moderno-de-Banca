# INFORME — CONTROL DE CAJEROS (LOCAL)

**Fecha:** 2026-11-19  
**Ámbito:** Solo laboratorio local. **Sin publish Render. Sin PostgreSQL de producción. Sin APK/SUNMI. Sin ajustes reales en datos vivos.**

## Objetivo

Pantalla administrativa para ver cajeros de la sucursal, identificar balances negativos (MI CAJA) y aplicar **ajuste contable de banca negativa** hasta RD$0.00, sin tocar Banco General ni inventar efectivo.

## Auditoría contable

| Concepto | Regla reutilizada | Resultado |
|---|---|---|
| BALANCE REAL | `mi_caja_de` / `indicadores_caja` (mismo que MI CAJA) | Coincide |
| Ventas / premios / neto | `_periodo_ventas_cajero` (período filtrado) | Solo período |
| Entregado al admin | Suma `Entrega` del período | Solo período |
| Ajustes mostrados | `ajustes_ciclo` del ciclo abierto | Incluidos en cuadre una sola vez |
| Fórmula cuadre | `fondo + recaudación − entregas + ajustes` | Sin doble conteo |
| Tipo de movimiento | `ajuste_banca_negativa` / `_prueba` vía `mover_caja_cajera` | Solo cajón del cajero |
| Banco General | No se crea `MovimientoSaldo` ni se altera `sucursal.saldo_actual` | Protegido en servicio |
| No es venta/premio/fondo | Flags en respuesta + tipo dedicado | Confirmado |
| Historial | Tabla `ajustes_caja_cajera` + auditoría | Permanente / auditable |
| Idempotencia | `operacion_id` único + reintento seguro | Confirmado en pytest |
| Concurrencia | `SELECT … FOR UPDATE` sobre el cajero + `balance_visto` | 409 si cambió |

**Conclusión:** el ajuste solo acredita el cajón (prueba o real según modo) hasta cubrir la deuda. No descuenta Banco General. No elimina ventas, premios, entregas ni fondos previos.

## Endpoints (locales)

- `GET /control-cajeros?desde=&hasta=&sucursal_id=`
- `POST /control-cajeros/ajuste` `{usuario_id, monto, motivo, operacion_id, balance_visto}`
- `GET /control-cajeros/ajustes`

Permisos: `requiere_rol("admin")` + `assert_usuario_en_alcance` / `resolver_filtro_sucursal`.

## UI

- Menú **Cajeros → CONTROL DE CAJEROS**
- Tarjetas, tabla (escritorio) / cards (móvil)
- Modal **AJUSTAR BALANCE DEL CAJERO** (solo negativos)
- **VER** reutiliza el perfil existente (`verDetalleCajero`)
- Filtros HOY / AYER / 15 DÍAS / DESDE-HASTA / ACTUALIZAR  
  → afectan métricas de período; **BALANCE REAL permanece acumulado (MI CAJA)**

## Pruebas (`tests/test_control_cajeros.py`)

Ejecutado localmente con `DATABASE_URL` vacío (SQLite temporal de conftest):

```
6 passed
```

| # | Caso | Resultado |
|---|---|---|
| 1 | Cajero positivo | PASS |
| 2 | Cajero negativo (DEUDA primero) | PASS |
| 3 | Cajero cero (CUADRADO) | PASS |
| 4 | Ajuste completo → 0 | PASS |
| 5 | Ajuste parcial | PASS |
| 6 | Ajuste > deuda | PASS (400) |
| 7 | Duplicado `operacion_id` | PASS (idempotente) |
| 8 | Balance cambiado antes de confirmar | PASS (409) |
| 9 | Supervisor / cajero sin permiso | PASS (403/401) |
| 10 | Integridad MI CAJA + Banco General | PASS |
| 11 | `ajustes_ciclo` en indicadores | PASS |

No se ejecutaron ajustes reales contra datos de producción ni Render.

## Capturas

Carpeta: `docs/respaldos/capturas_control_cajeros_20261119/`

| Archivo | Contenido |
|---|---|
| `01_control_escritorio.png` | Pantalla completa escritorio |
| `02_control_telefono.png` | Vista móvil (cards) |
| `03_cajero_negativo.png` | Fila DEUDA + AJUSTAR |
| `04_modal_ajustar.png` | Modal AJUSTAR |

Preview HTML: `docs/respaldos/_preview_control_cajeros.html` (sin API).

## Archivos modificados / nuevos

- `apps/api/models.py` — `AjusteCajaCajera`
- `apps/api/servicios.py` — `indicadores_caja` (+ajustes), `control_cajeros`, `aplicar_ajuste_banca_negativa`, `listar_ajustes_caja`
- `apps/api/main.py` — rutas `/control-cajeros*`
- `apps/web/index.html` — menú + sección + modal
- `apps/web/app.js` — carga, tabla, modal, refresh
- `apps/web/style.css` — estilos CC
- `tests/test_control_cajeros.py`
- `docs/respaldos/_preview_control_cajeros.html`
- `docs/respaldos/_capturar_control_cajeros.py`
- `docs/respaldos/capturas_control_cajeros_20261119/*`
- Este informe

## Confirmación de no publicación

| Recurso | Estado |
|---|---|
| Render | **Intacto** — no deploy |
| PostgreSQL producción | **Intacto** — no conexión/migración |
| APK / SUNMI | **Sin cambios** |
| Comisiones | **Sin cambios de reglas** |
| Datos existentes | **Sin borrados / sin reinicio de ciclos** |

## Listo para publicar

Implementación local completa. **Publicar únicamente cuando usted lo autorice.**
