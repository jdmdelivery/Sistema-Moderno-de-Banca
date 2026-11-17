# Informe final — Publish JDMCASHNOW Super Admin

**Fecha:** 2026-11-16 / 2026-11-17 UTC  
**Autorización:** commit + migraciones aditivas + deploy Render controlado. Sin APK. Sin borrado/reinicio de datos.

---

## 1. Resultado

| Ítem | Valor |
|------|--------|
| Commit principal | `d782553` — *feat: JDMCASHNOW Super Admin…* |
| Hotfix | `63799ef` — *fix: sembrar permisos_sucursal con defaults TRUE* |
| Deploy LIVE | `dep-dbtt0ldbedkc73eoaptg` (código) + redeploy `dep-dbtt3i942hec73aubd3g` (sin COMPAT) |
| Servicio | `srv-dbsfbem7bikc73feg280` / https://sistema-de-banca-moderna.onrender.com |
| Health | `ok: true` · base `postgresql` |
| `COMPAT_GLOBAL_FORZADO` | **Ausente** (desactivado; aislamiento activo) |
| APK | **No** modificada / **No** reinstalada (0.3.34) |
| Alfredo | `admin` / `rol=admin` / `sucursal_id=1` / **hash de clave intacto** |
| JDMCASHNOW | `super_admin` / `aprobado` / login OK |

---

## 2. Respaldo pre-publish

| Campo | Valor |
|-------|--------|
| Dump | `banca_moderna_pre_jdmcashnow_20261116-234428.dump` |
| SHA256 | `3b0b545dd3de8a88bddbdebfd7d7eb82662248b5798e13a4ee91d4ab7b0cbd4b` |
| Bytes | 136850 |
| Restore verificado | **OK** (`counts_match: true`) |
| Meta | `backup_verify_jdmcashnow_20261116-234428.json` |
| Inventario | `inventario_baseline_jdmcashnow_20261116-234428.json` |
| Snapshot pre | `snapshot_pre_deploy_jdmcashnow_20261116-234428.json` |

### Baseline (pre)

| Métrica | Valor |
|---------|--------|
| tickets | 16 |
| jugadas | 140 |
| movimientos_cajera | 16 |
| fondos / entregas | 0 / 0 |
| ventas no anuladas | 4230.00 |
| premio pendiente | 4100.00 (3 ganadores) |
| CASTILLO / PEGUERO saldo | 0.00 / 0.00 |
| Alfredo | admin · sucursal **1** · caja 0 / 0 |
| 0000 | CASTILLO · activo |
| 12345 (LA MAQUINA) | PEGUERO · caja prueba 4230.00 |

---

## 3. Qué se publicó

- Rol `super_admin`, cuenta **JDMCASHNOW** (nueva; Alfredo no promovido)
- Aprobación de cajeros + API `/super/*` + panel web Super Admin
- Aislamiento de admin/supervisor por `sucursal_id` (API + UI)
- Migración aditiva `_001_super_admin_aditiva.sql` (columnas + `permisos_sucursal`)
- Hotfix de defaults TRUE en siembra de permisos

**No** se tocaron tickets, ventas, premios, saldos históricos, fondos ni entregas previas.

---

## 4. Secuencia de activación

1. `COMPAT_GLOBAL_FORZADO=1` en Render (transición)  
2. Commit/push `d782553` → falló arranque por INSERT de permisos sin defaults  
3. Migración `_001` aplicada en LIVE + hotfix `63799ef` → **LIVE**  
4. Creación JDMCASHNOW (clave solo en secret/almacén local; no en git/informe)  
5. Login JDMCASHNOW OK con compat diferido  
6. Eliminación de `COMPAT_GLOBAL_FORZADO` + redeploy → aislamiento **activo**  
7. Verificación API CASTILLO ↛ PEGUERO (403) y viceversa  

Reversión: `docs/respaldos/PROCEDIMIENTO_REVERSION_JDMCASHNOW_LIVE.md`

---

## 5. Verificaciones post-deploy

| # | Comprobación | Resultado |
|---|--------------|-----------|
| 1 | Render LIVE / health | OK |
| 2 | Login JDMCASHNOW | OK (`super_admin`, `compat_global=false`) |
| 3 | JDMCASHNOW ve todas las sucursales | OK (CASTILLO + PEGUERO) |
| 4 | Alfredo hash/rol/sucursal intactos | OK (`admin\|admin\|1`) — **login con su clave: confirmar manualmente** (agente no dispone de la contraseña) |
| 5 | Admin solo su sucursal | OK (admins de verificación) |
| 6 | Accesos cruzados API | OK (403 movimientos/reportes/tickets/fondos/super) |
| 7 | Cajeros existentes | Cuentas intactas; login SUNMI no ejercitado aquí (sin claves; contrato API intacto) |
| 8 | APK 0.3.34 | Sin cambios; contrato `/terminal/login` preservado |
| 9 | Fingerprints tickets / movs / saldos sucursal | **Idénticos** (`compare_jdmcashnow_*.json`) |
| 10 | Nuevos cajeros requieren aprobación | OK (pendiente → 401 SUNMI → aprobar → 200) |
| 11 | Dispositivos revocados | Ninguna terminal inactiva en LIVE ahora; lógica `activa=false` intacta en código |

Cuentas temporales de verificación (`verif_castillo`, `verif_peguero`, `caj_pend_verif`) quedaron **bloqueadas** (no borradas).

---

## 6. Pruebas

```text
Local pre-publish: pytest tests → 320 passed
Post-hotfix foco: 9 passed (fase2 + auditoría)
LIVE: login/aislamiento/aprobación no destructivos OK
```

---

## 7. Credencial JDMCASHNOW

- Usuario: `JDMCASHNOW`
- Clave: **no** incluida en este informe ni en el repositorio  
- Almacén local del operador + variable Render `JDMCASHNOW_CLAVE` (recuperación)

---

## 8. Incidencias

1. **Deploy `d782553` falló** al sembrar `permisos_sucursal` sin DEFAULT → corregido con migración LIVE + `63799ef`. Servicio anterior siguió respondiendo health durante el fallo.  
2. **Restart no bastó** para quitar `COMPAT_GLOBAL_FORZADO` de la memoria del proceso → se eliminó la env var y se forzó redeploy.  
3. **Login Alfredo**: verificación estructural OK; falta confirmación humana con su contraseña habitual.  
4. **Login cajeros 0000/12345**: no probado (claves no disponibles al agente); cuentas y estados preservados.

---

## 9. Estado final

- Super Admin global: **solo JDMCASHNOW**  
- Admins de banca: aislados por sucursal  
- `COMPAT_GLOBAL_FORZADO`: **desactivado**  
- Datos históricos: **intactos** (fingerprints core OK)  
- APK 0.3.34: **sin tocar**  
