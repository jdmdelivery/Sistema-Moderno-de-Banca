"""Tres lecturas idénticas y diez minutos antes de confirmar.

El estado vive en la base, no en la memoria: un reinicio de Render no
pone el contador en cero. Un resultado manual bloqueado no se reemplaza.
Un confirmado que luego cambia en la fuente queda en alerta, sin tocar
premios ya pagados.
"""
from datetime import timedelta

from .models import ColaPremio, CorreccionPendiente, ObservacionResultado, Resultado, Sorteo, Usuario
from . import motor, servicios

LECTURAS_MINIMAS = 3
MINUTOS_ESTABLES = 10


def observar(db, sorteo, fecha, numeros, momento, origen="widget"):
    """Registra una lectura. Confirma solo si ya hubo tres iguales y 10 minutos."""
    obs = (
        db.query(ObservacionResultado)
        .filter_by(sorteo_id=sorteo.id, fecha=fecha)
        .first()
    )
    if obs is None:
        obs = ObservacionResultado(sorteo_id=sorteo.id, fecha=fecha, fuente="conectate")
        db.add(obs)
        db.flush()
    if obs.bloqueado:
        return "bloqueado"
    actual = db.query(Resultado).filter_by(sorteo_id=sorteo.id, fecha=fecha).first()
    if actual is not None and actual.fuente in ("manual", "simulado"):
        obs.bloqueado = True
        return "bloqueado"
    if actual is not None and actual.estado in ("confirmado", "liquidado"):
        if (actual.premio1, actual.premio2, actual.premio3) != numeros:
            _alerta(db, actual, numeros)
            return "alerta"
        return "igual"
    anterior = (obs.premio1, obs.premio2, obs.premio3)
    if anterior == numeros and obs.primera_en is not None:
        obs.lecturas += 1
        obs.ultima_en = momento
    else:
        obs.premio1, obs.premio2, obs.premio3 = numeros
        obs.lecturas = 1
        obs.primera_en = momento
        obs.ultima_en = momento
    _guardar_provisional(db, sorteo, fecha, numeros, momento, origen)
    transcurrido = momento - obs.primera_en
    if obs.lecturas >= LECTURAS_MINIMAS and transcurrido >= timedelta(minutes=MINUTOS_ESTABLES):
        return _confirmar(db, sorteo, fecha)
    return "provisional"


def _guardar_provisional(db, sorteo, fecha, numeros, momento, origen="widget"):
    fila = db.query(Resultado).filter_by(sorteo_id=sorteo.id, fecha=fecha).first()
    if fila is None:
        db.add(Resultado(
            sorteo_id=sorteo.id, fecha=fecha,
            premio1=numeros[0], premio2=numeros[1], premio3=numeros[2],
            estado="propuesto", fuente="conectate", externo=origen,
            recibido_en=momento, propuesto_en=momento,
        ))
        return
    if fila.estado in ("confirmado", "liquidado"):
        return
    fila.premio1, fila.premio2, fila.premio3 = numeros
    fila.estado = "propuesto"
    fila.fuente = "conectate"
    fila.externo = origen
    fila.recibido_en = momento


def _confirmar(db, sorteo, fecha):
    fila = db.query(Resultado).filter_by(sorteo_id=sorteo.id, fecha=fecha).first()
    if fila is None or fila.estado in ("confirmado", "liquidado"):
        return "igual"
    hoy = servicios.ahora_local().date()
    if fecha not in (hoy, hoy - timedelta(days=1)):
        return "fuera"
    admin = db.query(Usuario).filter_by(usuario="admin").first()
    if admin is None:
        return "sin_admin"
    fila.estado = "confirmado"
    fila.confirmado_por = admin.id
    fila.confirmado_en = servicios.ahora_local()
    servicios.auditar(
        db, "resultado", fila.id, "confirmacion_automatica", usuario_id=admin.id,
        detalle={"sorteo": sorteo.nombre, "fecha": str(fecha), "fuente": "conectate"},
    )
    if db.query(ColaPremio).filter_by(resultado_id=fila.id).first() is None:
        db.add(ColaPremio(resultado_id=fila.id, estado="pendiente"))
    db.flush()
    return "confirmado"


