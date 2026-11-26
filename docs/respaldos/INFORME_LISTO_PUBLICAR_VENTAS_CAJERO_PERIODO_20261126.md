# Listo para publicar — Ventas por Cajero (período)

**Estado:** corregido y verificado en local. **No publicado** (espera autorización nocturna).

## Alcance
- Solo panel admin BANCA MODERNA (`/reportes/ventas-cajeros` + UI).
- Mismo servicio Render y misma base PostgreSQL (sin nueva DB).
- Sin APK, sin cambios a MI CAJA / comisiones / lógica de cierre / registros históricos.

## Causa
El listado/detalle pisaba el filtro DESDE/HASTA con métricas del ciclo abierto.

## Archivos
- `apps/api/servicios.py`
- `apps/web/app.js`
- `tests/test_ventas_cajeros.py`
- `tests/test_cierre_ciclo_cajera.py`

## Publicar esta noche (cuando autorice)
1. `git push origin main` (commit de este arreglo).
2. Esperar deploy live en `srv-dbsfbem7bikc73feg280`.
3. Smoke: panel → Ventas por cajero → HOY / AYER / ESTA SEMANA / ESTE MES / DESDE-HASTA.
4. Verificar LEIDY (u otra cajera): HOY = solo ventas del día; ciclo sigue aparte en `ventas_ciclo`.
5. Tras un cierre de ciclo, consultar la fecha del cierre: ventas históricas visibles; `ventas_ciclo` del ciclo nuevo en 0.
