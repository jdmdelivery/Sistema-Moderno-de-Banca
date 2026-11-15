"""Servicios centrales: sesiones, terminales, venta, consulta/pago/anulación,
resultados, saldos, caja, cuadre y reportes. Toda regla de negocio vive aquí;
las rutas (main.py) solo traducen HTTP <-> servicio.
"""
import json
from datetime import timedelta

from sqlalchemy import func, update

from . import motor
from .comun import D, ErrorServicio, ahora_local
from .models import (
    Auditoria,
    Consorcio,
    Cuadre,
    Jugada,
    LimiteVenta,
    MovimientoSaldo,
    Resultado,
    Sesion,
    Sorteo,
    Sucursal,
    TablaPagos,
    Terminal,
    Ticket,
    TipoJugada,
    TransaccionCaja,
    Usuario,
)
from .security import generar_serial, hash_token, nuevo_token

CLAVES_REQUERIDAS = {"QN": ["1ro", "2do", "3ro"], "PL": ["1-2", "1-3", "2-3"], "SP": ["sp"]}


# ---------------------------------------------------------------- auditoría
def auditar(db, entidad, entidad_id, accion, usuario_id=None, terminal_id=None, detalle=None):
    db.add(
        Auditoria(
            entidad=entidad,
            entidad_id=str(entidad_id),
            accion=accion,
            usuario_id=usuario_id,
            terminal_id=terminal_id,
            detalle_json=json.dumps(detalle or {}, ensure_ascii=False, default=str),
        )
    )


# ----------------------------------------------------------------- sesiones
def crear_sesion(db, usuario, tipo, terminal_id=None, horas=12):
    token = nuevo_token()
    db.add(
        Sesion(
            token_hash=hash_token(token),
            usuario_id=usuario.id,
            tipo=tipo,
            terminal_id=terminal_id,
            expira_en=ahora_local() + timedelta(hours=horas),
        )
    )
    db.flush()
    return token


def sesion_y_usuario(db, token, tipo=None):
    if not token:
        raise ErrorServicio(401, "Falta el token de sesión")
    sesion = db.query(Sesion).filter_by(token_hash=hash_token(token)).first()
    if sesion is None or sesion.expira_en < ahora_local():
        raise ErrorServicio(401, "Sesión inválida o vencida: inicie sesión de nuevo")
    if tipo is not None and sesion.tipo != tipo:
        raise ErrorServicio(401, "Esa sesión no sirve para esta operación")
    usuario = db.get(Usuario, sesion.usuario_id)
    if usuario is None or not usuario.activo:
        raise ErrorServicio(401, "El usuario está inactivo")
    return sesion, usuario


def cerrar_sesion(db, token):
    sesion = db.query(Sesion).filter_by(token_hash=hash_token(token or "")).first()
    if sesion is not None:
        db.delete(sesion)
        db.commit()


# ---------------------------------------------------------------- terminales
def terminal_de_sucursal(db, sucursal):
    """La terminal de trabajo de una sucursal (2026-11-14: sin token ni
    activación — el operador entra con usuario y contraseña y el servidor
    resuelve la terminal desde SU sucursal). Devuelve la primera terminal
    activa; si la sucursal no tiene ninguna, la crea (número 1). Si tiene
    pero están todas revocadas, devuelve None y el login se rechaza."""
    terminales = (
        db.query(Terminal)
        .filter_by(sucursal_id=sucursal.id)
        .order_by(Terminal.numero_terminal)
        .all()
    )
    for t in terminales:
        if t.activa:
            return t
    if terminales:
        return None
    t = Terminal(
        sucursal_id=sucursal.id,
        numero_terminal=1,
        serial_sunmi=f"APP-{sucursal.codigo}",
        activa=True,
    )
    db.add(t)
    db.flush()
    return t


# --------------------------------------------------------------------- venta
def _tabla_vigente(db, tipo_id, momento):
    filas = (
        db.query(TablaPagos)
        .filter(
            TablaPagos.tipo_jugada_id == tipo_id,
            TablaPagos.vigente_desde <= momento,
            (TablaPagos.vigente_hasta.is_(None)) | (TablaPagos.vigente_hasta > momento),
        )
        .all()
    )
    return {f.clave: D(f.factor) for f in filas}


def _verificar_sorteo_abierto(sorteo, momento):
    if sorteo is None:
        raise ErrorServicio(400, "El sorteo indicado no existe")
    if not sorteo.activo:
        raise ErrorServicio(400, f"El sorteo {sorteo.nombre} está inactivo")
    dias = {d.strip() for d in (sorteo.dias_activos or "").split(",") if d.strip()}
    if str(momento.isoweekday()) not in dias:
        raise ErrorServicio(400, f"El sorteo {sorteo.nombre} no juega hoy")
    if momento.time() >= sorteo.hora_cierre:
        raise ErrorServicio(400, f"El sorteo {sorteo.nombre} ya cerró (cierre {sorteo.hora_cierre.strftime('%H:%M')})")
    return sorteo


