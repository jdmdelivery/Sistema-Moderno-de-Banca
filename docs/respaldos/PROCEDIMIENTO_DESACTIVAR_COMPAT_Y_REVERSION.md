# Procedimiento: desactivar COMPAT_GLOBAL_FORZADO + reversión

**No ejecutar en LIVE hasta autorización explícita.**

## A. Activación segura (orden obligatorio)

1. **Respaldo LIVE** completo + restore de verificación en BD aislada.
2. Migración aditiva (si falta) en LIVE — columnas `estado_aprobacion`, `permisos_sucursal`, etc.
3. En Render: `COMPAT_GLOBAL_FORZADO=1` (secret/env).
4. Crear JDMCASHNOW con script + secret `JDMCASHNOW_CLAVE` (nunca en git):
   ```text
   --live --confirm SI-AUTORIZO-LIVE
   ```
5. **Verificar login panel** de JDMCASHNOW (rol `super_admin`, menú Super Admin).
6. Confirmar que Alfredo (`admin`) entra con su clave habitual y `rol=admin`.
7. Confirmar `sucursal_id` de cada admin de banca (Alfredo → CASTILLO=`1` en snapshot).
8. Quitar `COMPAT_GLOBAL_FORZADO` en Render (o `=0`) y redeploy/restart.
9. Login de nuevo:
   - JDMCASHNOW: `compat_global=false`, ve todas las sucursales.
   - Admin CASTILLO: solo CASTILLO; 403 a PEGUERO.
   - Admin PEGUERO: solo PEGUERO.
10. Cajeros ya `aprobado` siguen entrando en SUNMI 0.3.34 sin reinstalar.
11. Comparar fingerprints de tickets/cajas/saldos vs respaldo pre-cambio.

## B. Checklist «ningún admin global»

Tras el paso 8–9:

| Cuenta | Esperado |
|--------|----------|
| JDMCASHNOW | `super_admin`, alcance total |
| Alfredo / admins de banca | `admin`, `compat_global=false`, solo su `sucursal_id` |
| Supervisores | solo su sucursal (siempre) |
| Variable `COMPAT_GLOBAL_FORZADO` | ausente o no truthy |

Comprobar: `GET /auth/yo` y `GET /sucursales` por cada admin.

## C. Reversión

### C1 — Falla el login de JDMCASHNOW

1. Mantener o restaurar `COMPAT_GLOBAL_FORZADO=1` (admins globales de nuevo).
2. No borrar usuarios ni tickets.
3. Revisar clave (secret) / `activo` / `estado_aprobacion=aprobado` / `rol=super_admin`.
4. Reset de clave solo con script `--reset-clave` en entorno autorizado.
5. Alfredo y cajeros no se tocan.

### C2 — Falla el aislamiento (alguien queda sin sucursal / bloqueado)

1. **Inmediato:** `COMPAT_GLOBAL_FORZADO=1` + restart → vuelve alcance histórico.
2. Corregir `sucursal_id` de admins afectados.
3. Reintentar desactivación del flag.
4. Si hace falta: desactivar temporalmente la cuenta JDMCASHNOW (`activo=false`) **solo** si también se fuerza compat; si no hay super activo, compat vuelve solo.

### C3 — Rollback de código

1. Redeploy del commit anterior en Render.
2. Restaurar BD **solo** si hubo corrupción (no esperado: cambios son aditivos). Preferir flag de compat antes que restore.
3. APK 0.3.34 no se reinstala ni se modifica en ningún escenario de esta activación.

## D. Qué no hacer

- No poner la clave de JDMCASHNOW en el código.
- No promover a Alfredo a `super_admin`.
- No borrar tickets, ventas, premios, cajas, fondos, entregas ni movimientos.
- No migrar destructiva ni `TRUNCATE`.
- No publicar hasta firma del informe de auditoría.
