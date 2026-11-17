"""Resultados desde RDLotto (https://rdlotto.com/api-docs).

Solo se usan los endpoints documentados. La propia API dice que sus números
son información y no la fuente oficial del operador. Por eso un resultado
`verified` queda EN VERIFICACIÓN: no liquida ni habilita pagos. Un resultado
`live` queda RECIBIDO y tampoco se paga. Si la fuente falla, no se inventan
números.

La correspondencia usa el identificador `game` y la sesión, no el parecido
del nombre. Una diferencia de horario mayor a 10 minutos deja el sorteo
sin conexión.
"""
import json
import urllib.error
import urllib.request
from datetime import datetime, timedelta

from .comun import ahora_local
from .models import CorreccionPendiente, Importacion, Resultado, ResultadoVersion, Sorteo
from .servicios import auditar

URL_RESULTADOS = "https://rdlotto.com/api/v1/results"
URL_RECIENTES = "https://rdlotto.com/api/v1/latest"
FUENTE = "rdlotto"
TOLERANCIA_MINUTOS = 10
INTERVALO_SEGUNDOS = 90

# nombre interno, game, session, hora publicada por RDLotto (America/Santo_Domingo)
# Solo entran juegos cuyo identificador y hora ya estaban comprobados.
# Un horario parecido no autoriza a copiar los números de otro sorteo.
CONEXIONES = (
    ("La Primera 12:00 PM", "la-primera-quiniela", "dia", "12:00"),
    ("La Suerte Dominicana 12:30 PM", "la-suerte-quiniela", "dia", "12:30"),
    ("King Lottery 12:30 PM", "king-lottery-quiniela", "dia", "12:30"),
    ("Quiniela Real 12:55 PM", "quiniela-real", "dia", "12:55"),
    ("La Anguila 1:00 PM", "anguila-medio-dia", "dia", "13:00"),
    ("La Suerte Dominicana 6:00 PM", "la-suerte-quiniela", "noche", "18:00"),
    ("La Anguila 6:00 PM", "anguila-tarde", "dia", "18:00"),
    ("King Lottery 7:30 PM", "king-lottery-quiniela", "noche", "19:30"),
    ("Loteka 7:55 PM", "quiniela-loteka", "noche", "19:55"),
    ("La Anguila 9:00 PM", "anguila-noche", "noche", "21:00"),
)

_SIN_FUENTE = "Sin fuente RDLotto comprobada para este horario."
SIN_CONEXION = (
    ("Florida 2:30 PM", "RDLotto publica Florida día a las 14:30, pero no hay un identificador de juego comprobado."),
    ("Florida 10:45 PM", "RDLotto publica Florida noche a las 22:45, pero no hay un identificador de juego comprobado."),
    ("Haiti Bolet 9:30 AM", _SIN_FUENTE),
    ("Haiti Bolet 10:30 AM", _SIN_FUENTE),
    ("Haiti Bolet 11:30 AM", _SIN_FUENTE),
    ("Haiti Bolet 5:30 PM", _SIN_FUENTE),
    ("Haiti Bolet 6:30 PM", _SIN_FUENTE),
    ("Haiti Bolet 7:30 PM", _SIN_FUENTE),
    ("La Anguila 8:00 AM", _SIN_FUENTE),
    ("La Anguila 9:00 AM", _SIN_FUENTE),
    ("La Anguila 10:00 AM", _SIN_FUENTE),
    ("La Anguila 11:00 AM", _SIN_FUENTE),
    ("La Anguila 12:00 PM", _SIN_FUENTE),
    ("La Anguila 2:00 PM", _SIN_FUENTE),
    ("La Anguila 3:00 PM", _SIN_FUENTE),
    ("La Anguila 4:00 PM", _SIN_FUENTE),
    ("La Anguila 5:00 PM", _SIN_FUENTE),
    ("La Anguila 7:00 PM", _SIN_FUENTE),
    ("La Anguila 8:00 PM", _SIN_FUENTE),
    ("La Anguila 10:00 PM", _SIN_FUENTE),
    ("La Primera 7:00 PM", "RDLotto publica La Primera noche a las 19:00, pero la sesión de noche no está comprobada."),
    ("Leidsa 3:55 PM", "No hay un identificador Leidsa comprobado."),
    ("Leidsa 8:55 PM", "No hay un identificador Leidsa comprobado. nacional-noche es otro sorteo y no se usa aquí."),
    ("Lotedom 12:00 PM", "RDLotto publica Quiniela LoteDom a las 12:00, pero no hay un identificador de juego comprobado."),
    ("Lotería Nacional 2:30 PM", _SIN_FUENTE),
    ("Lotería Nacional 6:00 PM", _SIN_FUENTE),
    ("Lotería Nacional 9:00 PM", "nacional-noche está publicado a las 20:55, no a las 21:00. No se asignan esos números."),
    ("Lotería Real Noche 8:00 PM", _SIN_FUENTE),
    ("New York 3:30 PM", "RDLotto publica New York día a las 15:30, pero no hay un identificador de juego comprobado."),
    ("New York 11:30 PM", "RDLotto publica New York noche a las 23:30, pero no hay un identificador de juego comprobado."),
)

