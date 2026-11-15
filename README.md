# Sistema de Banca Moderna — Servidor + Panel Web + App de Terminal

**Sistema de Banca Moderna** (nombre elegido por Jose el 2026-11-14):
sistema propio de venta de lotería para bancas, construido desde la
especificación de la Etapa 1 (`~/workspace/goals/sistema-de-loter-a-para-bancas-app-apk-servidor/files/ESPECIFICACION.md`).
Incluye el **servidor central (API)**, el **panel web del consorcio** y la
**app Android de la terminal** (`android-app/`), que consume la API de
terminal aquí implementada.

**Estado: EN VIVO y probado (69/69 tests).**
- Panel: https://sistema-de-banca-moderna.onrender.com (Render, plan
  gratuito). Repo: `jdmdelivery/Sistema-Moderno-de-Banca`.
- La base en vivo es la **SQLite temporal interna** del servicio, por
  decisión de Jose el 2026-11-14 (Render solo permite una PostgreSQL
  gratuita por cuenta y la ocupa JDM): los datos se borran al reiniciar
  el servicio. Conectar la base definitiva (PostgreSQL) es un paso
  posterior ya previsto: basta fijar `DATABASE_URL` (la app la normaliza
  al dialecto psycopg 3 que trae `requirements.txt`); el `render.yaml`
  con el Blueprint original queda en el repo.
- **APK de la terminal compilado y verificado** (Etapa 3): ver
  `android-app/README.md`. Falta probarlo en la SUNMI física.

## Cómo correrlo en local

```bash
cd ~/workspace/sistema-loteria
.venv/bin/python -m uvicorn apps.api.main:app --port 8100
# Panel: http://127.0.0.1:8100/   (usuario: admin · clave: admin123)
```

- La base de datos se elige con `DATABASE_URL`. Sin esa variable usa
  SQLite local (`./sistema_loteria.db`). En producción será PostgreSQL
  (el código es portable: SQLAlchemy, sin SQL específico de un motor).
- Al arrancar, si la BD está vacía, se siembra sola: consorcio, usuario
  admin, los 19 sorteos observados en los videos (con horas de cierre
  típicas, editables), tipos QN/PL/SP y la tabla de pagos inicial
  (QN ×60/×10/×5 · PL ×1200/×400/×200 · SP ×2500 — todo editable).
- **Cambie la clave del admin** tras el primer despliegue (Panel → Usuarios).

## Cómo correr los tests

```bash
.venv/bin/python -m pytest -q   # 68 tests, BD SQLite temporal por test
```

## Estructura

```
apps/api/main.py       Rutas HTTP: panel del consorcio + API de terminal + panel web
apps/api/servicios.py  Reglas de negocio: sesiones, venta, pago, anulación,
                       resultados, saldos, caja, cuadre y reportes
apps/api/motor.py      Motor de ganadores (QN/PL/SP) y liquidación/reversión
apps/api/conectate.py  Importador de resultados de Conectate (ver abajo)
apps/api/models.py     Modelo de datos (especificación §5)
apps/api/seed.py       Datos iniciales
apps/api/security.py   Hash PBKDF2 de claves, tokens, seriales de ticket
apps/web/              Panel web en español (index.html, app.js, style.css)
tests/                 Suite pytest (venta, motor, pago, anulación, cuadre,
                       conectate, administración y cableado del panel)
```

## Piezas clave (y cómo se probaron)

- **Venta con el servidor como juez:** valida terminal (serial + token),
  sesión de operador, saldo prepago, cierre de cada sorteo, montos
  mín/máx y límites por número ANTES de vender. Si algo falla no hay
  venta, ni débito, ni número consumido. El ID es el **consecutivo
  global del consorcio**; el Serial es aleatorio de 10 caracteres; el QR
  de la terminal contendrá `LOT:{id}:{serial}`.
