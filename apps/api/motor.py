"""Motor de ganadores: evalúa jugadas contra los resultados confirmados y
liquida/revierte sorteos. Las reglas viven aquí; los factores NO: cada jugada
guarda la foto de la tabla de pagos vigente al momento de la venta.
"""
import json
from collections import Counter

from sqlalchemy import or_

from .comun import D, ErrorServicio
from .models import Jugada, Resultado, Ticket, Usuario


def factores_de(jugada) -> dict:
    return {k: D(v) for k, v in json.loads(jugada.factores_json or "{}").items()}


def _resultado_coincide(jugada, resultado, sorteo_id):
    """Un resultado solo aplica si coinciden fecha y sorteo exactos.

    La igualdad de números no basta: un 25 del día 14 no gana un ticket del 15.
    """
    if resultado is None or sorteo_id is None or jugada.fecha is None:
        return False
    if resultado.estado == "error_fuente":
        return False
    return resultado.sorteo_id == sorteo_id and resultado.fecha == jugada.fecha


def evaluar_jugada(jugada, res_a, res_b=None):
    """Devuelve (premio, detalle). res_a = resultado del sorteo principal;
    res_b = resultado del segundo sorteo (solo Súper Palé).

    Exige que cada resultado sea de la misma fecha y del mismo sorteo que la
    jugada. Nunca se acepta el «último resultado disponible» de otra fecha.
    """
    if not _resultado_coincide(jugada, res_a, jugada.sorteo_id):
        raise ErrorServicio(
            500,
            "El resultado no corresponde a la fecha y el sorteo de la jugada",
        )
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
        if not _resultado_coincide(jugada, res_b, jugada.sorteo2_id):
            raise ErrorServicio(
                500,
                "Súper Palé: el segundo resultado no corresponde a la fecha y el sorteo de la jugada",
            )
        if {jugada.n1, jugada.n2} == {res_a.premio1, res_b.premio1}:
            return D(monto * factores["sp"]), "sp"
        return D(0), None
    if tipo == "TR":
        # Orden libre con multiset: cada número debe coincidir en cantidad,
        # no basta con que aparezca alguna vez (12-12-38 ≠ 12-38-38).
        if jugada.n2 is None or jugada.n3 is None:
            return D(0), None
        oficiales = Counter([res_a.premio1, res_a.premio2, res_a.premio3])
        jugados = Counter([jugada.n1, jugada.n2, jugada.n3])
        if oficiales == jugados:
            return D(monto * factores["tr"]), "tr"
        return D(0), None
    raise ErrorServicio(500, f"Tipo de jugada sin regla en el motor: {tipo}")


def recomputar_ticket(db, ticket):
    """Recalcula premio_total y estado de un ticket según sus jugadas evaluadas.

    Un premio ya cobrado no vuelve a quedar pendiente. Si hay premios
    confirmados sin cobrar, el ticket pasa a ganador/parcial aunque otros
    sorteos sigan abiertos. Si un sorteo posterior confirma un premio nuevo
    sobre un ticket ya cobrado, se reabre a parcial sin tocar los pagos previos.
    """
    if ticket.estado in ("anulado", "vencido"):
        return
    premio = sum(
        (D(j.premio) for j in ticket.jugadas if j.evaluada and j.premio is not None),
        D(0),
    )
    ticket.premio_total = D(premio)
    impagos = [
        j for j in ticket.jugadas
        if j.evaluada and j.premio is not None and D(j.premio) > 0 and not j.pagada
    ]
    # Ticket ya cobrado completo: solo se reabre si aparece un premio nuevo.
    if ticket.estado == "pagado":
        if impagos:
            ticket.estado = "parcial"
        return
    hay_pagadas = any(j.pagada for j in ticket.jugadas)
    todas_evaluadas = bool(ticket.jugadas) and all(j.evaluada for j in ticket.jugadas)
    if impagos:
        # Premios confirmados se pueden cobrar aunque otros sorteos sigan abiertos.
        # Un tramo ya cobrado no vuelve a "ganador": queda "parcial".
        ticket.estado = "parcial" if hay_pagadas else "ganador"
        return
    if not todas_evaluadas:
        # Sin premio pendiente: si ya hubo cobro parcial, el ticket sigue parcial
        # hasta que cierren los sorteos restantes; si no, permanece vendido.
        ticket.estado = "parcial" if hay_pagadas else "vendido"
        return
    if hay_pagadas:
        ticket.estado = "pagado"
        if ticket.pagado_en is None:
            pagadas = [j for j in ticket.jugadas if j.pagada and j.pagado_en is not None]
            if pagadas:
                ultimo = max(pagadas, key=lambda j: j.pagado_en)
                ticket.pagado_en = ultimo.pagado_en
                ticket.pagado_por_usuario_id = ultimo.pagado_por_usuario_id
                ticket.pago_operacion_id = ultimo.pago_operacion_id
                if ultimo.pagado_por_usuario_id:
                    cajero = db.get(Usuario, ultimo.pagado_por_usuario_id)
                    if cajero is not None:
                        ticket.pagado_en_sucursal_id = cajero.sucursal_id
        return
    ticket.estado = "no_ganador"


