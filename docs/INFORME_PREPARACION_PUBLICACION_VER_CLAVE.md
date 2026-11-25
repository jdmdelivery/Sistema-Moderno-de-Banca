# Preparación de publicación — VER CONTRASEÑA

**Fecha de preparación:** 2026-11-25  
**Estado:** LISTO PARA AUTORIZACIÓN NOCTURNA — **aún no publicado**  
**Servicio:** mismo Render (`sistema-de-banca-moderna`)  
**BD:** misma PostgreSQL (`dpg-dbslergae00c738d56j0-a`)  
**APK:** sin cambios ni reinstalación

---

## Qué se publica (cuando autorices)

- API + panel web: campo cifrado opcional, endpoint `POST /usuarios/{id}/ver-clave`, botón **VER CONTRASEÑA**.
- Migración **solo aditiva** al arrancar:  
  `ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS clave_consulta_cifrada TEXT`
- Auth sigue en **PBKDF2 / `clave_hash`**. Usuarios, IDs, tickets, ventas, cajas: intactos.

---

## Checklist de esta noche (orden)

| # | Paso | Quién | ¿Hecho ahora? |
|---|---|---|---|
| 1 | Respaldo PG verificable (dump + restore lab) | Script local | **OK** `backup_verify_ver_clave_20261125-154038.json` (columna nueva aún = 0 en prod) |
| 2 | Generar `CLAVE_CONSULTA_USUARIOS` (32 bytes base64) **fuera del repo** | Ops | Archivo local de secreto (no en git/chat) |
| 3 | Pegar el secreto en Render → Environment del **mismo** web service | Tú / al autorizar | **NO hecho** (prohibido hasta tu OK) |
| 4 | Deploy del código (git push / Render deploy) | Al autorizar | **NO hecho** |
| 5 | Post-check: `/health`, login panel, una venta de prueba en terminal | Al autorizar | Pendiente |
| 6 | Confirmar aviso a operadores (panel USUARIOS + campo `aviso_consulta_clave` en login) | Ya en código | Listo en código local |

### Cómo configurar el secreto en Render (sin pegarlo aquí)

1. Abre el servicio web actual en el dashboard de Render.  
2. **Environment** → **Add Environment Variable**.  
3. Name: `CLAVE_CONSULTA_USUARIOS`  
4. Value: pegar el contenido del archivo de secreto local (una sola línea base64).  
5. Guardar. El deploy posterior debe ver la variable.  
6. **Nunca** commits, tickets ni chats con el valor.

Sin la variable: el sistema **sigue vendiendo**; solo no se pueden consultar claves.

---

## Migración (aditiva, reversible)

```sql
ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS clave_consulta_cifrada TEXT;
-- Rollback (solo si hace falta revertir el feature):
-- ALTER TABLE usuarios DROP COLUMN clave_consulta_cifrada;
```

No reescribe filas, no cambia `clave_hash`, no toca tickets/cajas.

---

## Recuperación sin borrar datos

| Fallo | Acción |
|---|---|
| Deploy malo / bug UI | Redeploy del commit anterior (misma BD) |
| Quitar feature de BD | `DROP COLUMN clave_consulta_cifrada` (opcional) |
| Perder env AES | Consultas fallan; **login y ventas OK** |
| Desastre de datos | Restaurar el `.dump` / `.sql` del respaldo pre-publish a lab primero; producción solo con decisión explícita |

Script de respaldo: `docs/respaldos/_backup_pre_publish_ver_clave.py`  
Runbook: `docs/RUNBOOK_VER_CLAVE_RESPALDO.md`

---

## Aviso a operadores (ya en código)

- Panel USUARIOS: texto de que, tras un acceso correcto, el administrador autorizado de su banca puede consultar la contraseña.  
- Login terminal: campo JSON `aviso_consulta_clave` (las APK actuales lo ignoran; no rompe el login).

---

## Pruebas hechas vs pendientes

**Hechas (local, no suite completa):** cifrado AES-GCM; aislamiento entre bancas (incl. COMPAT_GLOBAL); reauth; rate-limit vía `auditoria`; UPDATE condicionado por `clave_hash`; ID/tickets al editar operador; login sin clave maestra.

**Pendientes esta noche (post-deploy, breves):**

1. `GET /health` en producción.  
2. Login panel admin real.  
3. Una venta SUNMI de humo (APK sin actualizar).  
4. `VER CONTRASEÑA` sobre un operador de prueba / tras un login reciente.  
5. Confirmar que un admin de otra banca sigue recibiendo 403.

---

## Riesgos de seguridad (aceptados al publicar)

1. Quien tenga **env AES + dump PG** puede descifrar claves ya capturadas. Mitigar: secreto solo en Render; acceso restringido.  
2. Claves antiguas **no consultables** hasta próximo login o cambio.  
3. Rate-limit multi-proceso vía `auditoria` (OK entre workers).  
4. Captura reversible es un trade-off consciente frente a “solo hash”.

---

## Prohibido hasta tu autorización expresa

- Cambiar variables en Render  
- Ejecutar migración/deploy en producción  
- Reiniciar el servicio  
- Actualizar APK  
- Tocar ventas o usuarios existentes  

Cuando autorices esta noche, se ejecutan solo los pasos 3–5 del checklist.
