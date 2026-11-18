# Informe de impacto — VER PREMIOS SUNMI 0.3.35

**Fecha:** 2026-11-17  
**Alcance:** implementación LOCAL únicamente. **NO publicado en Render. NO instalado en SUNMI.**

## Resumen

Cada cajera solo puede consultar y pagar tickets que ella misma vendió. La regla se aplica en el servidor (`exigir_vendedor_id=operador.id`) para `POST /terminal/tickets/consultar`, `POST /terminal/tickets/pagar` y `GET /terminal/reportes/pendientes`. El panel admin/supervisor no recibe esa restricción de vendedor.

## Archivos tocados

### Servidor
- `apps/api/servicios.py` — `_exigir_vendedor_ticket`, `consultar_ticket` / `pagar_ticket`, `_ticket_resumen` con `detalle_premios`, `reporte_pendientes` / `pendientes_texto` con ámbito real/prueba.
- `apps/api/main.py` — terminal consultar/pagar/pendientes siempre con operador autenticado; pendientes con `detalle_premios=True`.

### APK 0.3.35 (versionCode 40)
- `OpcionesActivity.java` — botón azul **VER PREMIOS** debajo de **PAGAR**.
- `VerPremiosActivity.java` — lista + pago vía la misma API `/terminal/tickets/pagar`.
- `AndroidManifest.xml` — registro de `VerPremiosActivity`.
- `app/build.gradle.kts` — `0.3.35` / `40`.
- `inyectar_impresora.py` — `VERSION = "0.3.35"`.

### Pruebas
- `tests/test_ver_premios_cajera.py` — casos 1–12.
- Ajustes en `test_pago.py`, `test_cuadre.py`, `test_cajas_privadas.py` (antes asumían pago terminal entre cajeras).

## Impacto operativo (cajeras y pagos)

| Tema | Efecto |
|------|--------|
| Pagos históricos | Intactos. No se modifican filas de tickets, movimientos ni saldos existentes. |
| APK 0.3.34 instalada | Sigue funcionando contra el servidor nuevo; si escanea ticket ajeno recibe **ESTE TICKET PERTENECE A OTRA CAJERA** (403). |
| APK 0.3.35 | Añade VER PREMIOS; el escáner PAGAR usa la misma regla de dueño. |
| Misma sucursal, otra cajera | Bloqueado en terminal (cambio respecto a 0.3.34 + servidor anterior). |
| Otra sucursal | Bloqueado en terminal; panel admin puede seguir pagando con `sucursal_id`. |
| Pagos parciales / `operacion_id` | Conservados. |
| Aislamiento sucursales | Conservado. |
| MODO_DESARROLLO | No alterado. Pendientes terminal usan el ámbito real/prueba alineado al modo. |

## Compatibilidad SUNMI V1s Android 6

- `minSdk = 23` (Android 6).
- UI programática (sin recursos nuevos que rompan API 23).
- Java 8, sin APIs modernas en `VerPremiosActivity`.
- Impresora / QN / PL / SP / MONTO FIJO / DISP / COPIAR TICKET: sin cambios de lógica.

## Pruebas

Suite `test_ver_premios_cajera.py` (12 escenarios) + regresión de pago/cuadre/cajas privadas: **aprobadas en local**.

## Publicación

**Pendiente de autorización explícita** para:
1. Publicar servidor en Render.
2. Instalar APK 0.3.35 en dispositivos.
