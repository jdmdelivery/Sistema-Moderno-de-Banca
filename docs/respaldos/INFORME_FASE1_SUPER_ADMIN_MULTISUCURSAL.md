# FASE 1 — Auditoría y diseño: Super Admin multisucursal

**Fecha:** 2026-11-16  
**Alcance:** solo diseño + respaldo + prueba de migración en BD **aislada**.  
**Prohibido cumplido:** sin commit, sin publish Render, sin modificar PostgreSQL LIVE.

Compatibilidad a preservar: SUNMI **0.3.34** + commit **`b2ef3cc`** (login multi-sucursal).

---

## 1. Auditoría del sistema actual

### 1.1 Roles hoy (`usuarios.rol`)

| Rol | Panel | Terminal SUNMI | Alcance real hoy |
|-----|-------|----------------|------------------|
| `admin` | Sí | Entra como admin móvil | **Global** (todas las sucursales) |
| `supervisor` | Sí | Sí | Casi global (sin algunas acciones admin) |
| `operador` | No | Sí | Su `sucursal_id` + su caja |

No existe `super_admin`. No hay tabla de permisos por sucursal. No hay estado “pendiente de aprobación”.

### 1.2 Controles de acceso observados

- Auth panel: `POST /auth/login` → roles `admin|supervisor`.
- Auth terminal: `POST /terminal/login` → `operador|supervisor` (+ admin móvil).
- Guardia típica: `requiere_rol("admin")` o `("admin","supervisor")`.
- **Brecha:** `GET /sucursales`, `GET /usuarios`, movimientos, terminales y varios reportes **no filtran por `usuario.sucursal_id`**. Un admin ve y opera el consorcio entero. Eso coincide con “admin de consorcio” actual, no con “admin de sucursal”.

### 1.3 Dinero y tickets (ya separados en datos)

Ya existen y **no se deben rehacer**:

- Tickets: `sucursal_vendedora_id`, `usuario_id`, estados, anulaciones con motivo.
- Cajas cajero: `saldo_caja`, `saldo_caja_prueba`, `movimientos_cajera`.
- Caja sucursal: `sucursales.saldo_actual`, `movimientos_saldo`.
- Fondos: `fondos_asignados`.
- Entregas: `entregas` (parciales reducen pendiente sin borrar ventas).
- Límites: `limites_cajera` / `limites_venta` por sucursal.
- Auditoría: `auditoria`.

Multisucursal SUNMI (`b2ef3cc`): reasigna terminal al login; **no** mueve `sucursal_vendedora_id` históricos.

### 1.4 Esquema / migraciones

No hay Alembic. El arranque usa `create_all` + `_columnas_faltantes()` en `apps/api/db.py` (ALTER aditivos idempotentes). El diseño nuevo sigue ese patrón + SQL versionado en `docs/respaldos/migraciones/`.

### 1.5 Snapshot LIVE (pre-diseño)

| Artefacto | Valor |
|-----------|--------|
| Dump | `banca_moderna_pre_multisucursal_20261116-223702.dump` |
| SHA256 | `1ef8ff5e9638fd604fd3987117da4efc850674084cdaa5cbe028f075d2864d56` |
| Restore verificado | `counts_match: true` |
| Inventario | `inventario_baseline_multisucursal_20261116-223702.json` |

Roles LIVE al snapshot: `admin` (Alfredo), operadores en CASTILLO/PEGUERO; 2 sucursales. **Ningún usuario convertido.**

---

## 2. Diseño de permisos propuesto

### 2.1 Nuevos roles (aditivos)

| Rol | Significado | Sucursal |
|-----|-------------|----------|
| `super_admin` | Consorcio completo | `sucursal_id` NULL |
| `admin` | Administrador **de una sucursal** | Obligatoria |
| `supervisor` | Se mantiene (opcional por sucursal) | Obligatoria |
| `operador` | Cajera SUNMI | Obligatoria |

**Regla de transición (crítica):**  
No convertir automáticamente a Alfredo ni a ningún `admin` actual.  
Hasta que exista al menos un `super_admin` **autorizado explícitamente**, el código puede:

