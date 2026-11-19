# Informe Fase 1 — Pre-publicación recibos PNG

**Fecha:** 2026-11-18  
**Estado:** **DETENIDO AL FINAL DE FASE 1 — NO PUBLICAR**  
**Motivo de freno:** regresión local **4 failed / 372 passed**.

---

## Veredicto Fase 1

| Control | Resultado |
|---|---|
| Commit / deploy LIVE Render | OK identificado |
| Respaldo PostgreSQL completo | **OK** |
| Recuperación verificada | **OK** (conteos idénticos; primaria intacta) |
| Migraciones (auditoría) | OK — solo aditiva `disenos_ticket` |
| Endpoints legacy en LIVE | OK presentes |
| Endpoints PNG en LIVE | Ausentes (esperado hasta Fase 2) |
| `MODO_DESARROLLO` | `true` — **no modificado** |
| Pruebas de regresión | **FALLÓ (4)** → **no continuar a publicar** |

---

## 1. Commit y despliegue LIVE

| Campo | Valor |
|---|---|
| Servicio | `srv-dbsfbem7bikc73feg280` |
| URL | https://sistema-de-banca-moderna.onrender.com |
| Deploy LIVE | `dep-dburiqui0phs73bf43v0` |
| Estado | `live` |
| Commit | `d4c1f9ba1559cff60eb6aab4ff81b58335f41c5d` |
| Mensaje | `fix: diseno elite de lista y detalle de cajeros con VOLVER.` |
| Finished | 2026-11-18T14:43:44Z |
| `origin/main` local | mismo commit `d4c1f9b` |

**Código de recibos PNG:** está en el working tree local (**sin commit / sin push**):  
`ticket_imagen.py`, `recibos_imagen.py`, `impresion_servidor.py`, cambios en `main.py` / `servicios.py` / `models.py` (`DisenoTicket`), etc.

---

## 2. Respaldo PostgreSQL y recuperación

| Artefacto | Valor |
|---|---|
| Dump custom | `docs/respaldos/banca_moderna_pre_publish_recibos_20261118-213529.dump` |
| SQL plain | `docs/respaldos/banca_moderna_pre_publish_recibos_20261118-213529.sql` |
| Meta | `docs/respaldos/backup_verify_recibos_20261118-213529.json` |
| SHA-256 dump | `31395a7abbd20ee3f7af40fc6cc6b062e2c29c4dea37b1bafec806f2c5bd86de` |
| Tamaño dump | 188 827 bytes |
| Restore method | `psql_plain_sql` en BD temporal `banca_moderna_restore_recibos_ok` |
| Conteos dump = restore | **Sí** |
| Primaria intacta tras prueba | **Sí** |
| Temp DB eliminada | **Sí** |

### Conteos LIVE (muestra)

- tickets **77**, jugadas **676**, usuarios **24**, sucursales **3**, terminales **11**
- auditoria **1270**, resultados **172**, siguiente_ticket **114**
- suma_caja real **0.00**, suma_caja_prueba **12725.00**, saldo sucursales **0.00**

---

## 3. Migraciones necesarias (sin borrar datos)

| Cambio | Tipo | Estado en LIVE |
|---|---|---|
| Tabla `disenos_ticket` | **CREATE aditivo** (vacía) | **No existe** |
| Columnas pago en `jugadas` | Ya presentes | OK |
| `tickets.serial` | Ya presente | OK |
| DROP / TRUNCATE / reinicio | **Ninguno** | N/A |

Al publicar (Fase 2, solo con autorización): `create_all` / ensure creará `disenos_ticket` sin tocar ventas, premios ni saldos.

---

## 4. Compatibilidad de endpoints

### Legacy en LIVE (OpenAPI) — presentes

`/terminal/login`, `/terminal/venta`, `/terminal/tickets/consultar|pagar|reimprimir`, `/terminal/entregas`, `/terminal/entregas/{id}`, `/terminal/reportes/dia`, …

### PNG nuevos — **no** están en LIVE todavía

- `/terminal/tickets/{ticket_id}/imagen`
- `/terminal/tickets/{ticket_id}/pago/imagen`
- `/terminal/entregas/{entrega_id}/imagen`
- `/terminal/reportes/dia/imagen`

Diseño de despliegue: **aditivos**; APK antiguas siguen con `texto` / `comprobante`.

---

## 5. MODO_DESARROLLO

| Origen | Valor | Acción Fase 1 |
|---|---|---|
| Env Render | **`true`** | **No modificado** |
| `/health` LIVE | `modo_desarrollo: true`, `datos: "prueba"` | Solo lectura |

**Riesgo pendiente:** producción con `MODO_DESARROLLO=true` mezcla semántica de prueba. Cualquier cambio debe ser decisión explícita suya (no automática).

---

## 6. Regresión local

Log: `docs/respaldos/fase1_pytest_recibos_20261118.log`  
**372 passed, 4 failed** (≈9m 55s)

| Test fallido | Causa aparente |
|---|---|
| `test_resumen_periodo` (2) | Endpoint fuerza `alcance=cajero` → 200; test espera 403 |
| `test_semilla_prueba` | Semilla local `BANCA CASTILLO` vs esperado `BANCA CASTILLO (PRUEBA)` |
| `test_ventas_cajeros` | 403 `ESTE TICKET PERTENECE A OTRA CAJERA` (aislamiento de cajera) |

Por la regla **“Si algo falla, detener”**: **no se inicia Fase 2**.

---

## 7. Riesgos / pendientes antes de autorizar publicar

1. **Corregir o dispensar** los 4 tests fallidos.  
2. **Commit** del paquete recibos PNG (aún no está en `origin/main`).  
3. Decidir qué hacer con **`MODO_DESARROLLO=true`** en Render.  
4. Tras deploy: crear `disenos_ticket` aditivo; verificar OpenAPI PNG; smoke con auth de prueba (sin pagos/entregas reales).  
5. Luego, con autorización aparte: instalar APK **0.4.2** solo en SUNMI piloto.

---

## Archivos de evidencia Fase 1

- `fase1_pre_publish_recibos_20261118-213529.json`
- `backup_verify_recibos_20261118-213529.json`
- `banca_moderna_pre_publish_recibos_20261118-213529.dump` / `.sql`
- `fase1_pytest_recibos_20261118.log`

---

## Siguiente paso

**Esperando su autorización.**  
No se publicó Render. No hay push. No hay instalación en banqueras. PostgreSQL de producción no se modificó (solo dump + restore en BD temporal).
