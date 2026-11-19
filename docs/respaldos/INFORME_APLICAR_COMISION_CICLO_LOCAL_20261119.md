# INFORME — Aplicar comisión al ciclo abierto (local, sin publicar)

**Fecha:** 19 de noviembre de 2026  
**Ámbito:** local + dry-run/respaldo **solo lectura**.  
**Estado:** listo para su autorización. **NO publicado. NO aplicado en PostgreSQL de producción.**

---

## Autorización recibida (alcance)

Aplicar el % desde el **inicio del ciclo abierto**, incluyendo ventas anteriores a la configuración del %, **sin borrar nada**.

## Qué hace el código local

En **Comisiones** → checkbox *Aplicar desde inicio del ciclo abierto*:

1. Inserta (append-only) un registro en `comisiones_cajera` con `vigente_desde` = inicio del ciclo / primera venta.  
2. Recalcula el balance del ciclo: ventas válidas × % − pagos del ciclo.  
3. Excluye anulados.  
4. No toca ciclos cerrados.  
5. **Idempotente:** guardar dos veces el mismo % con la misma autorización **no** duplica filas ni el balance.  
6. Ventas nuevas siguen acumulando.  
7. **No borra** tickets, ventas, premios, usuarios, movimientos ni pagos.  
8. **No** altera MI CAJA ni Banco General.

Dashboard: tarjeta Comisión del RESUMEN sigue oculta. Perfil: PORCENTAJE / BALANCE / PAGAR Y CERRAR.

Cache local: `?v=perfil-ciclo-balance-3` · SW `v11`.

---

## Dry-run Wanda (solo lectura producción)

| Campo | Valor |
|-------|--------|
| Usuario | `1308` Wanda |
| Ventas válidas ciclo | **RD$14,745.00** (11 tickets; 2 anulados fuera) |
| Pagos ciclo | **RD$0** |
| Balance esperado al 15% | **RD$2,211.75** |
| Escrito en PG | **No** |

Evidencia: `docs/respaldos/dryrun_aplicar_ciclo_wanda_20261119-184130.json`

---

## Respaldo preparado (solo lectura)

| Archivo | SHA256 (inicio) |
|---------|-----------------|
| `banca_moderna_pre_aplicar_ciclo_20261119-184218.dump` | `808b4fd2…` |
| `banca_moderna_pre_aplicar_ciclo_20261119-184218.sql` | `e26651f5…` |
| Meta | `backup_pre_aplicar_ciclo_20261119-184218.json` |

`aplicar_en_prod: false` — dump listo; **aún no se aplica** el % en producción.

---

## Pruebas locales

```text
pytest tests/test_balance_comision_ciclo.py tests/test_ventas_cajeros.py \
       tests/test_cierre_ciclo_cajera.py tests/test_pagos_comision.py \
       tests/test_panel_iphone.py -q
23 passed
```

Incluye: Wanda 14,745 → 2,211.75; doble guardado sin duplicar; pagos previos respetados; anulaciones; cierre; nuevo ciclo; UI sin tarjeta Comisión.

---

## Plan cuando autorice publicar + aplicar en producción

1. Publicar commit local a Render.  
2. Verificar health + assets `perfil-ciclo-balance-3`.  
3. En panel: Comisiones → Wanda → **15%** → marcar **Aplicar desde inicio del ciclo abierto** → GUARDAR.  
4. Confirmar balance **RD$2,211.75**.  
5. No DROP / no DELETE de tickets ni historiales.

**Rollback:** redeploy commit anterior; el registro append-only de comisión puede quedar (no borra ventas). Respaldo dump disponible.

---

## Esperando

Su autorización expresa para **publicar en Render** y **aplicar** el 15% al ciclo de Wanda (y demás cajeras que indique) en producción.