- **Modo compat:** `admin` sin scoping estricto (comportamiento actual), **o**
- **Gate de publicación:** promover 1 cuenta a `super_admin` en el mismo deploy (solo con su OK).

Recomendación: **Gate** — no publicar el aislamiento estricto sin su autorización de promoción.

### 2.2 Matriz de capacidades

| Capacidad | Super Admin | Admin sucursal | Operador |
|-----------|:-----------:|:--------------:|:--------:|
| Crear/editar sucursales | Sí | No | No |
| Crear/administrar admins de sucursal | Sí | No | No |
| Crear cajeros | Sí (o vía admin) | Sí → **PENDIENTE** | No |
| Aprobar/rechazar cajeros | Sí | **No** | No |
| Activar / suspender / bloquear | Sí (todos) | Sí (solo su sucursal; no a sí mismo ni a super_admin) | No |
| Ver ventas/cajas/premios/fondos/entregas | Todas | Solo su sucursal | Solo lo de terminal actual |
| Configurar permisos por sucursal | Sí | No | No |
| Fondos / entregas / límites / anulaciones | Todas | Solo su sucursal (si permiso_sucursal lo permite) | Según reglas actuales SUNMI |
| Auditoría global | Sí | Solo su sucursal | No |

### 2.3 Aprobación de cajeros

Campos nuevos en `usuarios` (default seguro):

- `estado_aprobacion`: `aprobado` \| `pendiente` \| `rechazado`  
  → **DEFAULT `aprobado`** + UPDATE de saneo → usuarios actuales siguen entrando.
- `solicitado_por`, `solicitado_en`
- `aprobado_por`, `aprobado_en`
- `rechazado_por`, `rechazado_en`, `motivo_rechazo`
- `suspendido` (aparte de `activo`/bloqueo; opcional para “suspender” sin confundir con bloqueo)

Flujo:

1. Admin sucursal `POST /usuarios` con `rol=operador` → `estado_aprobacion=pendiente`, `activo` no habilita login.
2. Super Admin ve cola `GET /super/cajeros-pendientes`.
3. `POST .../aprobar` o `/rechazar` + auditoría.
4. `POST /terminal/login` y panel: rechazan si `pendiente`/`rechazado` (mensaje claro).

### 2.4 Aislamiento backend (obligatorio)

Helpers nuevos (código, no solo UI):

- `exige_super_admin`
- `exige_admin_sucursal` / `alcance_sucursal_ids(usuario)`
- `assert_mismo_sucursal(usuario, sucursal_id)` en **cada** GET/POST con id

Todo listado/filtrado: admin → `WHERE sucursal_id = yo.sucursal_id`.  
Manipular `?sucursal_id=` o IDs ajenos → **403**, no 200 vacío engañoso cuando sea escritura.

### 2.5 Panel UI (fases 3–4)

- **Super Admin:** dashboard consorcio + drill-down por sucursal + cola de aprobaciones + permisos + auditoría global.
- **Admin sucursal:** el panel actual **restringido** a su sucursal (reutilizar secciones Usuarios, Fondos, Entregas, Límites, Tickets, Reportes; no duplicar motores contables).

SUNMI 0.3.34: sin cambios obligatorios si el login sigue con el mismo contrato; solo mensajes nuevos de “pendiente de aprobación”.

### 2.6 Dinero / tickets

Sin tablas nuevas de “caja paralela”. Reutilizar indicadores existentes (`indicadores_caja`, entregas, fondos, reportes).  
Anulaciones: seguir reglas actuales; registrar siempre usuario/sucursal/motivo; no delete físico.

---

## 3. Migraciones estrictamente necesarias

Archivos preparados (aún **no** aplicados a LIVE):

| Archivo | Propósito |
|---------|-----------|
| `docs/respaldos/migraciones/_001_super_admin_aditiva.sql` | Columnas aprobación + `permisos_sucursal` + índice |
| `docs/respaldos/migraciones/_001_super_admin_revert.sql` | DROP solo objetos nuevos |
| `docs/respaldos/migraciones/_probar_001_en_aislada.py` | Restore aislado + apply + idempotencia + revert |

**No incluye:** cambio de roles de usuarios, reseteo de claves, renumeración de tickets, limpieza general.

### Prueba en BD aislada (ejecutada)