_POR_GAME = {(game, session): (nombre, hora) for nombre, game, session, hora in CONEXIONES}


def cobertura():
    """Lista fija para el panel: conectadas y las que se dejan fuera, con el motivo."""
    conectadas = [
        {"sorteo": nombre, "game": game, "session": session, "hora_fuente": hora, "conectada": True, "motivo": ""}
        for nombre, game, session, hora in CONEXIONES
    ]
    fuera = [
        {"sorteo": nombre, "game": None, "session": None, "hora_fuente": None, "conectada": False, "motivo": motivo}
        for nombre, motivo in SIN_CONEXION
    ]
    return conectadas + fuera


def descargar(fecha, timeout=20):
    """GET documentado /api/v1/results?date=. Devuelve (documento, error)."""
    url = f"{URL_RESULTADOS}?date={fecha.isoformat()}"
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "banca-moderna"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8")), None
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}"
    except Exception as e:
        return None, f"Error de red: {e}"


def _hora(texto):
    try:
        return datetime.strptime(str(texto), "%H:%M").time()
    except (TypeError, ValueError):
        return None


def _minutos(a, b):
    return abs((a.hour * 60 + a.minute) - (b.hour * 60 + b.minute))


def _premios(numbers):
    if not isinstance(numbers, list) or len(numbers) < 3:
        return None
    try:
        nums = [int(x) for x in numbers[:3]]
    except (TypeError, ValueError):
        return None
    # Se permiten repeticiones; solo se exige formato y rango 0–99.
    if any(n < 0 or n > 99 for n in nums):
        return None
    return nums


def _estado_fuente(status):
    if status == "verified":
        return "en_verificacion"
    if status in ("live", "live_complete"):
        return "recibido"
    return None


def _anotar_version(db, resultado, detalle):
    db.add(
        ResultadoVersion(
            resultado_id=resultado.id,
            version=resultado.version,
            premio1=resultado.premio1,
            premio2=resultado.premio2,
            premio3=resultado.premio3,
            estado=resultado.estado,
            fuente=resultado.fuente,
            detalle=detalle,
        )
    )


