# INFORME FINAL — CONTROL DE CAJEROS + CAJA NEGATIVA + RECUPERACIÓN AUTOMÁTICA

**Fecha:** 2026-11-19  
**Ámbito:** EXCLUSIVO LOCAL. **Sin publish Render. Sin PostgreSQL de producción. Sin APK/SUNMI.**

## Veredicto

**Auditoría COMPLETA.**

- Recuperación automática por ventas: **ya cubierta por la contabilidad existente** (`mover_caja_cajera` con signo +1 en cada venta). No se crearon movimientos artificiales.
- Pago con MI CAJA insuficiente: **permitido** (deuda contable).
- Ajuste admin: **solo deuda vigente**, con `balance_visto` + `FOR UPDATE`; no deja balance positivo; no toca Banco General.
- PostgreSQL aislado `127.0.0.1:55432` / `banca_moderna_aislada`: **levantado y auditado** (casos A–G PASARON).

## 1. Recuperación automática (regla de ventas)

| Hallazgo | Detalle |
|---|---|
| ¿Se bloquea venta con MI CAJA negativa? | **No.** `vender()` no exige saldo positivo. |
| ¿Cómo se recupera? | Cada venta suma **una sola vez** vía `venta` / `venta_prueba`. |
| ¿Movimientos artificiales? | **No.** |
| ¿Ajuste automático? | **No.** |
| ¿Comisiones / ciclos? | **Sin cambios.** |

Ejemplo verificado (Caso A):

`-1000 → venta 500 → -500 → venta 500 → 0 → venta 500 → +500`

## 2. Pago con premio > MI CAJA

- Terminal/APK: permite (sin cambiar APK).
- Panel: confirma si `premio_excede_mi_caja`.
- Ticket pagado una sola vez; Banco General intacto en modo prueba.
- Caso B: `2000 − 3000 = -1000` — **PASS**.

## 3. CONTROL DE CAJEROS

- `BALANCE REAL = MI CAJA` (misma fuente).
- DEUDA / POSITIVO / CUADRADO; AJUSTAR solo si negativo.
- Negativos primero.

## 4. Ajuste = deuda **actual**

| Escenario | Resultado |
|---|---|
| Deuda original -1000, venta 600 → deuda -400; ajuste máx 400 | PASS (Caso D) |
| Admin confirma con `balance_visto` viejo tras venta | **409** (Caso E) |
| Recuperación total a 0 | AJUSTAR desaparece; 0 ajustes auto (Caso F) |
| Ajuste no deja positivo / no toca Banco General | PASS |

## 5. Contabilidad del ajuste

- Tipo: `ajuste_banca_negativa[_prueba]` → `mover_caja_cajera` (+1).
- Entra en `ajustes_ciclo` / cuadre **una vez**.
- Historial en `ajustes_caja_cajera` + auditoría.
- No es venta, premio ni fondo.

## 6. PostgreSQL aislado

| Antes | Ahora |
|---|---|
| Puerto 55432 caído / roles inexistentes | Clúster nuevo local `banca-moderna-pg-aislada` |
| Auditoría marcada incompleta | **COMPLETA** |

Runner: `docs/respaldos/_auditoria_recuperacion_pg_aislada.py`

```
PASÓ  0. PostgreSQL aislado
PASÓ  A. Recuperación por ventas
PASÓ  B. Premio > MI CAJA
PASÓ  C. Recuperación tras premio
PASÓ  D. Ajuste tras recuperar parcial
PASÓ  E. Venta durante ajuste
PASÓ  F. Recuperación completa sin ajuste
PASÓ  G. Anulación revierte recuperación
PASÓ  Conciliación MI CAJA = CONTROL
```

## 7. Pruebas SQLite (pytest)

```
tests/test_recuperacion_caja_negativa.py → 9 passed
(+ suites previas de pago/control)
```

Nota: concurrencia de dos ajustes en SQLite no serializa `FOR UPDATE`; en PostgreSQL sí. El runner PG valida el entorno real de bloqueos.

## 8. Compatibilidad

- APK / SUNMI: **sin modificar**.
- Escáner, VER PREMIOS, parciales, QN/PL/SP: usan el mismo `_cobrar_premios` / `vender`.
- Si en el futuro se desea diálogo de deuda en la APK, requeriría actualización autorizada.

## 9. Producción

| Recurso | Estado |
|---|---|
| Render | Intactos |
| PostgreSQL producción | Intactos |
| Datos / comisiones / ciclos | Sin borrados ni reinicios |

## Archivos relevantes

- `apps/api/servicios.py` — venta, pago, control, ajuste
- `apps/api/main.py` — rutas
- `apps/web/app.js` / `index.html` / `style.css` — UI
- `tests/test_recuperacion_caja_negativa.py`
- `tests/test_pago_caja_negativa.py`
- `docs/respaldos/_auditoria_recuperacion_pg_aislada.py`
- Este informe

**Listo para publicar únicamente cuando usted lo autorice.**
