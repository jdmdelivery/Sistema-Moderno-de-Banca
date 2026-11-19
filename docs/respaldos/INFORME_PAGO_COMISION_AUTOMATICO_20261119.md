# INFORME — Sistema automático de pago de comisiones (local)

**Fecha:** 19 de noviembre de 2026  
**Ámbito:** solo local. **Sin Render, sin PostgreSQL de producción, sin APK/SUNMI.**  
**Estado:** listo para revisión. **No publicado.**

---

## Objetivo

Que cada cajera acumule comisión automáticamente por ventas válidas y que el administrador registre pagos (total o parcial) hasta que la **COMISIÓN PENDIENTE** vuelva a `RD$0.00`, sin tocar MI CAJA ni el Banco General.

---

## Diseño

| Pieza | Comportamiento |
|-------|----------------|
| Acumulación | Calculada al vuelo desde tickets **no anulados**, con el `%` vigente en `vendido_en` (mismo motor `_porcentaje_vigente` / `_comision_tickets`) |
| Pagos | Tabla nueva `pagos_comision` (historial independiente; no se borran filas) |
| Pendiente | `max(0, acumulada − suma(pagos))` |
| Cajas | Verificación explícita: pagar **no** cambia `saldo_caja` ni `saldo_actual` |
| Idempotencia | `operacion_id` único + bloqueo `FOR UPDATE` + rechazo si la suma supera lo ganado |
| Liquidaciones quincena | Se conservan intactas (`liquidaciones_comision`); el perfil usa el ledger de pagos |

No se escribe un asiento por cada venta: acumular desde tickets evita doble contabilidad y respeta anulaciones automáticamente.

---

## Migración (reversible)

Archivo: `docs/respaldos/MIGRACION_PAGOS_COMISION_20261119.sql`

- **Aplicar:** `CREATE TABLE IF NOT EXISTS pagos_comision (...)` + índices  
- **Revertir:** `DROP TABLE IF EXISTS pagos_comision;`  
- En local/tests: `create_all` crea la tabla al arrancar

---

## API nueva

| Método | Ruta | Uso |
|--------|------|-----|
| `GET` | `/comisiones/pagos` | Historial (filtro sucursal/cajera) |
| `POST` | `/comisiones/pagos` | Pago total/parcial (`usuario_id`, `monto`, `operacion_id`) |
| `GET` | `/comisiones/auditoria-sin-porcentaje` | Ventas válidas sin % registrado al vender |

`GET /reportes/ventas-cajeros/{id}` ahora incluye en `comision`:

- `comision_acumulada`, `comision_pagada`, `comision_pendiente`
- `comision_periodo` (filtro de fechas del perfil)
- `historial_pagos`

---

## UI (perfil VENTAS POR CAJERO)

Panel **COMISIÓN GANADA**:

1. Porcentaje vigente  
2. Comisión acumulada  
3. Comisión pagada  
4. **COMISIÓN PENDIENTE** (destacada)  
5. Botón **PAGAR COMISIÓN** (prompt monto + confirmación)  
6. Historial de pagos  

Cache-bust local (no desplegado): `?v=perfil-comision-pago-1` · SW `banca-admin-shell-v7-perfil-comision-pago`

---

## Auditoría de ventas sin porcentaje

- Endpoint de solo lectura: `/comisiones/auditoria-sin-porcentaje`
- **No** aplica el 15% actual a ventas anteriores
- **No** hay ajuste retroactivo automático (`ajuste_automatico: false`)
- En producción, ejecutar este endpoint tras autorizar el deploy y revisar el informe antes de cualquier corrección manual

---

## Pruebas

```text
pytest tests/test_pagos_comision.py tests/test_ventas_cajeros.py tests/test_comisiones.py tests/test_panel_iphone.py -q
18 passed
```

Cubierto en `test_pagos_comision.py`:

- Acumulación por venta y anulación  
- Pago parcial y total → pendiente `0.00`  
- Nueva venta después del pago  
- Cambio de porcentaje (historial respetado)  
- Doble clic / misma `operacion_id` (idempotente)  
- Segundo pago que supera pendiente (400)  
- Carrera concurrente (no deja pagado > acumulado)  
- Aislamiento entre sucursales (admin de otra banca → 403)  
- Historial tras nueva sesión de BD  
- MI CAJA / Banco General intactos al pagar  

UI/CSS strings: `COMISIÓN PENDIENTE`, `PAGAR COMISIÓN`, `.vc-comision-pendiente`.

Compatibilidad móvil: mismos grids 2 columnas del perfil; vista previa a 420px.

---

## Capturas (local)

Carpeta: `docs/respaldos/capturas_pago_comision_20261119/`

| Archivo | Contenido |
|---------|-----------|
| `_preview_pago_comision_perfil.html` | Vista previa del panel |
| `pago_comision_perfil_completo.png` | Perfil escritorio |
| `pago_comision_perfil_movil.png` | Perfil móvil |

---

## Qué no se tocó

- PostgreSQL de producción / Render  
- Cálculos de ventas, premios, entregas, MI CAJA, Banco General  
- APK / SUNMI  
- Ajustes retroactivos de comisión  

---

## Archivos tocados (local)

- `apps/api/models.py` — modelo `PagoComision`  
- `apps/api/servicios.py` — saldo, pago, auditoría  
- `apps/api/main.py` — rutas  
- `apps/web/app.js` / `style.css` / `index.html` / `sw.js`  
- `tests/test_pagos_comision.py` (nuevo)  
- `tests/test_ventas_cajeros.py`, `tests/test_panel_iphone.py`  
- `docs/respaldos/MIGRACION_PAGOS_COMISION_20261119.sql`  

---

## Publicación

**No publicada.** Pendiente de su autorización explícita para:

1. Aplicar la migración en PostgreSQL de producción  
2. Desplegar el commit en Render  
3. Ejecutar auditoría de ventas sin % y decidir (aparte) si hay correcciones  