def _alerta(db, resultado, numeros):
    existe = (
        db.query(CorreccionPendiente)
        .filter_by(resultado_id=resultado.id)
        .filter(CorreccionPendiente.revisada_en.is_(None))
        .first()
    )
    if existe is not None:
        return
    db.add(CorreccionPendiente(
        resultado_id=resultado.id,
        premio1=numeros[0], premio2=numeros[1], premio3=numeros[2],
        fuente="conectate",
        detalle="La fuente cambió un resultado ya confirmado. No se reemplazó.",
    ))
    servicios.auditar(
        db, "resultado", resultado.id, "alerta_fuente",
        detalle={
            "guardado": [resultado.premio1, resultado.premio2, resultado.premio3],
            "fuente": list(numeros),
        },
    )


def procesar_cola(db):
    """Calcula premios pendientes de hoy y ayer. No paga y no repite."""
    hoy = servicios.ahora_local().date()
    ayer = hoy - timedelta(days=1)
    hechos = 0
    for item in db.query(ColaPremio).filter_by(estado="pendiente").all():
        resultado = db.get(Resultado, item.resultado_id)
        if resultado is None or resultado.fecha not in (hoy, ayer):
            item.estado = "omitido"
            item.nota = "fuera de hoy y ayer"
            item.procesado_en = servicios.ahora_local()
            continue
        if resultado.estado == "liquidado":
            item.estado = "hecho"
            item.procesado_en = servicios.ahora_local()
            continue
        motor.liquidar_resultado(db, resultado)
        from .comun import modo_desarrollo
        if modo_desarrollo():
            motor.liquidar_resultado_prueba(db, resultado)
        resultado.estado = "liquidado"
        resultado.liquidado_en = servicios.ahora_local()
        item.estado = "hecho"
        item.procesado_en = servicios.ahora_local()
        hechos += 1
    return hechos


def bloquear_manual(db, sorteo_id, fecha):
    obs = db.query(ObservacionResultado).filter_by(sorteo_id=sorteo_id, fecha=fecha).first()
    if obs is None:
        obs = ObservacionResultado(
            sorteo_id=sorteo_id, fecha=fecha, fuente="manual", bloqueado=True, lecturas=0,
        )
        db.add(obs)
    else:
        obs.bloqueado = True
        obs.fuente = "manual"


def resumen_observaciones(db, fecha):
    filas = []
    for sorteo in db.query(Sorteo).filter_by(activo=True).order_by(Sorteo.hora_sorteo, Sorteo.nombre):
        obs = db.query(ObservacionResultado).filter_by(sorteo_id=sorteo.id, fecha=fecha).first()
        resultado = db.query(Resultado).filter_by(sorteo_id=sorteo.id, fecha=fecha).first()
        filas.append({
            "sorteo": sorteo.nombre,
            "lecturas": obs.lecturas if obs else 0,
            "primera": obs.primera_en.isoformat(timespec="minutes") if obs and obs.primera_en else None,
            "ultima": obs.ultima_en.isoformat(timespec="minutes") if obs and obs.ultima_en else None,
            "bloqueado": bool(obs.bloqueado) if obs else False,
            "provisional": (
                f"{resultado.premio1:02d}-{resultado.premio2:02d}-{resultado.premio3:02d}"
                if resultado and resultado.estado not in ("confirmado", "liquidado") else None
            ),
            "confirmado": (
                f"{resultado.premio1:02d}-{resultado.premio2:02d}-{resultado.premio3:02d}"
                if resultado and resultado.estado in ("confirmado", "liquidado") else None
            ),
            "fuente": resultado.fuente if resultado else None,
            "estado": (
                "CONFIRMADO" if resultado and resultado.estado in ("confirmado", "liquidado")
                else "PROVISIONAL" if resultado else "PENDIENTE"
            ),
        })
    return filas