- **Jugadas multi-lotería:** una QN/PL marcada para varias loterías se
  replica por sorteo (el monto es por lotería, como en la pantalla de
  Juegos del video). El SP cruza exactamente dos loterías.
- **Tabla de pagos con vigencia:** cada jugada guarda la foto de los
  factores vigentes al vender; cambiar la tabla no toca tickets viejos.
- **Resultados en 3 estados:** PROPUESTO → CONFIRMADO → LIQUIDADO.
  Confirmar corre la liquidación en la misma operación. Revertir
  (solo admin) deshace la liquidación si ningún ticket afectado fue
  pagado; si ya se pagó, se bloquea y dice cuáles.
- **Pago único atómico:** la transición ganador→pagado es UNA
  actualización condicionada al estado. Dos pagos simultáneos = un pago
  y un rechazo con los datos reales del primer pago («Ya pagado en la
  sucursal X, el día Y…»). Se puede cobrar en cualquier sucursal.
- **Anulación acotada:** solo tickets vendidos y solo si NINGÚN sorteo
  del ticket ha cerrado; devuelve el total al saldo con su movimiento.
- **El papel no vale sin el servidor:** consultar/pagar/anular exigen
  ID + Serial y el servidor responde el estado y el monto reales.
- **Cuadre:** ventas − premios pagados − gastos + efectivo recibido,
  por terminal o por sucursal; la diferencia con lo contado queda
  registrada tal cual.
- **Reportes:** Resumen (Final, Por Lotería, Premios, Ganadores,
  Pagados, Nulos) y Tickets Pendientes con «pagado en otra sucursal»,
  también en **formato de texto impreso** igual al observado en video.

## ⚠️ Importador de Conectate (resultados)

El botón «Importar desde Conectate» intenta leer
`https://www.conectate.com.do/loterias/` y deja lo encontrado como
resultados **PROPUESTOS** para que un operador los revise y confirme.

**Advertencia comprobada el 2026-11-14:** el sitio está detrás de
Cloudflare y responde **HTTP 403** a los accesos automáticos desde
servidor (verificado desde esta máquina con navegador simulado). El
importador por tanto **falla con gracia**: registra cada intento en la
tabla de importaciones (hora, HTTP, motivo), **nunca inventa números**
y el operador siempre puede digitar los resultados a mano. Si en el
futuro Conectate ofrece una API o permite el acceso, el mismo
importador empezará a proponer sin cambiar nada más.

## Decisiones menores tomadas en esta etapa

1. **El premio pagado NO se acredita al saldo prepago.** La especificación
   (§5.1 y §6.1/§6.3) define los movimientos de saldo como recarga,
   débito por venta, crédito por anulación y ajuste, y compensa el premio
   pagado **en el cuadre** (la banca entregó ese efectivo de su caja).
   Acreditarlo también al saldo sería pagarlo dos veces.
2. **El monto de una jugada multi-lotería es por lotería** (la jugada se
   replica en cada sorteo marcado), como muestra la tabla de Juegos del
   video de referencia.
3. **Los tres premios de un resultado deben ser distintos** (así sale de
   la urna); el panel rechaza propuestas con números repetidos.
4. **Horas de cierre semilla** = las típicas del mercado (editables);
   el sorteo observado «La Primera» cierra 11:50 para su sorteo de 11:55.
5. **Vencimiento de premios:** el plazo (90 días) quedó como configuración
   del consorcio; el pase automático a VENCIDO se hará con la Etapa 3/4
   si Jose lo pide (ningún ticket se vence solo todavía).

## Qué falta

- **Etapa 4 — Piloto en la SUNMI física:** instalar el APK, crear la
  terminal en el panel con el serial real del equipo, pegar el token de
  un solo uso en la app y hacer una venta de prueba (ahí se verifica la
  impresión real y la lectura del QR impreso).
- **Base de datos definitiva** en el servidor en vivo (PostgreSQL) y
  cambio de la clave admin por la definitiva.
- **Firma release del APK** con clave propia cuando pase a producción.