def _parse_numeros(codigo_tipo, numeros):
    partes = [p for p in str(numeros).replace(" ", "").split("-") if p != ""]
    try:
        nums = [int(p) for p in partes]
    except ValueError:
        raise ErrorServicio(400, f"Números inválidos: «{numeros}»")
    for n in nums:
        if n < 0 or n > 99:
            raise ErrorServicio(400, "Cada número debe estar entre 00 y 99")
    if codigo_tipo == "QN":
        if len(nums) != 1:
            raise ErrorServicio(400, "La quiniela lleva un solo número")
        return nums[0], None
    if len(nums) != 2:
        raise ErrorServicio(400, "Esta jugada lleva dos números (ej. 26-58)")
    if nums[0] == nums[1]:
        raise ErrorServicio(400, "Los dos números de la pareja deben ser diferentes")
    return nums[0], nums[1]


def clave_numero(n1, n2):
    if n2 is None:
        return f"{n1:02d}"
    a, b = sorted([n1, n2])
    return f"{a:02d}-{b:02d}"


def vender(db, terminal, operador, jugadas_in, ahora=None, operacion_id=None):
    """Vende un ticket completo. Modelo de CAJA (2026-11-14): vender NO
    exige saldo — la cajera cobra en efectivo y cada venta SUMA a la caja
    de la sucursal. Valida todo antes de crear nada; si algo falla, no hay
    venta ni número consumido. Con operacion_id, un reenvío de la misma
    operación devuelve el ticket ya creado (nunca duplica la venta)."""
    ahora = ahora or ahora_local()
    fecha = ahora.date()
    consorcio = db.query(Consorcio).first()
    sucursal = db.get(Sucursal, terminal.sucursal_id)
    if sucursal is None or not sucursal.activa:
        raise ErrorServicio(403, "La sucursal de esta terminal está inactiva")
    if operacion_id:
        previo = db.query(Ticket).filter_by(operacion_id=str(operacion_id)).first()
        if previo is not None:
            if previo.terminal_id != terminal.id:
                raise ErrorServicio(409, "Esa operación ya fue registrada por otra terminal")
            return ticket_a_dict(db, previo, saldo_restante=D(sucursal.saldo_actual))
    if not jugadas_in:
        raise ErrorServicio(400, "El ticket no tiene jugadas")

    expandidas = []
    total = D(0)
    for entrada in jugadas_in:
        tipo = db.query(TipoJugada).filter_by(codigo=str(entrada["tipo"]).upper()).first()
        if tipo is None or not tipo.activo:
            raise ErrorServicio(400, f"Tipo de jugada no válido o inactivo: {entrada['tipo']}")
        n1, n2 = _parse_numeros(tipo.codigo, entrada["numeros"])
        monto = D(entrada["monto"])
        if monto < D(consorcio.monto_min_jugada):
            raise ErrorServicio(400, f"El monto mínimo por jugada es ${D(consorcio.monto_min_jugada)}")
        if monto > D(consorcio.monto_max_jugada):
            raise ErrorServicio(400, f"El monto máximo por jugada es ${D(consorcio.monto_max_jugada)}")
        factores = _tabla_vigente(db, tipo.id, ahora)
        faltan = [c for c in CLAVES_REQUERIDAS[tipo.codigo] if c not in factores]
        if faltan:
            raise ErrorServicio(
                409,
                f"La tabla de pagos está incompleta para {tipo.codigo} (faltan: {', '.join(faltan)}). "
                "El consorcio debe completarla en el panel.",
            )
        sorteo_ids = entrada.get("sorteos") or []
        if tipo.codigo == "SP":
            if len(sorteo_ids) != 2:
                raise ErrorServicio(400, "El Súper Palé requiere exactamente dos loterías")
            s1 = _verificar_sorteo_abierto(db.get(Sorteo, sorteo_ids[0]), ahora)
            s2 = _verificar_sorteo_abierto(db.get(Sorteo, sorteo_ids[1]), ahora)
            if s1.id == s2.id:
                raise ErrorServicio(400, "El Súper Palé debe cruzar dos loterías diferentes")
            expandidas.append({"tipo": tipo, "sorteo": s1, "sorteo2": s2, "n1": n1, "n2": n2,
                               "monto": monto, "factores": factores})
            total += monto
        else:
            if not sorteo_ids:
                raise ErrorServicio(400, "Cada jugada necesita al menos una lotería seleccionada (DISP)")
            for sid in sorteo_ids:
                s = _verificar_sorteo_abierto(db.get(Sorteo, sid), ahora)
                expandidas.append({"tipo": tipo, "sorteo": s, "sorteo2": None, "n1": n1, "n2": n2,
                                   "monto": monto, "factores": factores})
                total += monto

    # Límites por número (acumulado del día, contando este mismo ticket)
    acumulado = {}
    for e in expandidas:
        clave = clave_numero(e["n1"], e["n2"])
        limite = (
            db.query(LimiteVenta)
            .filter_by(sorteo_id=e["sorteo"].id, tipo_jugada_id=e["tipo"].id, clave_numero=clave)
            .first()
        )
        if limite is None:
            continue
        ya_vendido = (
            db.query(func.coalesce(func.sum(Jugada.monto), 0))
            .join(Ticket)
            .filter(
                Jugada.sorteo_id == e["sorteo"].id,
                Jugada.tipo_jugada_id == e["tipo"].id,
                Jugada.numeros == clave,
                Jugada.fecha == fecha,
                Ticket.estado != "anulado",
            )
            .scalar()
        )
        llave = (e["sorteo"].id, e["tipo"].id, clave)
        nuevo = D(ya_vendido) + acumulado.get(llave, D(0)) + e["monto"]
        if nuevo > D(limite.monto_max_acumulado):
            raise ErrorServicio(
                409,
                f"Límite alcanzado para el número {clave} en {e['sorteo'].nombre}: "
                f"el máximo acumulado es ${D(limite.monto_max_acumulado)}",
            )
        acumulado[llave] = acumulado.get(llave, D(0)) + e["monto"]

    # Consecutivo GLOBAL del consorcio (incremento atómico dentro de la venta)
    db.execute(
        update(Consorcio)
        .where(Consorcio.id == consorcio.id)
        .values(siguiente_ticket=Consorcio.siguiente_ticket + 1)
    )
    db.flush()
    nuevo_id = db.query(Consorcio.siguiente_ticket).filter_by(id=consorcio.id).scalar() - 1

    serial = generar_serial()
    while db.query(Ticket).filter_by(serial=serial).first() is not None:
        serial = generar_serial()

    ticket = Ticket(
        id=nuevo_id,
        serial=serial,
        sucursal_vendedora_id=sucursal.id,
        terminal_id=terminal.id,
        usuario_id=operador.id,
        vendido_en=ahora,
        operacion_id=str(operacion_id) if operacion_id else None,
        fecha=fecha,
        total=total,
        estado="vendido",
        premio_total=D(0),
    )
    db.add(ticket)
    db.flush()
    for e in expandidas:
        db.add(
            Jugada(
                ticket_id=ticket.id,
                tipo_jugada_id=e["tipo"].id,
                sorteo_id=e["sorteo"].id,
                sorteo2_id=e["sorteo2"].id if e["sorteo2"] else None,
                fecha=fecha,
                numeros=clave_numero(e["n1"], e["n2"]),
                n1=e["n1"],
                n2=e["n2"],
                monto=e["monto"],
                factores_json=json.dumps({k: str(v) for k, v in e["factores"].items()}),
            )
        )
    sucursal.saldo_actual = D(sucursal.saldo_actual) + total
    db.add(
        MovimientoSaldo(
            sucursal_id=sucursal.id,
            tipo="venta",
            monto=total,
            referencia=f"Ticket {ticket.id}",
            saldo_resultante=sucursal.saldo_actual,
            creado_por=operador.id,
        )
    )
    auditar(db, "ticket", ticket.id, "venta", usuario_id=operador.id, terminal_id=terminal.id,
            detalle={"total": str(total), "jugadas": len(expandidas), "sucursal": sucursal.codigo})
    db.commit()
    db.refresh(ticket)
    return ticket_a_dict(db, ticket, saldo_restante=D(sucursal.saldo_actual))


