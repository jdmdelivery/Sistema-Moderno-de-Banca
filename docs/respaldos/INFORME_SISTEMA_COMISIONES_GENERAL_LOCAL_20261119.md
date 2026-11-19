# INFORME — Sistema de comisiones general (local, sin publicar)

**Fecha:** 19 de noviembre de 2026  
**Ámbito:** auditoría readonly de producción + corrección/pruebas **solo local**.  
**NO publicado. NO modificado PostgreSQL de producción. NO APK/SUNMI.**

---

## 1. Auditoría — causa general (todas las cajeras)

El balance **no está “roto” por sucursal**: usa el % **vigente al momento de cada venta**.

Si el administrador guarda el 15% **después** de ventas del ciclo, esas ventas quedan en **0%** hasta que se autorice  
**«Aplicar desde inicio del ciclo abierto»**.

Auditoría readonly: `audit_comisiones_todas_cajeras_20261119-185413.json`  
(12 cajeras activas)

| Diagnóstico | Cantidad |
|-------------|----------|
| todas_sin_pct_al_vender | 4 |
| parcial_sin_pct_al_vender | 2 |
| sin_ventas_ciclo | 5 |
| alineado_15 (Wanda) | 1 |

### Foco solicitado (registros actuales)

| Cajera | Usuario | Ventas ciclo | Balance actual | Si autoriza 15% al ciclo | Diagnóstico |
|--------|---------|--------------|----------------|--------------------------|-------------|
| Isaury | 1301 | **7,645.00** | **30.00** | **1,146.75** | Parcial: 7,445 sin % + 200×15%=30 |
| Dayanna | 1302 | **50.00** | **0.00** | **7.50** | Todas sin % al vender |
| Lizbech | 1305 | **4,300.00** | **319.50** | **645.00** | Parcial: 2,170 sin % + resto al 15% |
| Wanda | 1308 | **14,745.00** | **2,211.75** | **2,211.75** | Ya alineada (aplicación previa) |

**Nota Lizbech:** el panel del usuario citó 4,285 / 317.25 / 642.75. La auditoría DB da **4,300 / 319.50 / 645.00** (misma causa parcial; cifras exactas de tickets vigentes). Pagos ciclo: **0** en las cuatro.

---

## 2. Solución general (no parche por usuaria)

Misma lógica para **cualquier** cajera actual o futura:

```
BALANCE = comisión del ciclo ( % al momento de cada venta válida )
        − pagos de comisión del ciclo
```

Autorización expresa (todas las cajeras):

1. Admin elige % + marca **Aplicar desde inicio del ciclo abierto**.  
2. **Vista previa** (`GET /comisiones/preview-aplicar-ciclo`) muestra balance actual → proyectado.  
3. Confirmación con números.  
4. Append-only en `comisiones_cajera` (no borra tickets/pagos/historial).  
5. Idempotente: guardar dos veces el mismo % no duplica.  
6. Respeta pagos previos.  
7. Anulados fuera.  
8. Ciclos cerrados intactos.  
9. DESDE/HASTA del dashboard no altera el balance del ciclo.  
10. Dashboard: sin tarjeta Comisión. Perfil: PORCENTAJE / BALANCE / PAGAR Y CERRAR.

Cache local: `?v=perfil-ciclo-balance-4` · SW `v12`.

---

## 3. Resultado esperado al aplicar 15% al ciclo (cuando autorice en producción)

| Cajera | Balance esperado |
|--------|------------------|
| Isaury 1301 | **RD$1,146.75** |
| Dayanna 1302 | **RD$7.50** |
| Lizbech 1305 | **RD$645.00** |
| Wanda 1308 | RD$2,211.75 (ya OK; idempotente) |

No se aplica en producción en esta fase.

---

## 4. Pruebas locales

```text
pytest tests/test_balance_comision_ciclo.py tests/test_ventas_cajeros.py \
       tests/test_cierre_ciclo_cajera.py tests/test_pagos_comision.py \
       tests/test_panel_iphone.py tests/test_comisiones.py -q
28 passed
```

Incluyen: preview, caso parcial tipo Isaury, dos sucursales, cambio de %, ventas antes/después, anulación, doble guardado, pagos previos, cierre y nuevo ciclo, UI sin tarjeta Comisión.

---

## 5. Esperando autorización

Para producción (paso futuro):

1. Publicar este paquete local.  
2. Por cada cajera con `*_sin_pct_*`: Comisiones → % → vista previa → confirmar aplicar ciclo.  
3. No pagar ni cerrar ciclos salvo que lo indique.
