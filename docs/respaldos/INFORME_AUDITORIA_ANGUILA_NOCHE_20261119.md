# INFORME — Auditoría La Anguila nocturna (6–10 PM) · 2026-11-19

**Modo:** solo lectura en producción + corrección preparada en **local**  
**NO publicado en Render.** Sin inserts en PostgreSQL. Sin APK/SUNMI.  
**Zona:** America/Santo_Domingo  
**Evidencia:** `audit_anguila_noche_20261119.json`

---

## Respuestas directas

### 1. ¿Por qué llegaron los resultados hasta las 5:00 PM?

Porque hasta ~17:29 el cruce **Conéctate firmado × operador** (`anguillalottery.ai`) **sí funcionó** de forma intermitente.  
`La Anguila 5:00 PM` quedó `liquidado` `04-87-65` a las **17:29:00** (`fuente=conectate`, `ext=operador`).

Los 10 horarios de 8:00 AM a 5:00 PM del 19/11 están **todos liquidados** en PostgreSQL.

### 2. ¿Qué ocurrió exactamente a las 6:00 PM?

| Hecho | Evidencia |
|-------|-----------|
| Reloj **siguió** consultando | 242 importaciones 17:00–23:04, **0 fallos** de ciclo |
| Conéctate **sí** publicó 6:00 PM | Firmado: `62-94-33` |
| Operador **sí** tiene 6:00 PM hoy (HTML) | Misma triple `62-94-33`, fecha `19/11/2026` |
| Servidor **no pudo leer** el operador de forma fiable | Tras ~19:00: **100%** ciclos con aviso de operador/firma; `firmados` cae a 6 |
| Causa técnica | TLS de `anguillalottery.ai` = **certificado autofirmado** → `CERTIFICATE_VERIFY_FAILED` → `operador anguila sin respuesta` |
| PostgreSQL | **SIN_FILA** / sin observación |

No hay tope a las 5:00 PM en código. El reloj no se detuvo.

### 3. ¿Por qué no llegaron 7, 8, 9 y 10 PM?

| Sorteo | Conéctate | Operador (HTML real) | Cruce LIVE actual | PostgreSQL | Motivo |
|--------|-----------|----------------------|-------------------|------------|--------|
| 6:00 PM | 62-94-33 | 62-94-33 (19/11) | bloqueado por SSL en prod | SIN_FILA | Operador ilegible por cert autofirmado |
| 7:00 PM | 80-62-91 | 80-62-91 (19/11) | idem | SIN_FILA | idem |
| 8:00 PM | 97-94-68 | 97-94-68 (19/11) | idem | SIN_FILA | idem |
| 9:00 PM | 43-87-56 | 43-87-56 (19/11) | idem | SIN_FILA | idem |
| 10:00 PM | 21-66-98 | **Ausente hoy** (HTML aún muestra 18/11) | no hay cruce | SIN_FILA | Operador **aún no publica** el 19/11 + mismo bloqueo SSL |

### 4. ¿Dónde está el problema?

| Componente | ¿Culpable? |
|------------|------------|
| Conéctate | **No** — publicó 6–10 PM |
| Operador (contenido 6–9 PM) | **No** — ya están en el HTML |
| Operador (TLS) | **Sí** — cert autofirmado desde **2026-11-14** (`CN=anguillalottery.ai`, self-signed) |
| Reloj | **No** — activo toda la noche (~cada 60–80 s) |
| Validación 3 lecturas / 4 min | **No** — nunca llegó la 1.ª lectura |
| PostgreSQL | **No** — no guardó porque no hubo cruce |
| Panel / SUNMI | **No** — no hay fila que mostrar |
| Filtro 5:00 PM / bug AM-PM | **No** — descartado |

SHA-256 del certificado: `9857ff64fd6d20a8b0acea2a8a745868747dd48effc10863a0e2a1d5934f0525`

### 5. ¿Qué corrección necesita?

**Servidor (local, lista):**

1. `operador_oficial.descargar_anguila`: si la CA pública falla, reintentar **solo** si el SHA-256 del certificado coincide con el pin conocido (`ANGUILA_CERT_SHA256`).
2. `resultados_auto`: dejar de ocultar el error como `"firma pendiente"`; registrar el motivo real (`operador anguila sin respuesta` / `certificado no reconocido`).

**No** se rebajan las reglas de coincidencia Conéctate↔operador ni las 3 lecturas / 4 minutos.

### 6. ¿La corrección está probada en local?

**Sí.**

- `pytest tests/test_operador_oficial.py tests/test_anguila_haiti.py` → **19 passed**
- En vivo (local, sin tocar PG prod): `descargar_anguila()` OK; cruce acepta **5–9 PM** del 19/11; **10 PM** sigue ausente en operador (esperado).

### 7. ¿APK o solo servidor?

**Solo servidor.** APK/SUNMI no intervienen en la importación automática.

---

## Tabla operativa (19-nov-2026)

| Hora | Conéctate | Operador | Última consulta reloj | Validación | PostgreSQL | Panel | Motivo exacto |
|------|-----------|----------|----------------------|------------|------------|-------|---------------|
| 5:00 PM | 04-87-65 | 04-87-65 | continuo | liquidado 17:29 | liquidado | visible | OK |
| 6:00 PM | 62-94-33 | 62-94-33 | continuo post-18:00 | sin 1.ª lectura | SIN_FILA | no | SSL operador |
| 7:00 PM | 80-62-91 | 80-62-91 | continuo | sin 1.ª lectura | SIN_FILA | no | SSL operador |
| 8:00 PM | 97-94-68 | 97-94-68 | continuo | sin 1.ª lectura | SIN_FILA | no | SSL operador |
| 9:00 PM | 43-87-56 | 43-87-56 | continuo | sin 1.ª lectura | SIN_FILA | no | SSL operador |
| 10:00 PM | 21-66-98 | no hoy | continuo | sin cruce | SIN_FILA | no | operador sin fecha 19/11 (+ SSL) |

Comparación ayer (18/11): los cinco nocturnos **sí** liquidaron (6PM 18:14 … 10PM 23:58).

---

## Reloj / Render

- Logs API Render `/logs` → **404** (igual que auditorías previas); el reloj se documenta por tabla `importaciones`.
- Post-17:00: `242` ciclos `ok`, gaps máximos ~5 min (intervalo normal), **sin** parada nocturna.
- Tras ~19:00: todos los ciclos marcan aviso de firma/operador (antes etiquetado genérico como “firma pendiente”).

---

## Archivos de la corrección local (no publicados)

- `apps/api/operador_oficial.py` — pin TLS Anguila  
- `apps/api/resultados_auto.py` — detalle de error real  
- `tests/test_operador_oficial.py` — pruebas pin + nocturnos  

---

## Rollback / publicación

**Pendiente de su autorización.**  
Al publicar: el reloj debería crear observaciones de 6–9 PM en cuanto vuelva a cruzar (3 lecturas + 4 min) **sin** insert manual.  
10 PM entrará cuando `anguillalottery.ai` publique la fecha 19/11.

**Ideal externo:** que Anguila instale un certificado de CA pública; entonces el pin queda como respaldo.