# ------------------------------------------------------- consulta/pago/anula
def buscar_ticket(db, ticket_id, serial):
    ticket = db.get(Ticket, int(ticket_id)) if str(ticket_id).isdigit() else None
    if ticket is None or ticket.serial != str(serial or "").strip().upper():
        raise ErrorServicio(404, "Ticket no encontrado: verifique el ID y el Serial del ticket")
    return ticket


def ticket_a_dict(db, ticket, saldo_restante=None):
    jugadas = []
    for j in ticket.jugadas:
        loterias = [j.sorteo.nombre if j.sorteo else "?"]
        if j.sorteo2 is not None:
            loterias.append(j.sorteo2.nombre)
        jugadas.append(
            {
                "tipo": j.tipo.codigo if j.tipo else "?",
                "tipo_nombre": j.tipo.nombre if j.tipo else "?",
                "loterias": loterias,
                "numeros": j.numeros,
                "monto": str(D(j.monto)),
                "evaluada": bool(j.evaluada),
                "premio": str(D(j.premio)) if j.premio is not None else None,
                "detalle_eval": j.detalle_eval,
            }
        )
    datos = {
        "id": ticket.id,
        "serial": ticket.serial,
        "qr": f"LOT:{ticket.id}:{ticket.serial}",
        "banca": ticket.sucursal_vendedora.nombre if ticket.sucursal_vendedora else "?",
        "banca_codigo": ticket.sucursal_vendedora.codigo if ticket.sucursal_vendedora else "?",
        "terminal_serial": ticket.terminal.serial_sunmi if ticket.terminal else None,
        "terminal_numero": ticket.terminal.numero_terminal if ticket.terminal else None,
        "fecha_hora": ticket.vendido_en.isoformat(sep=" ") if ticket.vendido_en else None,
        "fecha": ticket.fecha.isoformat() if ticket.fecha else None,
        "jugadas": jugadas,
        "total": str(D(ticket.total)),
        "estado": ticket.estado,
        "premio_total": str(D(ticket.premio_total)),
    }
    if ticket.estado == "pagado":
        datos["pago"] = {
            "sucursal": ticket.sucursal_pago.nombre if ticket.sucursal_pago else "?",
            "sucursal_codigo": ticket.sucursal_pago.codigo if ticket.sucursal_pago else "?",
            "fecha_hora": ticket.pagado_en.isoformat(sep=" ") if ticket.pagado_en else None,
            "monto": str(D(ticket.premio_total)),
        }
    if saldo_restante is not None:
        datos["saldo_restante"] = str(D(saldo_restante))
    return datos


