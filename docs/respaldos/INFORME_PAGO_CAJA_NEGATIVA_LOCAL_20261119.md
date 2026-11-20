# INFORME — Pago de premios con MI CAJA negativa (LOCAL)

**Fecha:** 2026-11-19  
**Ámbito:** Solo local. **Sin publish Render. Sin PostgreSQL de producción. Sin cambios APK/SUNMI. Sin pagos reales.**

## Auditoría de métodos de pago

| Canal | Endpoint | Validación de saldo (antes → ahora) |
|---|---|---|
| Escáner / PAGAR TICKET (APK) | `POST /terminal/tickets/pagar` | Bloqueaba si MI CAJA &lt; premio (modo prueba) → **permite deuda contable** |
| Consulta previa | `POST /terminal/tickets/consultar` | Añade aviso `premio_excede_mi_caja` + `mi_caja_despues_si_paga` |
| Panel admin | `POST /panel/tickets/pagar` | Misma contabilidad; UI exige confirmación explícita |
| Varias loterías / parciales | `_cobrar_premios` (único) | Sin cambio de reserva atómica de jugadas |
| Reimpresión | `reimprimir_ticket` | Sigue sin mover caja |

**Conservado:** ganador válido, resultado confirmado, ticket anulado, otra cajera (403), anti-duplicado por `operacion_id` / update condicional, comisiones intactas.

**Banco General (modo real):** sigue exigiendo fondos suficientes en la sucursal. En modo prueba no se toca.

## Regla nueva

1. Premio válido se paga aunque MI CAJA &lt; premio.  
2. MI CAJA puede quedar negativa (deuda **contable**).  
3. **No** se crea ajuste automático.  
4. El administrador ajusta después desde **CONTROL DE CAJEROS** (máx. a RD$0, sin Banco General).  
5. Panel: diálogo de confirmación si el premio excede MI CAJA.  
6. APK instalada: sin cambios; usa su confirmación existente y el servidor permite el pago.

## Pruebas

PostgreSQL aislado local (`127.0.0.1:55432`) **no estaba disponible** en esta máquina. Se ejecutó el equivalente en SQLite temporal de conftest (mismo código de negocio).

```
tests/test_pago_caja_negativa.py
tests/test_ganadores_prueba.py::test_premio_mayor_que_mi_caja_paga_y_deja_deuda_sin_tocar_general
tests/test_pago.py
tests/test_control_cajeros.py
→ 17 passed (suite combinada) / 5 passed (núcleo deuda)
```

| Caso | Resultado |
|---|---|
| MI CAJA 2000 / premio 3000 → -1000 | PASS |
| Ajuste parcial + completo a 0 | PASS |
| Sin doble cobro / concurrente | PASS |
| Ticket anulado / otra cajera | PASS |
| Banco General sin movimiento en prueba | PASS |
| CONTROL DE CAJEROS muestra DEUDA | PASS |
| Confirmación opcional en servicio (`exigir_confirmacion_deuda`) | PASS |

## Capturas

`docs/respaldos/capturas_pago_caja_negativa_20261119/`

| Archivo | Contenido |
|---|---|
| `01_cajera_mi_caja_negativa.png` | MI CAJA -RD$1,000 tras pago |
| `02_control_cajeros_deuda.png` | Fila DEUDA + AJUSTAR |
| `03_ajuste_administrativo.png` | Modal ajuste a RD$0 |
| `04_flujo_completo.png` | Flujo completo |

## Archivos tocados

- `apps/api/servicios.py` — `_aviso_caja_negativa`, `_cobrar_premios`, `pagar_ticket`, `consultar_ticket`
- `apps/api/main.py` — `confirmar_caja_negativa` en `LlaveIn`
- `apps/web/app.js` — confirmación panel + MI CAJA en rojo en perfil
- `tests/test_pago_caja_negativa.py` (nuevo)
- `tests/test_ganadores_prueba.py` (actualizado)
- Previews/capturas/informe en `docs/respaldos/`

## Confirmación

| Recurso | Estado |
|---|---|
| Render | Intactos |
| PostgreSQL producción | Intactos |
| APK / SUNMI | Sin modificar |
| Datos / ciclos / comisiones | Sin borrados ni cambios de reglas |

**Listo para publicar solo con su autorización.**
