# Runbook — VER CONTRASEÑA (respaldo y publicación)

**Estado:** código listo en local. **No aplicar en producción** hasta autorización expresa.

Mismo servicio Render y misma PostgreSQL. APK sin cambios.

## Migración aditiva (automática al arrancar la API)

```sql
ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS clave_consulta_cifrada TEXT;
-- Rollback opcional:
-- ALTER TABLE usuarios DROP COLUMN clave_consulta_cifrada;
```

- No toca `clave_hash`, IDs, tickets, ventas, cajas ni historial.
- Filas existentes: `NULL` → “Contraseña aún no disponible” hasta login/cambio.
- Captura post-login: `UPDATE … SET clave_consulta_cifrada WHERE id=? AND clave_hash=?` (anti-carrera).
- Rate-limit de reauth: filas en `auditoria` (`ver_clave_fallo_reauth` / `ver_clave_reauth_ok`), multi-proceso.

## Secreto AES (fuera de PostgreSQL y del repo)

```text
CLAVE_CONSULTA_USUARIOS=<32 bytes en base64>
```

```bash
python -c "import base64,secrets; print(base64.b64encode(secrets.token_bytes(32)).decode())"
```

Sin la variable: login y ventas siguen; solo no se puede consultar.

## Procedimiento de publicación (cuando se autorice)

Detalle completo: `docs/INFORME_PREPARACION_PUBLICACION_VER_CLAVE.md`

1. **Respaldo:** ya preparado con `_backup_pre_publish_ver_clave.py` → ver `backup_verify_ver_clave_*.json`.
2. **Secret:** pegar en Render Environment del **mismo** web service el valor de  
   `%USERPROFILE%\.cursor\secrets\banca_moderna_CLAVE_CONSULTA_USUARIOS.txt`  
   (no commitear; no pegar en chat).
3. **Dependencia:** `cryptography` ya está en `requirements.txt`.
4. **Deploy:** publicar API + web al servicio actual (sin tocar APK).
5. **Post-check:** `GET /health`; login panel; humo de venta SUNMI; VER CONTRASEÑA en operador de prueba; 403 entre bancas.
6. **No** migrar a otra BD ni actualizar APK.

## Recuperación sin borrar datos

| Problema | Acción |
|---|---|
| Rollback de feature | Redeploy commit anterior; opcional `DROP COLUMN clave_consulta_cifrada` |
| Perder env AES | Consultas fallan; **logins PBKDF2 intactos** |
| Restaurar BD | Restaurar el `pg_dump`; no recrear usuarios |

## No hacer

- No rotar `clave_hash` masivamente ni forzar cambio de contraseñas.
- No guardar `CLAVE_CONSULTA_USUARIOS` en el repositorio.
- No modificar PostgreSQL a mano salvo el ADD COLUMN (ya lo hace el arranque) o el DROP de rollback.