def consultar_ticket(db, ticket_id, serial):
    ticket = buscar_ticket(db, ticket_id, serial)
    datos = ticket_a_dict(db, ticket)
    datos["puede_pagar"] = ticket.estado == "ganador"
    if ticket.estado == "ganador":
        datos["mensaje"] = f"Ticket ganador: pague ${D(ticket.premio_total)}"
    elif ticket.estado == "pagado":
        p = datos["pago"]
        datos["mensaje"] = (
            f"Ya pagado en la sucursal {p['sucursal']}, el día {p['fecha_hora']}"
        )
    elif ticket.estado == "no_ganador":
        datos["mensaje"] = "El ticket no ganó"
    elif ticket.estado == "anulado":
        datos["mensaje"] = "El ticket está anulado"
    elif ticket.estado == "vencido":
        datos["mensaje"] = "El ticket está vencido"
    else:
        datos["mensaje"] = "Ticket vendido: aún faltan resultados por liquidar"
    return datos


def _error_no_pagable(db, ticket):
    """El error exacto según el estado de un ticket que no está ganador."""
    if ticket.estado == "pagado":
        p = ticket_a_dict(db, ticket)["pago"]
        raise ErrorServicio(
            409,
            f"Ya pagado en la sucursal {p['sucursal']}, el día {p['fecha_hora']}. No se puede pagar dos veces.",
        )
    if ticket.estado == "anulado":
        raise ErrorServicio(409, "El ticket está anulado: no se puede pagar")
    if ticket.estado == "no_ganador":
        raise ErrorServicio(409, "El ticket no ganó: no hay premio que pagar")
    if ticket.estado == "vencido":
        raise ErrorServicio(409, "El ticket está vencido: no se puede pagar")
    raise ErrorServicio(409, "El ticket aún no es ganador: faltan resultados por liquidar")


def pagar_ticket(db, ticket_id, serial, sucursal_pagadora_id, terminal_id, usuario_id):
    """Pago ÚNICO atómico: la transición ganador->pagado es una sola
    actualización condicionada al estado. Dos intentos a la vez = un pago.
    Modelo de CAJA: el premio sale de la caja de la sucursal que paga y se
    descuenta al pagarse (los pendientes no descuentan). Si la caja no
    alcanza, el pago se BLOQUEA con advertencia, el premio queda pendiente
    y el intento queda en auditoría: el consorcio debe entregar efectivo a
    la sucursal para poder pagarlo."""
    ticket = buscar_ticket(db, ticket_id, serial)
    if ticket.estado != "ganador":
        _error_no_pagable(db, ticket)
    sucursal = db.get(Sucursal, sucursal_pagadora_id)
    premio = D(ticket.premio_total)
    caja = D(sucursal.saldo_actual) if sucursal is not None else D(0)
    if caja < premio:
        auditar(db, "ticket", ticket.id, "pago_bloqueado", usuario_id=usuario_id,
                terminal_id=terminal_id,
                detalle={"motivo": "caja_insuficiente", "premio": str(premio),
                         "caja": str(caja), "sucursal_pagadora": sucursal_pagadora_id})
        db.commit()
        raise ErrorServicio(
            409,
            f"Advertencia: la caja de esta sucursal tiene ${caja} y el premio es ${premio}. "
            "No se pagó: el premio queda pendiente hasta que el consorcio entregue "
            "efectivo a la sucursal.",
        )
    ahora = ahora_local()
    filas = (
        db.execute(
            update(Ticket)
            .where(Ticket.id == ticket.id, Ticket.estado == "ganador")
            .values(
                estado="pagado",
                pagado_en_sucursal_id=sucursal_pagadora_id,
                pagado_por_terminal_id=terminal_id,
                pagado_por_usuario_id=usuario_id,
                pagado_en=ahora,
            )
        ).rowcount
        or 0
    )
    if filas != 1:
        db.rollback()
        db.expire_all()
        _error_no_pagable(db, buscar_ticket(db, ticket_id, serial))
    sucursal.saldo_actual = caja - premio
    db.add(
        MovimientoSaldo(
            sucursal_id=sucursal.id,
            tipo="pago_premio",
            monto=premio,
            referencia=f"Pago ticket {ticket.id}",
            saldo_resultante=sucursal.saldo_actual,
            creado_por=usuario_id,
        )
    )
    auditar(db, "ticket", ticket.id, "pago", usuario_id=usuario_id, terminal_id=terminal_id,
            detalle={"monto": str(premio), "sucursal_pagadora": sucursal_pagadora_id})
    db.commit()
    db.expire_all()
    return consultar_ticket(db, ticket_id, serial)


