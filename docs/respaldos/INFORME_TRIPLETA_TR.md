# Informe final TR — Tripleta 0.3.32 (correcciones)

Fecha: 2026-11-16  
APK: **0.3.32** (versionCode 37) — **no instalada**  
Push / Render / LIVE: **no ejecutados**

## 1. Fallos de pruebas (10) — resueltos

Causa: expectativas antiguas del veredicto de tickets pagados.

- Comportamiento vigente (correcto): `ESTE TICKET YA SE PAGÓ`
- No se cambió la lógica de pagos

Archivos de test actualizados:

- `tests/test_auditoria_publicacion.py` (2)
- `tests/test_ganadores_prueba.py` (1)
- `tests/test_resultados_auto.py` (1)

Los otros fallos del lote anterior eran el unpack `n1,n2,n3` en `/limites` (ya corregido en la entrega TR).

**Suite completa:** `280 passed` (exit 0).

## 2. Premios repetidos en resultados

La validación `Los tres premios deben ser números diferentes` era **incorrecta**.

En quinielas dominicanas cada posición sale de una tómbola independiente (00–99); un mismo número puede repetirse (~3 % de sorteos). Fuentes: reglas La Primera / Loteka y registros oficiales (p. ej. Nacional 89-89-00).

**Corrección:** eliminada la restricción en `servicios.py` (guardar resultado). Solo se valida rango 00–99.

TR compara con `Counter` (multiset). Pruebas añadidas/actualizadas:

- resultado `19-19-45` aceptado
- TR gana `12-12-38` / pierde `12-38-38`
- TR `00-00-25` y `25-25-25`
- QN con resultado `25-25-25` sigue cobrando solo 1ro ×60 (sin cambio de reglas QN)

## 3. Migración PostgreSQL (aislada)

Script: `docs/respaldos/migracion_tripleta_tr.sql`  
Validador: `docs/respaldos/_validar_migracion_tr_aislada.py`  
Cluster temporal: `127.0.0.1:55433` (apagado tras la prueba)

Resultado:

- Columna `n3` agregada; histórico con `n3 = NULL`
- Tipo TR + factor ×500 insertados
- Tickets / jugadas / premios / movimientos históricos **intactos**
- Script **idempotente**
- **LIVE no tocado**

## 4. Regresión QN / PL / SP y TR

- Motor QN/PL/SP: suite completa en verde (multiplicadores sin cambio)
- TR: venta, liquidación, permutaciones, multiset, ceros, pagos parciales/doble cobro, impresión unitaria Android
- APK 0.3.32 ya construida localmente; **sin instalar**

## 5. Restricciones cumplidas

- Sin push a GitHub
- Sin publicar Render
- Sin instalar APK
- Sin modificar PostgreSQL LIVE

## Pendiente de autorización

Publicar backend + migrar LIVE + instalar APK 0.3.32 **solo con autorización expresa**.