def liquidar_resultado_prueba(db, resultado):
    """Evalúa solo los tickets de prueba de este resultado. No cambia su estado."""
    return _liquidar(db, resultado, prueba=True)


def pruebas_pagadas_con(db, resultado):
    jugadas = (
        db.query(Jugada)
        .join(Ticket)
        .filter(
            Jugada.fecha == resultado.fecha,
            Ticket.es_prueba.is_(True),
            or_(Ticket.estado == "pagado", Jugada.pagada.is_(True)),
            or_(Jugada.sorteo_id == resultado.sorteo_id, Jugada.sorteo2_id == resultado.sorteo_id),
        )
        .all()
    )
    return sorted({j.ticket_id for j in jugadas})


def reabrir_pruebas(db, resultado):
    """Deja sin evaluar las jugadas de prueba no pagadas para poder corregirlas."""
    jugadas = (
        db.query(Jugada)
        .join(Ticket)
        .filter(
            Jugada.fecha == resultado.fecha,
            Jugada.evaluada.is_(True),
            Ticket.es_prueba.is_(True),
            Ticket.estado.notin_(("pagado", "anulado")),
            or_(Jugada.sorteo_id == resultado.sorteo_id, Jugada.sorteo2_id == resultado.sorteo_id),
        )
        .all()
    )
    tickets = set()
    for jugada in jugadas:
        if jugada.pagada:
            continue
        jugada.evaluada, jugada.premio, jugada.detalle_eval = False, None, None
        tickets.add(jugada.ticket_id)
    for ticket_id in tickets:
        ticket = db.get(Ticket, ticket_id)
        if ticket is not None:
            recomputar_ticket(db, ticket)
    return len(tickets)


def liquidar_resultado(db, resultado):
    """Evalúa las jugadas reales pendientes de este resultado.

    QN, PL y TR se liquidan con este sorteo. El súper palé espera a que la otra
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
    """Liquida solo jugadas con la misma fecha y el mismo sorteo del resultado.

    Clave obligatoria: (resultado.fecha, resultado.sorteo_id). No se usa el
    último resultado de otra fecha aunque los números coincidan.
    """
    fecha, sid = resultado.fecha, resultado.sorteo_id
    if fecha is None or sid is None:
        return 0
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
        if j.tipo.codigo not in ("QN", "PL", "TR"):
            continue
        if not _resultado_coincide(j, resultado, j.sorteo_id):
            continue
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
        # Ambos resultados deben ser de la misma fecha de la jugada.
        r1 = _resultado_util(db, j.sorteo_id, j.fecha, prueba)
        r2 = _resultado_util(db, j.sorteo2_id, j.fecha, prueba)
        if r1 is None or r2 is None:
            continue
        if not _resultado_coincide(j, r1, j.sorteo_id) or not _resultado_coincide(j, r2, j.sorteo2_id):
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
    """Resultado aplicable a un ticket: exacto por (sorteo_id, fecha).

    Nunca cae al resultado más reciente de otra fecha.
    """
    if sorteo_id is None or fecha is None:
        return None
    r = db.query(Resultado).filter_by(sorteo_id=sorteo_id, fecha=fecha).first()
    if r is None or r.estado == "error_fuente":
        return None
    if prueba or r.estado in ("confirmado", "liquidado"):
        return r
    return None


def premio_respaldado(db, jugada, prueba=False):
    """Recalcula el premio con el resultado exacto de la fecha de la jugada.

    Si falta el resultado de esa fecha/sorteo, o es solo provisional en un
    cobro real, no respalda el pago. No usa resultados de otros días.
    """
    if jugada is None or jugada.fecha is None:
        return None
    tipo = jugada.tipo.codigo if jugada.tipo else None
    if tipo in ("QN", "PL", "TR"):
        r1 = _resultado_util(db, jugada.sorteo_id, jugada.fecha, prueba)
        if r1 is None:
            return None
        premio, detalle = evaluar_jugada(jugada, r1)
        return premio, detalle, r1
    if tipo == "SP":
        r1 = _resultado_util(db, jugada.sorteo_id, jugada.fecha, prueba)
        r2 = _resultado_util(db, jugada.sorteo2_id, jugada.fecha, prueba)
        if r1 is None or r2 is None:
            return None
        premio, detalle = evaluar_jugada(jugada, r1, r2)
        return premio, detalle, r1
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
    # Solo las que realmente dependían de ESTE resultado: QN/PL/TR de este sorteo
    # y SP que lo crucen. (Las de otros sorteos no se tocan.)
    propias = []
    for j in jugadas:
        if j.ticket is not None and j.ticket.es_prueba:
            continue
        if j.tipo.codigo in ("QN", "PL", "TR") and j.sorteo_id == sid:
            propias.append(j)
        elif j.tipo.codigo == "SP" and (j.sorteo_id == sid or j.sorteo2_id == sid):
            propias.append(j)
    ticket_ids = {j.ticket_id for j in propias}
    pagados = [
        t.id
        for t in (db.get(Ticket, tid) for tid in ticket_ids)
        if t is not None and (t.estado == "pagado" or any(j.pagada for j in propias if j.ticket_id == t.id))
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