def anular_ticket(db, ticket_id, serial, usuario_id, terminal_id=None, ahora=None):
    ahora = ahora or ahora_local()
    ticket = buscar_ticket(db, ticket_id, serial)
    if ticket.estado == "anulado":
        raise ErrorServicio(409, "El ticket ya está anulado")
    if ticket.estado == "pagado":
        datos = ticket_a_dict(db, ticket)
        p = datos["pago"]
        raise ErrorServicio(409, f"El ticket ya fue pagado en la sucursal {p['sucursal']} el {p['fecha_hora']}")
    if ticket.estado in ("ganador", "no_ganador", "vencido"):
        raise ErrorServicio(409, "Ya no se puede anular: los sorteos de este ticket ya cerraron")
    for j in ticket.jugadas:
        for s in (j.sorteo, j.sorteo2):
            if s is None:
                continue
            if j.fecha < ahora.date() or (j.fecha == ahora.date() and ahora.time() >= s.hora_cierre):
                raise ErrorServicio(409, f"No se puede anular: el sorteo {s.nombre} ya cerró")
    ticket.estado = "anulado"
    ticket.anulado_en = ahora
    ticket.anulado_por = usuario_id
    sucursal = db.get(Sucursal, ticket.sucursal_vendedora_id)
    sucursal.saldo_actual = D(sucursal.saldo_actual) - D(ticket.total)
    db.add(
        MovimientoSaldo(
            sucursal_id=sucursal.id,
            tipo="anulacion",
            monto=D(ticket.total),
            referencia=f"Anulación ticket {ticket.id}",
            saldo_resultante=sucursal.saldo_actual,
            creado_por=usuario_id,
        )
    )
    auditar(db, "ticket", ticket.id, "anulacion", usuario_id=usuario_id, terminal_id=terminal_id,
            detalle={"total_devuelto": str(D(ticket.total))})
    db.commit()
    db.refresh(ticket)
    return ticket_a_dict(db, ticket, saldo_restante=D(sucursal.saldo_actual))


# ---------------------------------------------------------------- resultados
def guardar_resultado(db, sorteo_id, fecha, p1, p2, p3, usuario, fuente="manual"):
    """Crea o corrige un resultado en estado PROPUESTO. Nunca toca uno
    confirmado/liquidado: para corregirlo hay que revertirlo primero."""
    sorteo = db.get(Sorteo, sorteo_id)
    if sorteo is None:
        raise ErrorServicio(404, "El sorteo no existe")
    numeros = [p1, p2, p3]
    for n in numeros:
        if n is None or int(n) < 0 or int(n) > 99:
            raise ErrorServicio(400, "Cada premio debe ser un número entre 00 y 99")
    if len(set(int(n) for n in numeros)) != 3:
        raise ErrorServicio(400, "Los tres premios deben ser números diferentes")
    r = db.query(Resultado).filter_by(sorteo_id=sorteo_id, fecha=fecha).first()
    if r is not None and r.estado in ("confirmado", "liquidado"):
        raise ErrorServicio(
            409,
            "Este resultado ya fue confirmado/liquidado. Para corregirlo, primero revierta la liquidación.",
        )
    if r is None:
        r = Resultado(sorteo_id=sorteo_id, fecha=fecha, estado="propuesto")
        db.add(r)
    r.premio1, r.premio2, r.premio3 = (int(n) for n in numeros)
    r.fuente = fuente
    r.propuesto_por = usuario.id
    r.propuesto_en = ahora_local()
    auditar(db, "resultado", r.id or f"{sorteo_id}-{fecha}", "registro_resultado",
            usuario_id=usuario.id,
            detalle={"sorteo": sorteo.nombre, "fecha": str(fecha),
                     "numeros": [f"{int(n):02d}" for n in numeros], "fuente": fuente})
    db.commit()
    db.refresh(r)
    return r


def confirmar_resultado(db, resultado_id, usuario):
    """Confirmar = liquidar en la misma operación: el motor evalúa QN/PL/SP
    y marca cada ticket. El resultado queda en estado LIQUIDADO."""
    r = db.get(Resultado, resultado_id)
    if r is None:
        raise ErrorServicio(404, "El resultado no existe")
    if r.estado == "liquidado":
        raise ErrorServicio(409, "Este resultado ya fue confirmado y liquidado")
    ahora = ahora_local()
    r.estado = "confirmado"
    r.confirmado_por = usuario.id
    r.confirmado_en = ahora
    auditar(db, "resultado", r.id, "confirmacion", usuario_id=usuario.id,
            detalle={"sorteo": r.sorteo.nombre, "fecha": str(r.fecha)})
    afectados = motor.liquidar_resultado(db, r)
    r.estado = "liquidado"
    r.liquidado_en = ahora_local()
    auditar(db, "resultado", r.id, "liquidacion", usuario_id=usuario.id,
            detalle={"tickets_afectados": afectados})
    db.commit()
    db.refresh(r)
    return r, afectados


