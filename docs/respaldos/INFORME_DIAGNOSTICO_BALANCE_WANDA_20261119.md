# INFORME — Diagnóstico y corrección local BALANCE DE COMISIÓN (Wanda)

**Fecha:** 19 de noviembre de 2026  
**Ámbito:** solo local + auditoría **solo lectura** de PostgreSQL.  
**Estado:** **NO publicado.** Sin cambios en PG producción / APK / SUNMI.

---

## Diagnóstico Wanda (usuario `1308`)

| Campo | Valor |
|-------|--------|
| Cajera | Wanda (id 22) |
| Sucursal | BANCA CASTILLO (`1301`, id 1) |
| Ventas del ciclo (válidas) | **RD$14,745.00** (11 tickets; 2 anulados aparte) |
| Porcentaje vigente | **15%** |
| Balance mostrado | **RD$0.00** |
| Pagos / cierres | ninguno |
| `es_prueba` | true (servicio en MODO DESARROLLO) |

### Causa raíz (no es un fallo de suma)

El 15% se registró en `comisiones_cajera` el **2026-11-19 16:42:39**.  
**Todas** las ventas del ciclo tienen `vendido_en` **anterior** a esa hora (última venta 15:14:38).

La regla del sistema: comisión = % **vigente al momento de cada venta**.  
Sin fila de % en ese momento → **0%**. El % actual **no** se aplica solo.

| Escenario | Importe |
|-----------|---------|
| Balance según % registrados al vender (correcto hoy) | **RD$0.00** |
| Si se autoriza 15% desde inicio del ciclo (14,745 × 0.15) | **RD$2,211.75** |

Evidencia lectura:  
`docs/respaldos/audit_wanda_balance_comision_20261119-182124.json`  
`docs/respaldos/audit_wanda_balance_comision_detalle_20261119.json`

---

## Corrección local (sin publicar)

1. **Nota en perfil** cuando hay ventas del ciclo sin % al vender (`nota_balance`).  
2. **Autorización expresa** en Comisiones: checkbox  
   *«Aplicar desde inicio del ciclo abierto»* → `aplicar_desde_inicio_ciclo: true`.  
   Crea un registro con `vigente_desde` = inicio del ciclo / primera venta.  
   No inventa % distinto; no toca MI CAJA ni Banco General.  
3. Se mantiene: anulaciones fuera del balance, filtro DESDE/HASTA no altera el ciclo, pago+cierre reinicia a 0, nuevas ventas acumulan.  
4. Dashboard: sigue **sin** tarjeta Comisión (`perfil-ciclo-balance-3` / SW `v11`).

### Para corregir Wanda en producción (cuando autorice)

Tras publicar este paquete, en **Comisiones**: Wanda → 15% → marcar  
**Aplicar desde inicio del ciclo abierto** → guardar.  
Balance esperado: **RD$2,211.75**.  
Eso escribe una fila nueva en `comisiones_cajera` (no reescribe tickets).

---

## Pruebas locales

```text
pytest tests/test_balance_comision_ciclo.py tests/test_ventas_cajeros.py \
       tests/test_cierre_ciclo_cajera.py tests/test_pagos_comision.py \
       tests/test_panel_iphone.py -q
22 passed
```

Incluye: ventas antes del % → 0; autorización ciclo → 2211.75; ventas sucesivas 15%; anulación; filtro fechas; pago+cierre; nuevo ciclo; UI sin tarjeta Comisión.

---

## Capturas

`docs/respaldos/capturas_balance_wanda_20261119/`

| Archivo | Contenido |
|---------|-----------|
| `antes_balance_cero.png` | 15% vigente + balance RD$0 + nota |
| `despues_autorizacion_ciclo.png` | Balance RD$2,211.75 |

Preview HTML: `docs/respaldos/_preview_balance_wanda.html`

---

## Publicación

**Pendiente de su autorización.** No se hizo push ni deploy Render.
