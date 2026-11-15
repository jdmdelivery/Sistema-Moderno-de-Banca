"""Motor de ganadores: evalúa jugadas contra los resultados confirmados y
liquida/revierte sorteos. Las reglas viven aquí; los factores NO: cada jugada
guarda la foto de la tabla de pagos vigente al momento de la venta.
"""
import json

from sqlalchemy import or_

from .comun import D, ErrorServicio
from .models import Jugada, Resultado, Ticket


def factores_de(jugada) -> dict:
    return {k: D(v) for k, v in json.loads(jugada.factores_json or "{}").items()}


def evaluar_jugada(jugada, res_a, res_b=None):
    """Devuelve (premio, detalle). res_a = resultado del sorteo principal;
    res_b = resultado del segundo sorteo (solo Súper Palé)."""
    factores = factores_de(jugada)
    monto = D(jugada.monto)
    tipo = jugada.tipo.codigo
    if tipo == "QN":
        for clave, numero in (("1ro", res_a.premio1), ("2do", res_a.premio2), ("3ro", res_a.premio3)):
            if jugada.n1 == numero:
                return D(monto * factores[clave]), clave
        return D(0), None
    if tipo == "PL":
        if jugada.n1 == jugada.n2:
            # La tabla vigente solo paga 1-2, 1-3 y 2-3. Los tres premios
            # oficiales son distintos, así que una pareja repetida no ocupa
            # dos posiciones y no gana. No existe un factor nuevo para 1-1.
            return D(0), None
        premios = [res_a.premio1, res_a.premio2, res_a.premio3]
        if jugada.n1 in premios and jugada.n2 in premios:
            posiciones = sorted([premios.index(jugada.n1) + 1, premios.index(jugada.n2) + 1])
            clave = f"{posiciones[0]}-{posiciones[1]}"
            return D(monto * factores[clave]), clave
        return D(0), None
    if tipo == "SP":
        if res_b is None:
            raise ErrorServicio(500, "Súper Palé sin el resultado de la segunda lotería")
        if {jugada.n1, jugada.n2} == {res_a.premio1, res_b.premio1}:
            return D(monto * factores["sp"]), "sp"
        return D(0), None
    raise ErrorServicio(500, f"Tipo de jugada sin regla en el motor: {tipo}")


def recomputar_ticket(db, ticket):
    """Recalcula premio_total y estado de un ticket según sus jugadas evaluadas."""
    if ticket.estado in ("pagado", "anulado", "vencido"):
        return
    premio = sum(
        (D(j.premio) for j in ticket.jugadas if j.evaluada and j.premio is not None),
        D(0),
    )
    ticket.premio_total = D(premio)
    if ticket.jugadas and all(j.evaluada for j in ticket.jugadas):
        ticket.estado = "ganador" if premio > 0 else "no_ganador"
    else:
        ticket.estado = "vendido"


def liquidar_resultado(db, resultado):
    """Evalúa las jugadas reales pendientes de este resultado.

    QN y PL se liquidan con este sorteo. El súper palé espera a que la otra
    lotería también esté confirmada. Los tickets de prueba no entran aquí.
    """
    return _liquidar(db, resultado, prueba=False)


def liquidar_pruebas_fecha(db, fecha):
    """Liquida solo tickets de prueba contra resultados ya recibidos.

    No cambia el estado del resultado y no evalúa jugadas reales. Un
    resultado en verificación alcanza para la prueba; el pago real sigue
    exigiendo la confirmación del consorcio.
    """
    afectados = 0
    filas = db.query(Resultado).filter_by(fecha=fecha).all()
    for resultado in filas:
        if resultado.estado == "error_fuente":
            continue
        afectados += _liquidar(db, resultado, prueba=True)
    return afectados


def _liquidar(db, resultado, prueba):
    fecha, sid = resultado.fecha, resultado.sorteo_id
    afectados = set()
    jugadas = (
        db.query(Jugada)
        .join(Ticket)
        .filter(
            Jugada.sorteo_id == sid,
            Jugada.fecha == fecha,
            Jugada.evaluada.is_(False),
            Ticket.estado != "anulado",
            Ticket.es_prueba.is_(prueba),
        )
        .all()
    )
    for j in jugadas:
        if j.tipo.codigo in ("QN", "PL"):
            premio, detalle = evaluar_jugada(j, resultado)
            j.evaluada, j.premio, j.detalle_eval = True, premio, detalle
            afectados.add(j.ticket_id)
    sp = (
        db.query(Jugada)
        .join(Ticket)
        .filter(
            Jugada.fecha == fecha,
            Jugada.evaluada.is_(False),
            Ticket.estado != "anulado",
            Ticket.es_prueba.is_(prueba),
            or_(Jugada.sorteo_id == sid, Jugada.sorteo2_id == sid),
        )
        .all()
    )
    for j in sp:
        if j.tipo.codigo != "SP":
            continue
        r1 = _resultado_util(db, j.sorteo_id, fecha, prueba)
        r2 = _resultado_util(db, j.sorteo2_id, fecha, prueba)
        if r1 is None or r2 is None:
            continue
        premio, detalle = evaluar_jugada(j, r1, r2)
        j.evaluada, j.premio, j.detalle_eval = True, premio, detalle
        afectados.add(j.ticket_id)
    for ticket_id in afectados:
        ticket = db.get(Ticket, ticket_id)
        if ticket is not None:
            recomputar_ticket(db, ticket)
    return len(afectados)


def _resultado_util(db, sorteo_id, fecha, prueba):
    r = db.query(Resultado).filter_by(sorteo_id=sorteo_id, fecha=fecha).first()
    if r is None or r.estado == "error_fuente":
        return None
    if prueba or r.estado in ("confirmado", "liquidado"):
        return r
    return None


def revertir_liquidacion(db, resultado):
    """Deshace la evaluación de las jugadas que dependían de este resultado.

    Si algún ticket afectado ya fue PAGADO, la reversión se bloquea: no se
    puede deshacer un premio que ya salió por la caja.
    """
    fecha, sid = resultado.fecha, resultado.sorteo_id
    jugadas = (
        db.query(Jugada)
        .filter(
            Jugada.fecha == fecha,
            Jugada.evaluada.is_(True),
            or_(
                Jugada.sorteo_id == sid,
                Jugada.sorteo2_id == sid,
            ),
        )
        .all()
    )
    # Solo las que realmente dependían de ESTE resultado: QN/PL de este sorteo
    # y SP que lo crucen. (Las de otros sorteos no se tocan.)
    propias = []
    for j in jugadas:
        if j.ticket is not None and j.ticket.es_prueba:
            continue
        if j.tipo.codigo in ("QN", "PL") and j.sorteo_id == sid:
            propias.append(j)
        elif j.tipo.codigo == "SP" and (j.sorteo_id == sid or j.sorteo2_id == sid):
            propias.append(j)
    ticket_ids = {j.ticket_id for j in propias}
    pagados = [
        t.id
        for t in (db.get(Ticket, tid) for tid in ticket_ids)
        if t is not None and t.estado == "pagado"
    ]
    if pagados:
        raise ErrorServicio(
            409,
            "No se puede revertir: ya se pagó el/los ticket(s) "
            + ", ".join(str(x) for x in sorted(pagados))
            + " con este resultado. Reviértalo solo tras resolver esos pagos.",
        )
    for j in propias:
        j.evaluada, j.premio, j.detalle_eval = False, None, None
    for tid in ticket_ids:
        ticket = db.get(Ticket, tid)
        if ticket is not None:
            recomputar_ticket(db, ticket)
    return len(ticket_ids)