def revertir_resultado(db, resultado_id, usuario):
    r = db.get(Resultado, resultado_id)
    if r is None:
        raise ErrorServicio(404, "El resultado no existe")
    if r.estado != "liquidado":
        raise ErrorServicio(409, "Solo se puede revertir un resultado ya liquidado")
    afectados = motor.revertir_liquidacion(db, r)
    r.estado = "propuesto"
    r.liquidado_en = None
    auditar(db, "resultado", r.id, "reversion", usuario_id=usuario.id,
            detalle={"tickets_afectados": afectados})
    db.commit()
    db.refresh(r)
    return r, afectados


def resultado_a_dict(r):
    return {
        "id": r.id,
        "sorteo_id": r.sorteo_id,
        "sorteo": r.sorteo.nombre if r.sorteo else "?",
        "fecha": r.fecha.isoformat(),
        "premio1": f"{r.premio1:02d}",
        "premio2": f"{r.premio2:02d}",
        "premio3": f"{r.premio3:02d}",
        "estado": r.estado,
        "fuente": r.fuente,
        "confirmado_en": r.confirmado_en.isoformat(sep=" ") if r.confirmado_en else None,
        "liquidado_en": r.liquidado_en.isoformat(sep=" ") if r.liquidado_en else None,
    }


# -------------------------------------------------------------------- saldos
def recargar_saldo(db, sucursal_id, monto, referencia, usuario):
    monto = D(monto)
    if monto <= 0:
        raise ErrorServicio(400, "El monto de la recarga debe ser mayor que cero")
    sucursal = db.get(Sucursal, sucursal_id)
    if sucursal is None:
        raise ErrorServicio(404, "La sucursal no existe")
    sucursal.saldo_actual = D(sucursal.saldo_actual) + monto
    mov = MovimientoSaldo(
        sucursal_id=sucursal.id,
        tipo="recarga",
        monto=monto,
        referencia=referencia or "Recarga del consorcio",
        saldo_resultante=sucursal.saldo_actual,
        creado_por=usuario.id,
    )
    db.add(mov)
    auditar(db, "sucursal", sucursal.id, "recarga_saldo", usuario_id=usuario.id,
            detalle={"monto": str(monto), "saldo_resultante": str(sucursal.saldo_actual)})
    db.commit()
    db.refresh(mov)
    return mov


# ---------------------------------------------------------------------- caja
def registrar_caja(db, tipo, monto, concepto, sucursal_id, terminal_id, usuario_id):
    monto = D(monto)
    if monto <= 0:
        raise ErrorServicio(400, "El monto debe ser mayor que cero")
    if tipo not in ("recibir_efectivo", "gasto"):
        raise ErrorServicio(400, "Tipo de movimiento de caja no válido")
    if tipo == "gasto" and not (concepto and concepto.strip()):
        raise ErrorServicio(400, "El gasto requiere un concepto obligatorio")
    tx = TransaccionCaja(
        sucursal_id=sucursal_id,
        terminal_id=terminal_id,
        usuario_id=usuario_id,
        tipo=tipo,
        monto=monto,
        concepto=(concepto or "").strip(),
        fecha=ahora_local().date(),
    )
    db.add(tx)
    sucursal = db.get(Sucursal, sucursal_id)
    if sucursal is not None:
        if tipo == "recibir_efectivo":
            sucursal.saldo_actual = D(sucursal.saldo_actual) + monto
        else:  # gasto
            sucursal.saldo_actual = D(sucursal.saldo_actual) - monto
        db.add(
            MovimientoSaldo(
                sucursal_id=sucursal.id,
                tipo=tipo,
                monto=monto,
                referencia=tx.concepto or tipo,
                saldo_resultante=sucursal.saldo_actual,
                creado_por=usuario_id,
            )
        )
    auditar(db, "caja", tx.id or "nueva", "registro_caja", usuario_id=usuario_id,
            terminal_id=terminal_id,
            detalle={"tipo": tipo, "monto": str(monto), "concepto": tx.concepto})
    db.commit()
    db.refresh(tx)
    return tx


def _suma(db, columna, filtros):
    return D(db.query(func.coalesce(func.sum(columna), 0)).filter(*filtros).scalar())


