# FASE 2 — Roles, aprobación de cajeros y aislamiento (local)

**Fecha:** 2026-11-16  
**Autorización:** decisiones confirmadas + FASE 2 en código local / BD de pruebas.  
**Cumplido:** sin PostgreSQL LIVE, sin Render, sin commit, sin borrar/reiniciar datos.

---

## 1. Decisiones aplicadas

| # | Decisión | Implementación |
|---|----------|----------------|
| 1 | Super Admin en go-live = **JDMCASHNOW** (cuenta nueva; Alfredo permanece admin) | Actualizado en FASE 3; **no** aplicado en LIVE |
| 2 | Compat global temporal | `permisos.compat_global_activo()` = no hay `super_admin` activo → `admin` ve todo |
| 3 | Supervisor limitado a sucursal | `alcance_sucursal_ids` siempre filtra por `sucursal_id` del supervisor |
| 4 | FASE 2 local | Código + tests en SQLite de pytest |

---

## 2. Cambios de código (locales, sin commit)

| Archivo | Qué |
|---------|-----|
| `apps/api/permisos.py` | **Nuevo** — roles, alcance, aprobación, asserts |
| `apps/api/models.py` | Campos aprobación + `PermisoSucursal` |
| `apps/api/db.py` | Columnas aditivas idempotentes + seed permisos |
| `apps/api/main.py` | Login, usuarios, sucursales, terminales, reportes + API `/super/*` |
| `apps/api/servicios.py` | Bloquear/desbloquear/eliminar con alcance |
| `apps/api/seed.py` | Admin semilla con `estado_aprobacion=aprobado` |
| `apps/api/comun.py` | Mensaje pendiente (referencia) |
| `tests/test_super_admin_fase2.py` | **Nuevo** — compat, aprobación, rechazo, aislamiento, supervisor |
| `docs/respaldos/migraciones/_001_*.sql` | Ya preparados en FASE 1 (solo aislada) |

### API nueva (solo Super Admin)

- `GET /super/cajeros-pendientes`
- `POST /super/cajeros/{id}/aprobar`
- `POST /super/cajeros/{id}/rechazar`
- `GET/PUT /super/permisos-sucursal/{sucursal_id}`

### Comportamiento clave

- **Sin Super Admin:** cajeros creados por `admin` nacen `aprobado` (compat / tests).
- **Con Super Admin:** cajeros creados por admin de sucursal → `pendiente` → no login SUNMI/panel hasta aprobar.
- Super Admin puede crear cajeros ya aprobados.
- Admin de sucursal **no** aprueba ni toca cuentas `super_admin`.
- Crear/editar sucursales: Super Admin; en compat, el `admin` global histórico sigue pudiendo.

---

## 3. Protección de datos

- No se tocó LIVE.
- Usuarios existentes: default/`UPDATE` a `aprobado` en migración aditiva.
- No se cambian contraseñas, saldos, tickets ni dueños.
- Multisucursal SUNMI `b2ef3cc` intacto.

---

## 4. Pruebas

```text
pytest tests → 311 passed
```

Incluye `test_super_admin_fase2.py` (compat, pendiente→aprobar/rechazar, aislamiento, supervisor, no tocar Super Admin) y toda la regresión previa (dispositivo multi-sucursal, cajas, fondos, etc.).

---

## 5. Pendiente FASE 3–5 (no hecho)

- Panel web Super Admin (cola, drill-down, permisos UI).
- Restricción visual del panel admin de sucursal.
- Scoping fino de fondos/entregas/límites/anulaciones restantes.
- Go-live: commit + migración LIVE + crear JDMCASHNOW + compare fingerprints (ver INFORME_FASE3).

---

## 6. Go-live (cuando autorice)

1. Respaldo LIVE + snapshot.  
2. Commit solo del paquete Super Admin.  
3. Deploy Render.  
4. Aplicar `_001_super_admin_aditiva.sql` (o columnas vía `init_db`).  
5. `UPDATE usuarios SET rol='super_admin', sucursal_id=NULL WHERE usuario='admin';` **solo con OK** (conserva hash).  
6. Verificar compat_global=false y aislamiento.  
7. Compare conteos/saldos/claves.

**No publicar hasta nuevo informe + autorización.**
