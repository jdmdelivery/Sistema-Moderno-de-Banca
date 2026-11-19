# INFORME — Balance de comisión y reinicio automático del dashboard (local)

**Fecha:** 19 de noviembre de 2026  
**Ámbito:** solo local. **Sin Render / PostgreSQL producción / APK / SUNMI.**  
**Estado:** listo para revisión. **No publicado.**

---

## Cambios

### UI COMISIÓN GANADA (simplificada)

Visible solo:

1. **PORCENTAJE VIGENTE**  
2. **BALANCE DE COMISIÓN** (= pendiente del ciclo)  
3. **PAGAR COMISIÓN Y CERRAR CICLO**

Ocultos en el panel: Comisión acumulada, Comisión pagada, COMISIÓN PENDIENTE (etiqueta), botón de pago parcial.

### Tras cerrar el ciclo

1. Registra el pago administrativo (si hay balance > 0).  
2. Cierra el ciclo e inicia uno nuevo.  
3. Contadores del perfil → `RD$0.00` / tickets `0`.  
4. **`refrescarDashboardCajeroTrasCierre`**: refresca lista + detalle **sin recargar la página**.  
5. **MI CAJA** se mantiene en su saldo real (no se descuenta ni se fuerza a cero).

### Dashboard RESUMEN — sin tarjeta Comisión

- Ocultada solo la tarjeta `$… / Comisión` del Dashboard principal.  
- Siguen: Ventas, Tickets vendidos, Premios pagados, Premios pendientes, Neto.  
- Cálculo de comisión (API) y bloque COMISIÓN GANADA del perfil: sin cambios.  
- Grilla `.cards-inicio` con `auto-fit` (escritorio) y última tarjeta a ancho completo en móvil (5 ítems, sin hueco).

### Protección contable (sin cambios de regla)

- No toca Banco General, fondos, entregas, ventas/premios históricos.  
- Bloquea cierre si MI CAJA ≠ 0 o hay premios pendientes.  
- Idempotencia por `operacion_id`.

Cache-bust local (no desplegado): `?v=perfil-ciclo-balance-2` · SW `v10-perfil-ciclo-balance`.

---

## Pruebas

```text
pytest tests/test_cierre_ciclo_cajera.py tests/test_pagos_comision.py \
       tests/test_ventas_cajeros.py tests/test_comisiones.py tests/test_panel_iphone.py -q
21 passed
```

Incluye cierre completo, nuevas ventas, duplicados, premios/caja pendientes, aislamiento, UI de balance y ausencia de la tarjeta Comisión en `tarjetasInicio`.

---

## Capturas

`docs/respaldos/capturas_balance_comision_20261119/`

| Archivo | Contenido |
|---------|-----------|
| `antes_cierre_balance.png` | Balance $150 + botón de cierre |
| `despues_cierre_balance.png` | Contadores en $0.00 tras reinicio |

---

## Archivos tocados (local)

- `apps/web/app.js`  
- `apps/web/style.css`  
- `apps/web/index.html` / `sw.js`  
- `tests/test_ventas_cajeros.py` / `test_panel_iphone.py`  

---

## Publicación

**No publicada.** Pendiente de su autorización explícita para Render.