def entregar_cuadre(db, sucursal_id, terminal_id, usuario_id, fecha=None, efectivo_contado=None):
    """Cuadre del día: ventas − premios pagados − gastos + efectivo recibido.
    La diferencia entre lo contado y lo esperado queda registrada tal cual."""
    fecha = fecha or ahora_local().date()
    q = db.query(Cuadre).filter(Cuadre.fecha == fecha, Cuadre.sucursal_id == sucursal_id)
    q = q.filter(Cuadre.terminal_id == terminal_id) if terminal_id else q.filter(Cuadre.terminal_id.is_(None))
    if q.first() is not None:
        raise ErrorServicio(409, "Ya se entregó el cuadre de esta terminal/sucursal para esa fecha")

    f_ventas = [Ticket.fecha == fecha, Ticket.estado != "anulado"]
    f_premios = [Ticket.estado == "pagado", func.date(Ticket.pagado_en) == fecha]
    f_caja = [TransaccionCaja.fecha == fecha]
    if terminal_id:
        f_ventas.append(Ticket.terminal_id == terminal_id)
        f_premios.append(Ticket.pagado_por_terminal_id == terminal_id)
        f_caja.append(TransaccionCaja.terminal_id == terminal_id)
    else:
        f_ventas.append(Ticket.sucursal_vendedora_id == sucursal_id)
        f_premios.append(Ticket.pagado_en_sucursal_id == sucursal_id)
        f_caja.append(TransaccionCaja.sucursal_id == sucursal_id)

    ventas = _suma(db, Ticket.total, f_ventas)
    premios = _suma(db, Ticket.premio_total, f_premios)
    gastos = _suma(db, TransaccionCaja.monto, f_caja + [TransaccionCaja.tipo == "gasto"])
    recibidos = _suma(db, TransaccionCaja.monto, f_caja + [TransaccionCaja.tipo == "recibir_efectivo"])
    total_a_entregar = D(ventas - premios - gastos + recibidos)
    diferencia = None
    if efectivo_contado is not None:
        diferencia = D(D(efectivo_contado) - total_a_entregar)

    cuadre = Cuadre(
        sucursal_id=sucursal_id,
        terminal_id=terminal_id,
        fecha=fecha,
        ventas_total=ventas,
        premios_pagados_total=premios,
        gastos_total=gastos,
        efectivo_recibido_total=recibidos,
        total_a_entregar=total_a_entregar,
        efectivo_contado=D(efectivo_contado) if efectivo_contado is not None else None,
        diferencia=diferencia,
        entregado_por=usuario_id,
    )
    db.add(cuadre)
    db.flush()
    db.add(
        TransaccionCaja(
            sucursal_id=sucursal_id,
            terminal_id=terminal_id,
            usuario_id=usuario_id,
            tipo="entrega_cuadre",
            monto=total_a_entregar,
            concepto="Entrega de cuadre",
            fecha=fecha,
        )
    )
    sucursal = db.get(Sucursal, sucursal_id)
    if sucursal is not None:
        sucursal.saldo_actual = D(sucursal.saldo_actual) - D(total_a_entregar)
        db.add(
            MovimientoSaldo(
                sucursal_id=sucursal.id,
                tipo="entrega_cuadre",
                monto=abs(D(total_a_entregar)),
                referencia=f"Cuadre {fecha}",
                saldo_resultante=sucursal.saldo_actual,
                creado_por=usuario_id,
            )
        )
    auditar(db, "cuadre", cuadre.id, "entrega_cuadre", usuario_id=usuario_id,
            terminal_id=terminal_id,
            detalle={"fecha": str(fecha), "total_a_entregar": str(total_a_entregar),
                     "diferencia": str(diferencia) if diferencia is not None else None})
    db.commit()
    db.refresh(cuadre)
    return cuadre


def cuadre_a_dict(c):
    return {
        "id": c.id,
        "sucursal_id": c.sucursal_id,
        "terminal_id": c.terminal_id,
        "fecha": c.fecha.isoformat(),
        "ventas_total": str(D(c.ventas_total)),
        "premios_pagados_total": str(D(c.premios_pagados_total)),
        "gastos_total": str(D(c.gastos_total)),
        "efectivo_recibido_total": str(D(c.efectivo_recibido_total)),
        "total_a_entregar": str(D(c.total_a_entregar)),
        "efectivo_contado": str(D(c.efectivo_contado)) if c.efectivo_contado is not None else None,
        "diferencia": str(D(c.diferencia)) if c.diferencia is not None else None,
    }


# ------------------------------------------------------------------ reportes
def _tickets_rango(db, desde, hasta, sucursal_id=None):
    q = db.query(Ticket).filter(Ticket.fecha >= desde, Ticket.fecha <= hasta)
    if sucursal_id:
        q = q.filter(Ticket.sucursal_vendedora_id == sucursal_id)
    return q.order_by(Ticket.id).all()


def _ticket_resumen(db, t):
    return {
        "id": t.id,
        "serial": t.serial,
        "banca": t.sucursal_vendedora.nombre if t.sucursal_vendedora else "?",
        "fecha": t.fecha.isoformat(),
        "total": str(D(t.total)),
        "estado": t.estado,
        "premio_total": str(D(t.premio_total)),
        "pago": ticket_a_dict(db, t).get("pago"),
    }


