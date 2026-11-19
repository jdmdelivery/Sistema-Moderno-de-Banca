# INFORME — Corrección de 4 fallas pre-publicación (local)

**Fecha:** 2026-11-18  
**Ámbito:** Solo laboratorio local. Sin publish Render, sin push, sin cambio de `MODO_DESARROLLO`, sin PostgreSQL de producción, sin instalación APK.

## Veredicto

**APTO para publicación** (pendiente de su autorización explícita).

---

## 1. Auditoría de las cuatro fallas

### 1.1 / 1.2 `resumen_periodo` (dos pruebas)

| | |
|---|---|
| **Pruebas** | `tests/test_resumen_periodo.py` → `test_hoy_ayer_y_rango_imprimen_el_periodo_sin_alterar_saldos` y `test_mes_completo_incluye_todos_los_dias_y_totales` |
| **Esperado** | Operador con `alcance=sucursal` → **HTTP 403** |
| **Obtenido** | **HTTP 200** (alcance forzado en silencio a `cajero`) |
| **Causa raíz** | En `apps/api/main.py`, los endpoints de resumen día/mes/imagen reescribían `alcance="sucursal"` a `"cajero"` cuando el rol no era admin/supervisor, ocultando el rechazo que ya implementa `servicios.resumen_dia` / `resumen_mes`. |
| **¿Anterior a recibos?** | El clamp silencioso se alineó con rutas de imagen; el rechazo 403 en servicios ya existía. No es un bug de fórmulas ni de saldos. |
| **¿Afecta función real?** | Sí: un spoof de privilegio debía denegarse. Las fórmulas de ventas/premios/entregas **no** se tocaron. |
| **Solución** | Quitar el clamp; dejar que servicios responda 403. |

### 1.3 Semilla del nombre de banca

| | |
|---|---|
| **Prueba** | `tests/test_semilla_prueba.py` |
| **Esperado** | `BANCA CASTILLO (PRUEBA)` / `JOSE (PRUEBA)` en BD vacía de lab |
| **Obtenido** | Nombre sin `(PRUEBA)` (o semilla que no coincidía) |
| **Causa raíz** | Semilla de lab alterada; debía conservar el marcador y **no** renombrar si ya hay sucursales. |
| **¿Anterior a recibos?** | Relacionada con limpieza de `(PRUEBA)` en papel (impresión); la semilla de BD no debe perder el marcador. |
| **¿Afecta función real?** | Solo datos de lab en BD vacía. En BD con sucursales existentes: early-return, no sobrescribe. |
| **Solución** | Restaurar nombres `(PRUEBA)` + `if db.query(Sucursal).first(): return`. |

### 1.4 `ventas_cajeros` — HTTP 403

| | |
|---|---|
| **Prueba** | `tests/test_ventas_cajeros.py::test_dos_cajeros_separados_y_premio_de_otro` |
| **Esperado (código)** | Pago de ticket ajeno en terminal → **403 OTRA CAJERA** |
| **Obtenido** | 403 correcto; la prueba pedía flujo de cobro cruzado desactualizado |
| **Causa raíz** | Aislamiento terminal por `exigir_vendedor_id` (correcto). La prueba estaba desfasada respecto a la regla de negocio. |
| **¿403 correcto?** | **Sí.** Cajero no puede consultar/pagar ticket de otra cajera. No se debilitó auth ni aislamiento entre empresas. |
| **Solución** | Actualizar la prueba: assert 403 en cobro ajeno; cobro propio con fondos; reporte panel admin intacto. |

### Fallas secundarias tras quitar el clamp (investigadas, no ocultadas)

Tras eliminar el clamp, tres pruebas antiguas aún esperaban 200 con “forzar cajero”:

- `tests/test_cajas_privadas.py` (×2 spoof)
- `tests/test_resumen_dia.py` (spoof operador)

**Ajuste:** esperar **403** (misma política de seguridad que `resumen_periodo`). El supervisor con `alcance=sucursal` sigue en 200.

Además, `test_el_comprobante_suma_solo_lo_cobrado` fallaba con `assert "99" not in texto` por falsos positivos de `Ticket:` / `S/N:` en el nuevo layout. Se precisó a `assert "Número ganador: 99" not in texto` (intención real: no listar número no cobrado).

---

## 2. Archivos modificados (esta corrección)

| Archivo | Cambio |
|---|---|
| `apps/api/main.py` | Sin clamp silencioso de `alcance` en día/mes/imagen |
| `apps/api/seed.py` | Nombres `(PRUEBA)` + no sobrescribir sucursales existentes |
| `tests/test_ventas_cajeros.py` | 403 cobro ajeno + cobro propio |
| `tests/test_cajas_privadas.py` | Spoof → 403 |
| `tests/test_resumen_dia.py` | Spoof → 403 |
| `tests/test_sunmi_y_reversion.py` | Aserción `Número ganador: 99` |

No se modificaron balances, ventas, premios, entregas ni movimientos para hacer pasar pruebas.

---

## 3. Regresión completa

| Suite | Resultado | Log |
|---|---|---|
| **376 pruebas** | **376 passed** | `docs/respaldos/regresion_completa_post_4fallas_20261118.log` |
| Recibos + parciales + reimpresión + compat APK | **30 passed** | `docs/respaldos/regresion_recibos_parciales_compat_20261118.log` |
| Focus 4 fallas + semilla + spoof + comprobante | **10 passed** | `docs/respaldos/regresion_focus_4fallas_fix_20261118.log` |

### Controles adicionales

- **Pagos parciales / reimpresiones:** cubiertos por `test_sunmi_y_reversion` + `test_pagos_parciales_multi_sorteo` (OK).
- **Compat APK 0.4.2:** `test_opcion_b_validacion_local` (`versionCode=44`, `0.4.2-universal`) + `test_compat_apk_034_servidor_nuevo` (OK).
- **Migraciones:** siguen aditivas (`ALTER … ADD COLUMN` en `db.py`); sin DROP de datos de negocio.
- **Impresión servidor:** endpoints PNG en `main.py` (`/terminal/tickets/.../imagen`, pago, resumen, lab) listos para integrar en el despliegue cuando autorice.

---

## 4. Riesgos pendientes (no bloquean el veredicto de código)

1. **LIVE aún sin rutas PNG** hasta el deploy autorizado (OpenAPI LIVE previo carecía de esos paths).
2. **`MODO_DESARROLLO` en Render** no se tocó (solo lectura previa); cualquier cambio requiere autorización aparte.
3. **APK 0.4.2** no se instaló en banqueras (prohibido hasta autorización).
4. Publicación Render / push: **detenidos a la espera de su OK**.

---

## 5. Conclusión

Las cuatro fallas de Fase 1 quedaron resueltas por causa raíz (seguridad explícita 403, semilla de lab correcta, prueba de ventas_cajeros alineada al aislamiento real). Regresión **376/376** en verde.

**Estado: APTO para publicación.**

**Detenido. Esperando su autorización para cualquier publish / push / instalación.**