```text
ok: true
cajas_intactas: true
tickets_intactos: true
roles_intactos: true
claves_intactas: true
pendientes_tras_mig: 0
permisos_filas = sucursales: 2
idempotente: true
reversible: true
```

Fuente: dump `…223702.sql` restaurado en `banca_moderna_mig_superadmin_test` (luego eliminada).

También se reflejarán las columnas en `_columnas_faltantes()` / `models.py` en FASE 2 (código local), para que SQLite de tests y PG coincidan.

---

## 4. Riesgos

| Riesgo | Mitigación |
|--------|------------|
| Publicar aislamiento sin `super_admin` deja a Alfredo atrapado en una sola sucursal | Gate de promoción autorizado; o modo compat temporal |
| Cajeros nuevos quedan pendientes y “parece un bug” | UI clara + default `aprobado` solo para existentes |
| Admin sucursal intenta aprobar sus cajeros vía API | Endpoint solo `super_admin` |
| Fuga cross-sucursal por query params | `assert_mismo_sucursal` en servicios, tests de aislamiento |
| Romper SUNMI 0.3.34 | No cambiar contrato login; solo denegar pendientes |
| Migración mal aplicada en LIVE | Ya probada en aislada; publish solo con autorización + compare fingerprints |

---

## 5. Plan de pruebas (FASES 2–5)

1. **Aprobación:** crear cajero pendiente → login 401/403 → aprobar → login OK → rechazar → no login.  
2. **Aislamiento:** admin CASTILLO no lee/escribe IDs de PEGUERO (API directa).  
3. **Super:** ve ambas; aprueba; configura permisos; auditoría.  
4. **Contabilidad:** fondos/entregas/ajustes/anulaciones no duplican movimientos; fingerprints de cajas/tickets estables.  
5. **SUNMI:** dispositivo CASTILLO ↔ PEGUERO (`b2ef3cc`); cajero pendiente no entra.  
6. **Regresión:** `pytest` completo + suite nueva `test_super_admin_aislamiento.py`.

---

## 6. Plan de publicación (cuando autorice)

1. Respaldo LIVE fresco + snapshot fingerprints.  
2. Commit **solo** del paquete Super Admin (sin King WIP).  
3. Deploy Render.  
4. Aplicar `_001_super_admin_aditiva.sql` en LIVE (o vía `init_db` aditivo si se empaqueta ahí) — **solo con OK**.  
5. Promoción explícita del primer `super_admin` (comando/SQL autorizado).  
6. Compare pre/post: tickets, jugadas, cajas, fondos, entregas, roles, `clave_hash`.  
7. Sin reinstalar APK salvo que una fase futura lo exija (hoy: no).

---

## 7. Roadmap de implementación local (siguientes fases)

| Fase | Trabajo | Estado |
|------|---------|--------|
| **1** | Auditoría, respaldo, diseño, migración aislada, este informe | **Hecha** |
| **2** | Modelos + login/aprobación + tests (entorno local/SQLite) | Pendiente autorización para codificar |
| **3** | Panel Super Admin + restricción panel admin sucursal | Pendiente |
| **4** | Enlazar fondos/entregas/límites/ajustes/anulaciones con scoping | Pendiente |
| **5** | Suite aislamiento + contabilidad + SUNMI | Pendiente |

---

## 8. Decisiones que requieren su autorización antes de FASE 2/publish

1. **Promover a Alfredo a `super_admin` en go-live** — **SÍ** (conservar usuario/contraseña).  
2. **Admin actuales** — **COMPAT GLOBAL** temporal hasta activar y verificar Super Admin.  
3. **`supervisor`** — **LIMITAR A SUCURSAL** (solo su sucursal y cajeros).  
4. **FASE 2 código local** — **AUTORIZADA** (sin LIVE / sin Render / sin commit hasta nuevo OK).

---

**Conclusión FASE 1:** el sistema actual es un panel de consorcio con rol `admin` global. El Super Admin se introduce de forma **aditiva**, con aprobación de cajeros por defecto `aprobado` para no romper usuarios vigentes, aislamiento real en API, reutilización de la contabilidad existente y migración ya **verificada en copia aislada** sin tocar LIVE.