def reporte_resumen(db, desde, hasta, vista, sucursal_id=None):
    tickets = _tickets_rango(db, desde, hasta, sucursal_id)
    base = {"vista": vista, "desde": desde.isoformat(), "hasta": hasta.isoformat()}
    if vista == "final":
        vigentes = [t for t in tickets if t.estado != "anulado"]
        nulos = [t for t in tickets if t.estado == "anulado"]
        ventas = sum((D(t.total) for t in vigentes), D(0))
        premios_pagados = sum((D(t.premio_total) for t in tickets if t.estado == "pagado"), D(0))
        premios_pendientes = sum((D(t.premio_total) for t in tickets if t.estado == "ganador"), D(0))
        comision = D(0)
        for t in vigentes:
            suc = t.sucursal_vendedora
            if suc is not None:
                comision += D(t.total) * D(suc.comision_porcentaje) / D(100)
        base.update(
            {
                "total_tickets": len(tickets),
                "ventas": str(D(ventas)),
                "anulados_cantidad": len(nulos),
                "anulados_monto": str(D(sum((D(t.total) for t in nulos), D(0)))),
                "premios_pagados": str(D(premios_pagados)),
                "premios_pendientes": str(D(premios_pendientes)),
                "neto": str(D(ventas - premios_pagados)),
                "comision_total": str(D(comision)),
            }
        )
        return base
    if vista == "por_loteria":
        filas = {}
        for t in tickets:
            if t.estado == "anulado":
                continue
            for j in t.jugadas:
                nombre = j.sorteo.nombre if j.sorteo else "?"
                fila = filas.setdefault(
                    nombre, {"sorteo": nombre, "jugadas": 0, "ventas": D(0), "premios": D(0)}
                )
                fila["jugadas"] += 1
                fila["ventas"] += D(j.monto)
                if j.evaluada and j.premio is not None:
                    fila["premios"] += D(j.premio)
        base["filas"] = [
            {"sorteo": f["sorteo"], "jugadas": f["jugadas"],
             "ventas": str(D(f["ventas"])), "premios": str(D(f["premios"]))}
            for f in sorted(filas.values(), key=lambda x: x["sorteo"])
        ]
        return base
    if vista == "premios":  # todos los que ganaron (pagados o no)
        elegidos = [t for t in tickets if t.estado in ("ganador", "pagado")]
    elif vista == "ganadores":  # ganadores aún sin pagar
        elegidos = [t for t in tickets if t.estado == "ganador"]
    elif vista == "pagados":
        elegidos = [t for t in tickets if t.estado == "pagado"]
    elif vista == "nulos":
        elegidos = [t for t in tickets if t.estado == "anulado"]
    else:
        raise ErrorServicio(400, f"Vista de reporte no válida: {vista}")
    base["tickets"] = [_ticket_resumen(db, t) for t in elegidos]
    base["cantidad"] = len(elegidos)
    base["monto_total"] = str(D(sum((D(t.premio_total if vista != "nulos" else t.total) for t in elegidos), D(0))))
    return base


def reporte_pendientes(db, desde, hasta, sucursal_id):
    tickets = _tickets_rango(db, desde, hasta, sucursal_id)
    pendientes = [t for t in tickets if t.estado == "ganador"]
    pagados_en_otra = [
        t for t in tickets
        if t.estado == "pagado" and t.pagado_en_sucursal_id not in (None, sucursal_id)
    ]
    pagados = [t for t in tickets if t.estado == "pagado"]
    return {
        "desde": desde.isoformat(),
        "hasta": hasta.isoformat(),
        "sucursal_id": sucursal_id,
        "pendientes": [_ticket_resumen(db, t) for t in pendientes],
        "monto_pendiente": str(D(sum((D(t.premio_total) for t in pendientes), D(0)))),
        "pagados_en_otra": [_ticket_resumen(db, t) for t in pagados_en_otra],
        "pagado_en_otra_monto": str(D(sum((D(t.premio_total) for t in pagados_en_otra), D(0)))),
        "total_pagado": str(D(sum((D(t.premio_total) for t in pagados), D(0)))),
    }


def pendientes_texto(db, desde, hasta, sucursal_id, terminal=None):
    """Formato de texto imprimible en la térmica, como el observado en video 3."""
    sucursal = db.get(Sucursal, sucursal_id)
    rep = reporte_pendientes(db, desde, hasta, sucursal_id)
    ahora = ahora_local()
    lineas = [
        (sucursal.nombre if sucursal else "SUCURSAL").upper(),
        f"DEL DIA => {desde.strftime('%d-%m-%Y')} A {hasta.strftime('%d-%m-%Y')}",
        f"IMPRESO => {ahora.strftime('%d-%m-%Y %I:%M %p')}",
        f"Sucursal=> {sucursal.codigo if sucursal else '?'} "
        f"Terminal: {terminal.numero_terminal if terminal else '-'}",
        "Ticket Pendiente Pago",
        "Ticket | Ganado | Fecha",
    ]
    for t in rep["pendientes"]:
        lineas.append(f"{t['id']} | ${D(t['premio_total']):.2f} | {t['fecha']}")
    total = D(rep["monto_pendiente"]) + D(rep["total_pagado"])
    lineas += [
        f"Monto Pendiente: ${D(rep['monto_pendiente']):.2f}",
        f"Pagado En Otra Suc: ${D(rep['pagado_en_otra_monto']):.2f}",
        f"Total Pagado: ${D(rep['total_pagado']):.2f}",
        f"Total: ${total:.2f}",
    ]
    return "\n".join(lineas)
