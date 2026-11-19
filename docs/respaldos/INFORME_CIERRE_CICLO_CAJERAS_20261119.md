# INFORME — Cierre de ciclo de cajeras y perfil simplificado (local)

**Fecha:** 19 de noviembre de 2026  
**Ámbito:** solo local. **Sin Render / PostgreSQL producción / APK / SUNMI.**  
**Estado:** listo para revisión conjunta. **No publicado.**

---

## Resumen

El perfil individual de cada cajera ahora opera por **ciclo abierto**:

- **Ventas del ciclo** (ya no “Ventas netas” ligadas al calendario).
- Ocultos en UI: Ventas brutas, Anulaciones, Recaudación del período (siguen en BD/API/reportes).
- **COMISIÓN GANADA** del ciclo + pagos + **PAGAR COMISIÓN** (parcial, no cierra).
- **PAGAR COMISIÓN Y CERRAR CICLO** (pago completo + corte) o **CERRAR CICLO** si pendiente = 0.
- MI CAJA **no** se pone en cero por pagar/cerrar: exige conciliación previa (MI CAJA = 0 y sin premios pendientes).

---

## Archivos modificados

| Archivo | Cambio |
|---------|--------|
| `apps/api/models.py` | `CierreCicloCajera`; `ciclo_perfil_*` en Usuario |
| `apps/api/db.py` | columnas nuevas en usuarios |
| `apps/api/servicios.py` | métricas de ciclo, pagos por ciclo, `cerrar_ciclo_cajera` |
| `apps/api/main.py` | `GET/POST /comisiones/cierres` |
| `apps/web/app.js` | UI ciclo / ocultar recaudación / cerrar |
| `apps/web/style.css` | (acciones comisión previas) |
| `apps/web/index.html` / `sw.js` | cache-bust `perfil-ciclo-1` / SW `v8` |
| `tests/test_cierre_ciclo_cajera.py` | nuevo |
| `tests/test_ventas_cajeros.py` / `test_panel_iphone.py` | aserciones UI/ciclo |
| `docs/respaldos/MIGRACION_CIERRE_CICLO_CAJERA_20261119.sql` | migración |
| `docs/respaldos/MIGRACION_PAGOS_COMISION_20261119.sql` | (previa, sigue requerida) |

---

## Migraciones necesarias (orden)

1. `MIGRACION_PAGOS_COMISION_20261119.sql` → tabla `pagos_comision`  
2. `MIGRACION_CIERRE_CICLO_CAJERA_20261119.sql` → columnas `ciclo_perfil_*` + `cierres_ciclo_cajera`  

Ambas son reversibles (`DROP` / `DROP COLUMN` documentados). No tocan saldos.

---

## Comportamiento de MI CAJA

| Acción | ¿Cambia MI CAJA? | ¿Cambia Banco General? |
|--------|------------------|-------------------------|
| Pago parcial de comisión | No | No |
| Pago + cierre de ciclo | No | No |
| Entrega de efectivo (operación existente) | Sí (descuenta cajón) | No |

Regla de cierre: si `MI CAJA ≠ 0` o hay premios pendientes → **409** con mensaje de conciliación.

Tras cierre conciliado: nuevo ciclo en `RD$0.00` (ventas, premios, comisión, tickets, fondos/entregas del ciclo).

---

## Pruebas

Suite objetivo (local):

```text
pytest tests/test_cierre_ciclo_cajera.py tests/test_pagos_comision.py \
       tests/test_ventas_cajeros.py tests/test_comisiones.py tests/test_panel_iphone.py -q
```

Cubierto:

- Venta/acumulación, anulación, % 0/10/15  
- Pago parcial (no cierra) y completo + cierre  
- Bloqueo con caja pendiente; cierre con caja conciliada  
- Cierre con % 0 sin pago  
- Nueva venta tras cierre  
- Historial de cierres / isolation entre cajeras  
- Idempotencia de `operacion_id`  
- UI: strings de ciclo y ausencia de recaudación/brutas/anulaciones  

---

## Capturas

`docs/respaldos/capturas_cierre_ciclo_20261119/`

| Archivo | Contenido |
|---------|-----------|
| `_preview_antes_cierre.html` / `perfil_antes_cierre.png` | Perfil con pendiente y botón de cierre |
| `_preview_despues_cierre.html` / `perfil_despues_cierre.png` | Nuevo ciclo en RD$0.00 |

---

## Problemas pendientes / notas

1. **Lista “Ventas por cajero”** usa ventas del ciclo; el filtro DESDE/HASTA ya no corta el acumulado del perfil (sí puede usarse aún en otros reportes administrativos).  
2. **Auditoría de ventas sin %** (`/comisiones/auditoria-sin-porcentaje`) sigue siendo solo informe; sin ajustes retroactivos.  
3. Tras deploy, conviene hard-refresh / reapertura PWA por cache-bust `v8-perfil-ciclo`.  
4. No se unificó el cierre de ciclo con la liquidación quincenal antigua (`liquidaciones_comision`); conviven.

---

## Plan de despliegue (cuando autorice)

1. Backup lógico de PG (sin restore automático).  
2. Aplicar migraciones 1 y 2 en producción.  
3. Un solo deploy Render con: comisión ganada + pagos + cierre de ciclo + cache-bust.  
4. Verificar LIVE: health, SW `v8`, perfil Wanda (ventas del ciclo, sin recaudación).  
5. Correr auditoría sin % y revisar informe.  
6. Probar en PC / iPhone / Samsung: pago parcial, entrega a 0, cierre, nueva venta.

---

## Publicación

**No publicada.** Se solicita autorización explícita para publicar **juntos** en Render estos cambios locales (perfil simplificado + comisión + pagos + cierre de ciclo).
