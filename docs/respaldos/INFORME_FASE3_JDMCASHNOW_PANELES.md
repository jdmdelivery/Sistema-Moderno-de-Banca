# FASE 3 — JDMCASHNOW Super Admin + paneles web (local)

**Fecha:** 2026-11-16  
**Autorización:** actualización previa a FASE 3 — JDMCASHNOW será el Super Admin principal.  
**Cumplido:** sin PostgreSQL LIVE, sin Render, sin commit, sin borrar historial.

---

## 1. Decisiones aplicadas

| # | Decisión | Estado |
|---|----------|--------|
| 1 | JDMCASHNOW = Super Admin principal (cuenta nueva) | Script + tests locales |
| 2 | NO promover a Alfredo | Alfredo permanece `admin`; clave y datos intactos |
| 3 | Cada sucursal con su admin limitado | UI + API scoping (tras aislamiento) |
| 4 | JDMCASHNOW ve todas las sucursales / aprueba cajeros | Panel Super + `/super/*` |
| 5 | Cajeros existentes intactos | Sin cambios de permisos históricos |
| 6 | Sin tocar tickets/ventas/premios/cajas/fondos/entregas | Solo UI + auth/roles aditivos |
| 7 | Clave JDMCASHNOW fuera del código | `JDMCASHNOW_CLAVE` / `--clave` en shell |
| 8 | Aislamiento diferido hasta login verificado | `COMPAT_GLOBAL_FORZADO=1` |

---

## 2. Artefactos nuevos / tocados

| Archivo | Qué |
|---------|-----|
| `docs/respaldos/_crear_jdmcashnow_super_admin.py` | Creación segura (BD aislada por defecto; LIVE exige confirmación) |
| `apps/api/permisos.py` | `compat_global_forzado()` / aislamiento diferido |
| `apps/api/main.py` | `GET /super/resumen` + `compat_global` en `/auth/yo` |
| `apps/web/index.html` | Sección Super Admin + notas de alcance |
| `apps/web/app.js` | Panel Super, visibilidad por rol, admin de sucursal restringido |
| `tests/test_super_admin_fase3.py` | Login JDMCASHNOW, Alfred intacto, resumen, diferido, script |
| `tests/test_super_admin_fase2.py` | Helper de laboratorio usa JDMCASHNOW (no promueve Alfredo) |

### Panel Super Admin (web)

- Cola de cajeros pendientes → APROBAR / RECHAZAR
- Tabla de sucursales (admins, cajeros OK, pendientes, saldo)
- Editor de permisos por sucursal (`/super/permisos-sucursal/{id}`)

### Panel admin de sucursal (web)

- Con aislamiento activo: no crea/edita sucursales nuevas
- Roles limitados a operador/supervisor
- Sucursal fijada a la suya al crear usuarios
- Aviso de que cajeros nuevos quedan pendientes de JDMCASHNOW
- Sin acceso al menú Super Admin

---

## 3. Creación segura de JDMCASHNOW (solo aislada por ahora)

```powershell
$env:JDMCASHNOW_CLAVE = "********"   # nunca en el repo
$env:COMPAT_GLOBAL_FORZADO = "1"     # opcional: diferir aislamiento
python docs/respaldos/_crear_jdmcashnow_super_admin.py --sqlite-tmp
# o --database-url "postgresql://...aislado..."
```

Secuencia recomendada:

1. Crear cuenta con `COMPAT_GLOBAL_FORZADO=1`
2. Verificar login panel de JDMCASHNOW
3. Quitar `COMPAT_GLOBAL_FORZADO` → aislamiento de admins
4. **LIVE:** no ejecutar hasta autorización explícita (`--live --confirm SI-AUTORIZO-LIVE`)

---

## 4. Protección de datos

- No se tocó PostgreSQL LIVE ni Render.
- No commit.
- Alfredo: rol/clave/datos sin cambios.
- Cajeros existentes siguen `aprobado` (migración FASE 1/2).
- Historial de tickets/ventas/cajas intacto.

---

## 5. Pruebas

Ejecutar en el repo:

```text
pytest tests/test_super_admin_fase2.py tests/test_super_admin_fase3.py -q
→ 10 passed

pytest tests -q
→ 316 passed
```

Cobertura FASE 3:

- Login JDMCASHNOW + Alfred intacto
- `COMPAT_GLOBAL_FORZADO` mantiene alcance global
- `/super/resumen` + aprobación desde Super
- Admin de sucursal no ve Super ni otras bancas
- Script de creación en SQLite aislado
- Script `--sqlite-tmp` verificado (dry-run + create) sin LIVE

---

## 6. Pendiente (no hecho en FASE 3)

- Crear JDMCASHNOW en LIVE / Render
- Quitar `COMPAT_GLOBAL_FORZADO` en producción tras login verificado
- Commit + publish
- Asignar `sucursal_id` a Alfredo (CASTILLO) si en LIVE aún está null, **antes** de quitar el flag de compat
- Scoping fino restante de fondos/entregas si algún endpoint aún hereda alcance amplio

---

## 7. Go-live (cuando autorice)

1. Respaldo LIVE + restore aislado  
2. Migración aditiva ya probada  
3. `COMPAT_GLOBAL_FORZADO=1` en Render  
4. Script crear JDMCASHNOW (clave por secret)  
5. Login manual JDMCASHNOW  
6. Asignar sucursal a cada admin de banca  
7. Quitar flag → aislamiento  
8. Compare fingerprints / saldos  
