# Auditoría final — JDMCASHNOW / aislamiento (antes de publicar)

**Fecha:** 2026-11-16  
**Alcance:** local + evidencias de snapshots LIVE previos.  
**NO hecho:** publish Render, migraciones LIVE, cambios APK, commit.

---

## Veredicto

| Pregunta | Resultado |
|----------|-----------|
| ¿APK 0.3.34 sigue sin reinstalar? | **SÍ** — contrato `/terminal/login` intacto |
| ¿JDMCASHNOW puede ser Super Admin? | **SÍ** (probado en BD de tests + script aislado) |
| ¿Alfredo intacto? | **SÍ** — rol `admin`, misma clave; snapshot LIVE `sucursal_id=1` (CASTILLO) |
| ¿CASTILLO ↛ PEGUERO y viceversa? | **SÍ** tras endurecer rutas (tests de auditoría) |
| ¿Historial intacto por diseño? | **SÍ** — cambios aditivos; sin DELETE/TRUNCATE de negocio |
| ¿Listo para publicar YA? | **NO** — falta autorización + secuencia COMPAT (ver §7–9) |

---

## 1. APK SUNMI 0.3.34

- Contrato instalado: `POST /terminal/login` solo con `usuario` + `clave` (+ opcionales `dispositivo_id`…).
- Sesión, ventas, pagos y caja van por API; no hay BD local de tickets.
- `estado_aprobacion`: cajeros **ya aprobados** (LIVE y migración) siguen entrando; solo **nuevos** pendientes reciben 401 con mensaje de texto (la APK ya muestra `detail`).
- Evidencia previa: `INFORME_COMPAT_APK_0334_BACKEND_MULTISUCURSAL.md` + publish `b2ef3cc`.
- **No se modifica ni reinstala APK** en este plan.

---

## 2. Login JDMCASHNOW

- Script: `docs/respaldos/_crear_jdmcashnow_super_admin.py` (clave por `JDMCASHNOW_CLAVE`).
- Tests: `test_super_admin_fase3`, `test_auditoria_final_aislamiento` → login `rol=super_admin`.
- Panel: sección Super Admin (cola, resumen, permisos).

---

## 3. Alfredo / CASTILLO / PEGUERO

Snapshot LIVE `snapshot_pre_deploy_multisucursal_20261116-223855.json`:

| Usuario | Rol implícito | `sucursal_id` |
|---------|---------------|---------------|
| `admin` (Alfredo) | admin | **1** = BANCA CASTILLO |
| `0000`, `jose`, `0219` | operadores | 1 CASTILLO |
| `12345` | operador | 2 PEGUERO |

El script de creación **no** cambia rol ni hash de Alfredo.

---

## 4–5. Aislamiento API (CASTILLO ↔ PEGUERO)

La auditoría detectó fugas en reportes/tickets/caja/fondos/entregas/móvil/admin mientras el alcance de sucursales ya filtraba. **Se cerraron en local** con `permisos.resolver_filtro_sucursal` / `assert_ticket_en_alcance`.

Rutas ahora bloqueadas cruzadas (403) o filtradas a la banca del actor, entre otras:

- `/sucursales`, `/movimientos`, `/recargar`
- `/usuarios`, `/terminales`
- `/panel/tickets*`, `/ganadores*`, `/reportes/*`, `/movil/admin`
- `/caja/transacciones`, `/cuadres`, `/panel/caja/*`
- `/fondos`, `/entregas`, `/comisiones*`, `/auditoria` (filtrada por actores de la banca)

Prueba: `tests/test_auditoria_final_aislamiento.py`.

### Seguimiento post-auditoría ([auditor](f6c06025-f3b0-4185-8853-fed411e95270))

El mapa de fugas del auditor coincidió con el endurecimiento ya aplicado; se cerraron además los residuales que aún faltaban:

- `POST/PUT/revocar/reactivar /terminales` → `assert_sucursal_permitida`
- `guardar_limite_cajera` / `guardar_comision` / liquidaciones → `assert_usuario_en_alcance` / sucursal

### Riesgo residual (bajo / catalogación)

| Tema | Notas |
|------|-------|
| Límites globales `LimiteVenta` / sorteos / tabla de pagos | Catálogo de consorcio (compartido a propósito) |
| Resultados oficiales | Compartidos (lotería) |
| Auditoría | Admin aislado ve eventos de usuarios de su sucursal; no es mirror 1:1 de tickets ajenos |
| Pago de ticket vendido en otra banca | Regla de negocio histórica de pago único; con aislamiento el admin solo opera su `sucursal_id` de pago |
| Árbol `android-app/` local | `versionName 0.1.0` ≠ APK instalada 0.3.34; no usar ese árbol como fuente de verdad del binario |

---

## 6. Integridad histórica

- No hay migraciones destructivas en este paquete.
- Cajeros existentes → `aprobado` (FASE 1/2).
- Tickets / ventas / premios / cajas / fondos / entregas / movimientos: **sin rewrite**.
- Al activar: comparar fingerprints (`fp_tickets`, `fp_cajas`, etc.) vs snapshot pre-cambio.

---

## 7. Desactivar `COMPAT_GLOBAL_FORZADO`

Procedimiento completo: `docs/respaldos/PROCEDIMIENTO_DESACTIVAR_COMPAT_Y_REVERSION.md`.

Resumen: flag=1 → crear JDMCASHNOW → verificar login → confirmar `sucursal_id` de admins → quitar flag → verificar 403 cruzados → fingerprints.

---

## 8. Ningún admin global tras activación

Condición: existe `super_admin` activo **y** `COMPAT_GLOBAL_FORZADO` apagado → `compat_global=false` para todos los `admin`. Solo JDMCASHNOW tiene alcance total.

---

## 9. Reversión

1. Restaurar `COMPAT_GLOBAL_FORZADO=1` (inmediato).  
2. No borrar datos; corregir claves/`sucursal_id`.  
3. Redeploy commit anterior solo si el código falla.  
4. APK sin tocar.

---

## Pruebas locales (esta auditoría)

```text
pytest tests/test_auditoria_final_aislamiento.py + fase2/fase3
→ 14 passed

pytest tests
→ 320 passed
```

---

## Riesgos antes de autorizar publish

| # | Riesgo | Mitigación |
|---|--------|------------|
| 1 | Crear JDMCASHNOW sin flag → aislamiento inmediato | Usar `COMPAT_GLOBAL_FORZADO=1` primero |
| 2 | Admin sin `sucursal_id` queda ciego | Verificar Alfredo=`1` y demás admins antes de quitar flag |
| 3 | Secret de clave mal configurado | Probar login antes de quitar compat |
| 4 | Commit/publish incompleto | Publicar backend completo (FASE 3 + parches de alcance) en un solo deploy |

---

## Solicitud de autorización (pendiente de usted)

Cuando autorice, el orden será: respaldo LIVE → migrate aditiva si falta → env COMPAT → crear JDMCASHNOW → login OK → quitar COMPAT → compare fingerprints.  
**Sin APK nueva. Sin promover a Alfredo.**