def aplicar_documento(db, fecha, documento, usuario_id=None):
    """Guarda lo confiable del documento. No liquida y no inventa números."""
    sorteos = {s.nombre: s for s in db.query(Sorteo).all()}
    draws = documento.get("draws") if isinstance(documento, dict) else None
    if not isinstance(draws, list):
        return {"ok": False, "motivo": "La respuesta no trae la lista draws.", "guardados": 0, "alertas": []}
    guardados = 0
    alertas = []
    for draw in draws:
        if not isinstance(draw, dict):
            continue
        if str(draw.get("date")) != fecha.isoformat():
            continue
        clave = (draw.get("game"), draw.get("session"))
        if clave not in _POR_GAME:
            continue
        nombre, hora_esperada = _POR_GAME[clave]
        sorteo = sorteos.get(nombre)
        if sorteo is None:
            alertas.append(f"{nombre}: no está en el catálogo interno")
            continue
        hora_draw = _hora(draw.get("time"))
        hora_mapa = _hora(hora_esperada)
        if hora_draw is None or hora_mapa is None or hora_draw != hora_mapa:
            alertas.append(f"{nombre}: la fuente cambió la hora ({draw.get('time')}); no se guardó")
            continue
        if _minutos(sorteo.hora_sorteo, hora_mapa) > TOLERANCIA_MINUTOS:
            alertas.append(f"{nombre}: el horario interno no coincide con la fuente; no se guardó")
            continue
        estado = _estado_fuente(draw.get("status"))
        if estado is None:
            alertas.append(f"{nombre}: estado {draw.get('status')} no es confiable; no se guardó")
            continue
        premios = _premios(draw.get("numbers"))
        if premios is None:
            alertas.append(f"{nombre}: los números no son tres premios distintos de 00 a 99; no se guardó")
            continue
        fuentes = draw.get("reportedBy") if isinstance(draw.get("reportedBy"), list) else []
        detalle = json.dumps(
            {"url": draw.get("url"), "reportedBy": fuentes, "status": draw.get("status")},
            ensure_ascii=False,
        )
        if estado == "en_verificacion" and len(fuentes) < 2:
            estado = "recibido"
            alertas.append(f"{nombre}: verified sin dos fuentes independientes; queda recibido, no pagable")
        fila = db.query(Resultado).filter_by(sorteo_id=sorteo.id, fecha=fecha).first()
        if fila is not None and fila.fuente == "simulado":
            alertas.append(f"{nombre}: hay un resultado simulado; RDLotto no lo reemplaza")
            continue
        if fila is not None and fila.fuente == "conectate":
            actual = (fila.premio1, fila.premio2, fila.premio3)
            if actual != tuple(premios):
                alertas.append(f"{nombre}: Conéctate y RDLotto no coinciden; no se reemplazó")
            else:
                alertas.append(f"{nombre}: RDLotto repite el resultado de Conéctate; no se duplicó")
            continue
        if fila is not None and fila.estado in ("confirmado", "liquidado"):
            actual = (fila.premio1, fila.premio2, fila.premio3)
            if actual != tuple(premios):
                db.add(
                    CorreccionPendiente(
                        resultado_id=fila.id,
                        premio1=premios[0], premio2=premios[1], premio3=premios[2],
                        fuente=FUENTE,
                        detalle=detalle,
                    )
                )
                auditar(
                    db, "resultado", fila.id, "correccion_pendiente", usuario_id=usuario_id,
                    detalle={"sorteo": nombre, "anterior": [f"{n:02d}" for n in actual],
                             "nuevo": [f"{n:02d}" for n in premios]},
                )
                alertas.append(f"{nombre}: la fuente corrigió un resultado ya liquidado; quedó para revisión")
            continue
        if fila is not None and (fila.premio1, fila.premio2, fila.premio3) == tuple(premios) and fila.estado == estado:
            continue
        if fila is None:
            fila = Resultado(
                sorteo_id=sorteo.id, fecha=fecha, premio1=premios[0], premio2=premios[1], premio3=premios[2],
                estado=estado, fuente=FUENTE, version=1, externo=draw.get("game"),
                recibido_en=ahora_local(),
            )
            db.add(fila)
            db.flush()
        else:
            fila.premio1, fila.premio2, fila.premio3 = premios
            fila.estado = estado
            fila.fuente = FUENTE
            fila.externo = draw.get("game")
            fila.version = int(fila.version or 1) + 1
            fila.recibido_en = ahora_local()
        _anotar_version(db, fila, detalle)
        guardados += 1
    return {"ok": True, "guardados": guardados, "alertas": alertas}


def sincronizar(db, fecha, usuario_id=None, documento=None):
    """Una consulta del día. `documento` permite probar sin red."""
    if documento is None:
        documento, error = descargar(fecha)
        if documento is None:
            db.add(
                Importacion(
                    fuente=FUENTE, url=f"{URL_RESULTADOS}?date={fecha.isoformat()}",
                    fecha_objetivo=fecha, ok=False, encontrados=0, detalle=error,
                )
            )
            db.commit()
            return {"ok": False, "motivo": error, "guardados": 0, "alertas": [error]}
    resumen = aplicar_documento(db, fecha, documento, usuario_id)
    db.add(
        Importacion(
            fuente=FUENTE, url=f"{URL_RESULTADOS}?date={fecha.isoformat()}",
            fecha_objetivo=fecha, ok=bool(resumen.get("ok")),
            estado_http=200 if resumen.get("ok") else None,
            encontrados=resumen.get("guardados", 0),
            detalle="; ".join(resumen.get("alertas") or []) or "Sin alertas",
        )
    )
    if resumen.get("ok"):
        from .comun import modo_desarrollo
        from .motor import liquidar_pruebas_fecha

        if modo_desarrollo():
            resumen["pruebas_liquidadas"] = liquidar_pruebas_fecha(db, fecha)
            resumen["no_oficial"] = True
    db.commit()
    return resumen


def en_ventana(sorteo, momento):
    """Desde el cierre hasta dos horas después de la hora del sorteo."""
    inicio = datetime.combine(momento.date(), sorteo.hora_cierre)
    fin = datetime.combine(momento.date(), sorteo.hora_sorteo) + timedelta(hours=2)
    return inicio <= momento <= fin


def hay_sorteo_en_ventana(db, momento=None):
    momento = momento or ahora_local()
    nombres = {nombre for nombre, _, _, _ in CONEXIONES}
    for sorteo in db.query(Sorteo).all():
        if sorteo.nombre in nombres and sorteo.activo and en_ventana(sorteo, momento):
            return True
    return False
