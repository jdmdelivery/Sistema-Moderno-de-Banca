"""Servicios centrales: sesiones, terminales, venta, consulta/pago/anulación,
resultados, saldos, caja, cuadre y reportes. Toda regla de negocio vive aquí;
las rutas (main.py) solo traducen HTTP <-> servicio.
"""
import calendar
import json
import uuid
from datetime import datetime, time, timedelta

from sqlalchemy import func, or_, update
from sqlalchemy.exc import IntegrityError

from . import motor
from .comun import D, ErrorServicio, ZONA, ahora_local, modo_desarrollo
from .models import (
    Auditoria,
    Consorcio,
    ComisionCajera,
    CorreccionPendiente,
    Cuadre,
    Jugada,
    LimiteCajera,
    LimiteVenta,
    LiquidacionComision,
    MovimientoCajera,
    MovimientoSaldo,
    Resultado,
    Sesion,
    Sorteo,
    Sucursal,
    TablaPagos,
    Terminal,
    Entrega,
    FondoAsignado,
    Importacion,
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


def terminal_para_dispositivo(db, sucursal, dispositivo_id, modelo=None, android=None, version=None):
    """Cada aparato conserva su propio serial. Sin serial, sigue la terminal
    única de la sucursal, para no romper las sesiones que ya existían."""
    if not dispositivo_id or not str(dispositivo_id).strip():
        terminal = terminal_de_sucursal(db, sucursal)
        _anotar_terminal(terminal, modelo, android, version)
        return terminal
    serial = str(dispositivo_id).strip()[:60]
    todas = (
        db.query(Terminal)
        .filter_by(sucursal_id=sucursal.id)
        .order_by(Terminal.numero_terminal)
        .all()
    )
    propia = db.query(Terminal).filter_by(serial_sunmi=serial).first()
    if propia is not None:
        if propia.sucursal_id != sucursal.id:
            raise ErrorServicio(403, "Este dispositivo ya está registrado en otra sucursal")
        if not propia.activa:
            return None
        _anotar_terminal(propia, modelo, android, version)
        return propia
    activas = [t for t in todas if t.activa]
    if todas and not activas:
        return None
    if len(activas) == 1 and str(activas[0].serial_sunmi).startswith("APP-"):
        activas[0].serial_sunmi = serial
        _anotar_terminal(activas[0], modelo, android, version)
        return activas[0]
    numero = max((t.numero_terminal for t in todas), default=0) + 1
    nueva = Terminal(
        sucursal_id=sucursal.id,
        numero_terminal=numero,
        serial_sunmi=serial,
        activa=True,
    )
    db.add(nueva)
    db.flush()
    _anotar_terminal(nueva, modelo, android, version)
    return nueva


def _anotar_terminal(terminal, modelo, android, version):
    if terminal is None:
        return
    terminal.ultima_conexion_en = ahora_local()
    if modelo:
        terminal.modelo = str(modelo)[:80]
    if android:
        terminal.android_api = str(android)[:10]
    if version:
        terminal.version_app = str(version)[:30]


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


APERTURA_VENTAS = time(6, 0)
AVISO_CIERRE_SEGUNDOS = 5 * 60


def estado_sorteo(sorteo, momento):
    """El servidor decide si se puede vender. El reloj del teléfono no cuenta."""
    if sorteo is None:
        return {"estado": "cerrada", "abierto": False, "motivo": "El sorteo indicado no existe",
                "segundos_para_cierre": None}
    if not sorteo.activo:
        return {"estado": "cerrada", "abierto": False,
                "motivo": f"El sorteo {sorteo.nombre} está inactivo",
                "segundos_para_cierre": None}
    dias = {d.strip() for d in (sorteo.dias_activos or "").split(",") if d.strip()}
    if str(momento.isoweekday()) not in dias:
        return {"estado": "cerrada", "abierto": False,
                "motivo": f"El sorteo {sorteo.nombre} no juega hoy",
                "segundos_para_cierre": None}
    if momento.time() < APERTURA_VENTAS:
        return {"estado": "cerrada", "abierto": False,
                "motivo": "Las ventas abren a las 6:00 AM",
                "segundos_para_cierre": None}
    cierre = datetime.combine(momento.date(), sorteo.hora_cierre)
    segundos = int((cierre - momento).total_seconds())
    if segundos <= 0:
        return {
            "estado": "cerrada",
            "abierto": False,
            "motivo": (
                f"El sorteo {sorteo.nombre} ya cerró "
                f"(cierre {sorteo.hora_cierre.strftime('%H:%M')}). Vuelve a abrir a las 6:00 AM."
            ),
            "segundos_para_cierre": 0,
        }
    return {
        "estado": "proxima" if segundos <= AVISO_CIERRE_SEGUNDOS else "abierta",
        "abierto": True,
        "motivo": "",
        "segundos_para_cierre": segundos,
    }


def _verificar_sorteo_abierto(sorteo, momento):
    info = estado_sorteo(sorteo, momento)
    if not info["abierto"]:
        raise ErrorServicio(400, info["motivo"])
    return sorteo


def _parse_numeros(codigo_tipo, numeros):
    partes = [p for p in str(numeros).replace(" ", "").split("-") if p != ""]
    if codigo_tipo != "QN" and len(partes) == 1 and len(partes[0]) == 4 and partes[0].isdigit():
        partes = [partes[0][:2], partes[0][2:]]
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
    return nums[0], nums[1]


def clave_numero(n1, n2):
    if n2 is None:
        return f"{n1:02d}"
    a, b = sorted([n1, n2])
    return f"{a:02d}-{b:02d}"


TODAS_LAS_LOTERIAS = 0
CUALQUIER_NUMERO = "*"


def _acumulado_numero(db, sorteo_id, tipo_id, clave, fecha, usuario_id=None):
    consulta = (
        db.query(func.coalesce(func.sum(Jugada.monto), 0))
        .join(Ticket)
        .filter(
            Jugada.sorteo_id == sorteo_id,
            Jugada.tipo_jugada_id == tipo_id,
            Jugada.numeros == clave,
            Jugada.fecha == fecha,
            Ticket.estado != "anulado",
            Ticket.es_prueba.is_(False),
        )
    )
    if usuario_id is not None:
        consulta = consulta.filter(Ticket.usuario_id == usuario_id)
    return D(consulta.scalar())


def _revisar_tope(nombre, clave, sorteo, tope, ya, extra):
    if tope is None:
        return
    if D(ya) + D(extra) > D(tope):
        raise ErrorServicio(
            409,
            f"{nombre} para el número {clave} en {sorteo}: el máximo acumulado es ${D(tope)}",
        )


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
            return ticket_a_dict(db, previo)
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

    # El tope general y el de la cajera se revisan por número, lotería y fecha.
    # El más bajo de los dos bloquea. Un tope de "todos" aplica a cada número por separado.
    acumulado_general = {}
    acumulado_cajera = {}
    for e in expandidas:
        clave = clave_numero(e["n1"], e["n2"])
        llave = (e["sorteo"].id, e["tipo"].id, clave)
        general = (
            db.query(LimiteVenta)
            .filter_by(sorteo_id=e["sorteo"].id, tipo_jugada_id=e["tipo"].id, clave_numero=clave)
            .with_for_update()
            .first()
        )
        if general is not None:
            ya = _acumulado_numero(db, e["sorteo"].id, e["tipo"].id, clave, fecha)
            extra = acumulado_general.get(llave, D(0)) + e["monto"]
            _revisar_tope("Límite alcanzado", clave, e["sorteo"].nombre, general.monto_max_acumulado, ya, extra)
            acumulado_general[llave] = extra
        propios = (
            db.query(LimiteCajera)
            .filter(
                LimiteCajera.usuario_id == operador.id,
                LimiteCajera.tipo_jugada_id == e["tipo"].id,
                LimiteCajera.sorteo_id.in_([e["sorteo"].id, TODAS_LAS_LOTERIAS]),
                LimiteCajera.clave_numero.in_([clave, CUALQUIER_NUMERO]),
            )
            .order_by(LimiteCajera.id)
            .with_for_update()
            .all()
        )
        if propios:
            tope = min(propios, key=lambda fila: D(fila.monto_max_acumulado))
            ya = _acumulado_numero(db, e["sorteo"].id, e["tipo"].id, clave, fecha, operador.id)
            extra = acumulado_cajera.get(llave, D(0)) + e["monto"]
            _revisar_tope(
                "Límite de la cajera alcanzado", clave, e["sorteo"].nombre,
                tope.monto_max_acumulado, ya, extra,
            )
            acumulado_cajera[llave] = extra

    # El cierre se vuelve a leer en esta misma transacción, antes de consumir
    # un número de ticket. Si uno de los sorteos ya cerró, no se guarda nada.
    momento_cierre = ahora_local()
    if momento_cierre.date() != fecha:
        raise ErrorServicio(400, "La venta no se completó: cambió el día de operación. No se guardó el ticket.")
    for e in expandidas:
        _verificar_sorteo_abierto(e["sorteo"], momento_cierre)
        if e["sorteo2"] is not None:
            _verificar_sorteo_abierto(e["sorteo2"], momento_cierre)

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

    prueba = modo_desarrollo()
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
        es_prueba=prueba,
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
    if not prueba:
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
        mover_caja_cajera(db, operador.id, sucursal.id, "venta", total, f"Ticket {ticket.id}", 1)
    else:
        mover_caja_cajera(
            db, operador.id, sucursal.id, "venta_prueba", total, f"Ticket de prueba {ticket.id}", 1,
            bolsa="prueba",
        )
    auditar(db, "ticket", ticket.id, "venta", usuario_id=operador.id, terminal_id=terminal.id,
            detalle={"total": str(total), "jugadas": len(expandidas), "sucursal": sucursal.codigo,
                     "es_prueba": prueba})
    db.commit()
    db.refresh(ticket)
    return ticket_a_dict(db, ticket)


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
                "pagada": bool(j.pagada) or ticket.estado == "pagado",
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
        "es_prueba": bool(ticket.es_prueba),
        "reimpresiones": int(ticket.reimpresiones or 0),
        "cajero": db.get(Usuario, ticket.usuario_id).nombre if ticket.usuario_id and db.get(Usuario, ticket.usuario_id) else "",
    }
    if ticket.estado == "pagado":
        pagador = db.get(Usuario, ticket.pagado_por_usuario_id) if ticket.pagado_por_usuario_id else None
        datos["pago"] = {
            "sucursal": ticket.sucursal_pago.nombre if ticket.sucursal_pago else "?",
            "sucursal_codigo": ticket.sucursal_pago.codigo if ticket.sucursal_pago else "?",
            "fecha_hora": ticket.pagado_en.isoformat(sep=" ") if ticket.pagado_en else None,
            "monto": str(D(ticket.premio_total)),
            "operacion_id": ticket.pago_operacion_id or str(ticket.id),
            "cajero": pagador.nombre if pagador else "",
            "cajero_id": ticket.pagado_por_usuario_id,
        }
        datos["comprobante"] = comprobante_premio(db, ticket)
    if saldo_restante is not None:
        datos["saldo_restante"] = str(D(saldo_restante))
    return datos


def _numero_oficial(db, sorteo_id, fecha):
    fila = db.query(Resultado).filter_by(sorteo_id=sorteo_id, fecha=fecha).first()
    if fila is None or fila.estado == "error_fuente":
        return None
    return f"{int(fila.premio1):02d}-{int(fila.premio2):02d}-{int(fila.premio3):02d}", fila.fuente


def _premio_ya_cobrado(jugada, ticket):
    if not jugada.evaluada or jugada.premio is None or D(jugada.premio) <= 0:
        return False
    return bool(jugada.pagada) or ticket.estado == "pagado"


def _linea_premio(db, ticket, jugada):
    codigo = jugada.tipo.codigo if jugada.tipo else ""
    tipo = _NOMBRE_JUGADA.get(codigo, jugada.tipo.nombre if jugada.tipo else "?")
    loterias = []
    numeros = []
    for sorteo in (jugada.sorteo, jugada.sorteo2):
        if sorteo is None:
            continue
        loterias.append(sorteo.nombre)
        oficial = _numero_oficial(db, sorteo.id, jugada.fecha)
        if oficial is not None:
            numeros.append(oficial[0])
    cobrado = _premio_ya_cobrado(jugada, ticket)
    cajero = None
    if jugada.pagado_por_usuario_id:
        cajero = db.get(Usuario, jugada.pagado_por_usuario_id)
    elif cobrado and ticket.pagado_por_usuario_id:
        cajero = db.get(Usuario, ticket.pagado_por_usuario_id)
    return {
        "loteria": " · ".join(loterias),
        "fecha": jugada.fecha.isoformat() if jugada.fecha else "",
        "tipo": codigo,
        "tipo_nombre": tipo,
        "numeros": jugada.numeros,
        "numero_ganador": " · ".join(numeros),
        "acierto": jugada.detalle_eval or "",
        "premio": str(D(jugada.premio)),
        "estado_pago": "pagado" if cobrado else "pendiente",
        "pagado_en": jugada.pagado_en.isoformat(sep=" ") if jugada.pagado_en else (
            ticket.pagado_en.isoformat(sep=" ") if cobrado and ticket.pagado_en else None
        ),
        "cajero": cajero.nombre if cajero else "",
        "empresa": ticket.sucursal_vendedora.nombre if ticket.sucursal_vendedora else "",
    }


def _vista_pago(db, ticket):
    """Pantalla de pago: solo premios, sorteos todavía sin resultado y el total pendiente."""
    premios = []
    pendientes = []
    vistos = set()
    for jugada in ticket.jugadas:
        if jugada.evaluada and jugada.premio is not None and D(jugada.premio) > 0:
            premios.append(_linea_premio(db, ticket, jugada))
            continue
        if jugada.evaluada:
            continue
        for sorteo in (jugada.sorteo, jugada.sorteo2):
            if sorteo is None:
                continue
            clave = (sorteo.id, jugada.fecha)
            if clave in vistos:
                continue
            vistos.add(clave)
            pendientes.append({
                "loteria": sorteo.nombre,
                "fecha": jugada.fecha.isoformat() if jugada.fecha else "",
            })
    pendiente = sum((D(fila["premio"]) for fila in premios if fila["estado_pago"] == "pendiente"), D(0))
    pagado = sum((D(fila["premio"]) for fila in premios if fila["estado_pago"] == "pagado"), D(0))
    lineas = []
    if ticket.es_prueba:
        lineas.append("PRUEBA — NO OFICIAL")
    empresa = ticket.sucursal_vendedora.nombre if ticket.sucursal_vendedora else "?"
    codigo = ticket.sucursal_vendedora.codigo if ticket.sucursal_vendedora else "?"
    lineas.extend([
        f"EMPRESA: {empresa}",
        f"CÓDIGO: {codigo}",
        f"TICKET #{ticket.id}",
        f"SERIAL: {ticket.serial}",
        "",
    ])
    if ticket.estado == "anulado":
        lineas.append("TICKET ANULADO")
    elif ticket.estado == "vencido":
        lineas.append("TICKET VENCIDO")
    elif not premios:
        lineas.append("TICKET SIN PREMIOS")
    for fila in premios:
        lineas.extend([
            fila["tipo_nombre"],
            f"Lotería: {fila['loteria']}",
            f"Fecha: {fila['fecha']}",
            f"Número ganador: {fila['numero_ganador']}",
            f"Jugada: {fila['numeros']}",
            f"Premio: RD${fila['premio']}",
            "Estado: PAGADO" if fila["estado_pago"] == "pagado" else "Estado: PENDIENTE DE PAGO",
        ])
        if fila["estado_pago"] == "pagado" and fila["cajero"]:
            lineas.append(f"Cajero: {fila['cajero']}")
        if fila["pagado_en"]:
            lineas.append(f"Fecha de pago: {fila['pagado_en']}")
        lineas.append("")
    if pendientes and ticket.estado not in ("anulado", "vencido"):
        lineas.append("SORTEOS PENDIENTES")
        for fila in pendientes:
            lineas.append(f"{fila['loteria']} {fila['fecha']}")
        lineas.append("Esos sorteos no se pagan todavía.")
        lineas.append("")
    if premios and ticket.estado not in ("anulado", "vencido"):
        lineas.append(f"PREMIO TOTAL: RD${pendiente + pagado}")
        lineas.append(f"PREMIO YA PAGADO: RD${pagado}")
        lineas.append(f"PREMIO PENDIENTE: RD${pendiente}")
        lineas.append(f"SE COBRARÁ: RD${pendiente}")
    puede = (
        ticket.estado not in ("anulado", "vencido")
        and pendiente > 0
        and not (ticket.es_prueba and not modo_desarrollo())
    )
    return {
        "premios": premios,
        "sorteos_pendientes": pendientes,
        "premio_pendiente": str(pendiente),
        "premio_pagado": str(pagado),
        "importe_a_cobrar": str(pendiente),
        "texto_pago": "\n".join(lineas).rstrip(),
        "puede_pagar": puede,
    }


def consultar_ticket(db, ticket_id, serial):
    ticket = buscar_ticket(db, ticket_id, serial)
    datos = ticket_a_dict(db, ticket)
    datos["no_oficial"] = bool(ticket.es_prueba)
    if ticket.es_prueba and not modo_desarrollo():
        datos["puede_pagar"] = False
        datos["veredicto"] = "TICKET DE PRUEBA"
        datos["mensaje"] = "Ticket de prueba: no se paga y no afecta la caja"
        datos.update(_vista_pago(db, ticket))
        datos["puede_pagar"] = False
        return datos
    datos["puede_pagar"] = ticket.estado == "ganador"
    if ticket.estado == "ganador":
        datos["veredicto"] = (
            "TICKET GANADOR — PENDIENTE DE PAGO — NO OFICIAL"
            if ticket.es_prueba else "TICKET GANADOR — PENDIENTE DE PAGO"
        )
        datos["mensaje"] = f"Ticket ganador: pague ${D(ticket.premio_total)}"
    elif ticket.estado == "pagado":
        p = datos["pago"]
        datos["veredicto"] = "TICKET YA PAGADO — NO OFICIAL" if ticket.es_prueba else "TICKET YA PAGADO"
        datos["mensaje"] = (
            f"Ya pagado en la sucursal {p['sucursal']}, el día {p['fecha_hora']}"
        )
    elif ticket.estado == "no_ganador":
        datos["veredicto"] = "TICKET NO GANADOR"
        datos["mensaje"] = "El ticket no ganó"
    elif ticket.estado == "anulado":
        datos["veredicto"] = "TICKET ANULADO"
        datos["mensaje"] = "El ticket está anulado"
    elif ticket.estado == "vencido":
        datos["veredicto"] = "TICKET VENCIDO"
        datos["mensaje"] = "El ticket está vencido"
    else:
        datos["veredicto"] = "RESULTADOS PENDIENTES"
        datos["mensaje"] = "Ticket vendido: aún faltan resultados por liquidar"
    datos.update(_vista_pago(db, ticket))
    datos["puede_pagar"] = (
        D(datos["premio_pendiente"]) > 0 and ticket.estado not in ("anulado", "vencido")
    )
    if ticket.estado == "ganador":
        datos["mensaje"] = f"Ticket ganador: pague ${datos['premio_pendiente']}"
    elif ticket.estado == "parcial":
        datos["veredicto"] = "PAGO PARCIAL — QUEDA PREMIO PENDIENTE"
        datos["mensaje"] = f"Cobrar ahora ${datos['importe_a_cobrar']}"
    texto = comprobante_premio(db, ticket)
    if texto:
        datos["comprobante"] = texto
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


def reimprimir_ticket(db, ticket_id, serial, usuario_id, terminal_id=None):
    """Registra una copia. No crea venta, no mueve la caja y no cambia el estado."""
    ticket = buscar_ticket(db, ticket_id, serial)
    saldo = None
    sucursal = db.get(Sucursal, ticket.sucursal_vendedora_id)
    if sucursal is not None:
        saldo = D(sucursal.saldo_actual)
    estado = ticket.estado
    ticket.reimpresiones = int(ticket.reimpresiones or 0) + 1
    ticket.ultima_reimpresion_en = ahora_local()
    auditar(
        db, "ticket", ticket.id, "reimpresion", usuario_id=usuario_id, terminal_id=terminal_id,
        detalle={"cantidad": ticket.reimpresiones, "fecha": ticket.ultima_reimpresion_en.isoformat(sep=" "),
                 "usuario_id": usuario_id},
    )
    db.commit()
    db.refresh(ticket)
    if ticket.estado != estado or (sucursal is not None and D(sucursal.saldo_actual) != saldo):
        raise ErrorServicio(500, "La reimpresión no debe cambiar el ticket ni la caja")
    datos = consultar_ticket(db, ticket_id, serial)
    datos["reimpresion"] = True
    datos["leyenda"] = "COPIA — REIMPRESIÓN"
    return datos


def mi_caja_de(usuario):
    if usuario is None:
        return D(0)
    if modo_desarrollo():
        return D(usuario.saldo_caja_prueba or 0)
    return D(usuario.saldo_caja or 0)


def _respuesta_pago(db, ticket_id, serial, usuario_id):
    datos = consultar_ticket(db, ticket_id, serial)
    cajero = db.get(Usuario, usuario_id)
    if cajero is not None:
        datos.update(indicadores_caja(db, cajero))
    return datos


def _premios_sin_cobrar(ticket):
    return [
        j for j in ticket.jugadas
        if j.evaluada and j.premio is not None and D(j.premio) > 0 and not j.pagada
    ]


def _cobrar_premios(db, ticket, sucursal_pagadora_id, terminal_id, usuario_id, operacion_id, prueba):
    """Cobra, una sola vez, los premios ya comparados con un resultado.

    Los sorteos sin resultado se quedan fuera. Dos cajeros que escanean el
    mismo ticket reservan las jugadas con una sola actualización.
    """
    if ticket.estado in ("anulado", "vencido", "pagado"):
        _error_no_pagable(db, ticket)
    op = str(operacion_id).strip()[:40] if operacion_id else uuid.uuid4().hex
    if any(j.pago_operacion_id == op for j in ticket.jugadas):
        return _respuesta_pago(db, ticket.id, ticket.serial, usuario_id)
    sucursal = db.get(Sucursal, sucursal_pagadora_id)
    cajero = db.get(Usuario, usuario_id)
    pendientes = _premios_sin_cobrar(ticket)
    if not pendientes:
        if any(not j.evaluada for j in ticket.jugadas):
            raise ErrorServicio(409, "El ticket aún no es ganador: faltan resultados por liquidar")
        _error_no_pagable(db, ticket)
    premio = sum((D(j.premio) for j in pendientes), D(0))
    caja_real = D(sucursal.saldo_actual) if sucursal is not None else D(0)
    if prueba:
        caja_prueba = D(cajero.saldo_caja_prueba or 0) if cajero is not None else D(0)
        if cajero is None or caja_prueba < premio:
            auditar(db, "ticket", ticket.id, "pago_bloqueado", usuario_id=usuario_id,
                    terminal_id=terminal_id,
                    detalle={"motivo": "caja_prueba_insuficiente", "premio": str(premio),
                             "caja_prueba": str(caja_prueba), "es_prueba": True})
            db.commit()
            raise ErrorServicio(
                409,
                f"La caja de prueba tiene ${caja_prueba} y el premio simulado es ${premio}. "
                "No se pagó y la caja real no se tocó.",
            )
    else:
        if sucursal is None or caja_real < premio:
            auditar(db, "ticket", ticket.id, "pago_bloqueado", usuario_id=usuario_id,
                    terminal_id=terminal_id,
                    detalle={"motivo": "caja_insuficiente", "premio": str(premio),
                             "caja": str(caja_real), "sucursal_pagadora": sucursal_pagadora_id})
            db.commit()
            raise ErrorServicio(
                409,
                f"Advertencia: la caja de esta sucursal tiene ${caja_real} y el premio es ${premio}. "
                "No se pagó: el premio queda pendiente hasta que el consorcio entregue "
                "efectivo a la sucursal.",
            )
    ahora = ahora_local()
    filas = (
        db.execute(
            update(Jugada)
            .where(
                Jugada.ticket_id == ticket.id,
                Jugada.evaluada.is_(True),
                Jugada.premio > 0,
                Jugada.pagada.is_(False),
            )
            .values(
                pagada=True,
                pagado_en=ahora,
                pagado_por_usuario_id=usuario_id,
                pago_operacion_id=op,
            )
        ).rowcount
        or 0
    )
    if filas < 1:
        db.rollback()
        db.expire_all()
        _error_no_pagable(db, buscar_ticket(db, ticket.id, ticket.serial))
    reclamadas = db.query(Jugada).filter_by(ticket_id=ticket.id, pago_operacion_id=op).all()
    monto = sum((D(j.premio or 0) for j in reclamadas), D(0))
    if monto != premio or len(reclamadas) != filas:
        db.rollback()
        raise ErrorServicio(409, "No se pudo reservar el premio. No se descontó la caja.")
    db.expire_all()
    sucursal = db.get(Sucursal, sucursal_pagadora_id)
    ticket = db.get(Ticket, ticket.id)
    if prueba:
        mover_caja_cajera(
            db, usuario_id, sucursal.id, "pago_premio_prueba", monto,
            f"Pago de prueba ticket {ticket.id}", -1, bolsa="prueba",
        )
        if D(sucursal.saldo_actual) != caja_real:
            db.rollback()
            raise ErrorServicio(500, "Un pago de prueba no puede cambiar la caja real")
        accion = "pago_prueba"
    else:
        sucursal.saldo_actual = D(sucursal.saldo_actual) - monto
        db.add(
            MovimientoSaldo(
                sucursal_id=sucursal.id,
                tipo="pago_premio",
                monto=monto,
                referencia=f"Pago ticket {ticket.id}",
                saldo_resultante=sucursal.saldo_actual,
                creado_por=usuario_id,
            )
        )
        mover_caja_cajera(db, usuario_id, sucursal.id, "pago_premio", monto, f"Pago ticket {ticket.id}", -1)
        accion = "pago"
    motor.recomputar_ticket(db, ticket)
    if ticket.estado == "pagado":
        ticket.pagado_en_sucursal_id = sucursal_pagadora_id
        ticket.pagado_por_terminal_id = terminal_id
        ticket.pagado_por_usuario_id = usuario_id
        ticket.pagado_en = ahora
        ticket.pago_operacion_id = op
    auditar(
        db, "ticket", ticket.id, accion, usuario_id=usuario_id, terminal_id=terminal_id,
        detalle={
            "monto": str(monto),
            "empresa": sucursal.nombre if sucursal else "",
            "sucursal_pagadora": sucursal_pagadora_id,
            "no_oficial": prueba,
            "jugadas": [
                {
                    "loteria": " · ".join(
                        nombre for nombre in (
                            j.sorteo.nombre if j.sorteo else None,
                            j.sorteo2.nombre if j.sorteo2 else None,
                        ) if nombre
                    ),
                    "sorteo_id": j.sorteo_id,
                    "fecha": j.fecha.isoformat() if j.fecha else "",
                    "tipo": j.tipo.codigo if j.tipo else "",
                    "premio": str(D(j.premio or 0)),
                }
                for j in reclamadas
            ],
        },
    )
    db.commit()
    db.expire_all()
    return _respuesta_pago(db, ticket.id, ticket.serial, usuario_id)


def pagar_ticket(db, ticket_id, serial, sucursal_pagadora_id, terminal_id, usuario_id, operacion_id=None):
    """Cobra los premios disponibles de un ticket. Un segundo intento no los cobra otra vez."""
    ticket = buscar_ticket(db, ticket_id, serial)
    if operacion_id:
        previo = db.query(Ticket).filter_by(pago_operacion_id=str(operacion_id)[:40]).first()
        if previo is not None and previo.id == ticket.id and previo.estado == "pagado":
            return _respuesta_pago(db, ticket_id, serial, usuario_id)
    if ticket.es_prueba:
        if not modo_desarrollo():
            raise ErrorServicio(409, "Ticket de prueba: no se paga y no afecta la caja")
        return _cobrar_premios(
            db, ticket, sucursal_pagadora_id, terminal_id, usuario_id, operacion_id, True,
        )
    return _cobrar_premios(
        db, ticket, sucursal_pagadora_id, terminal_id, usuario_id, operacion_id, False,
    )


def anular_ticket(db, ticket_id, serial, usuario_id, terminal_id=None, ahora=None, motivo=None,
                   solo_propietario=False):
    ahora = ahora or ahora_local()
    ticket = buscar_ticket(db, ticket_id, serial)
    if solo_propietario and ticket.usuario_id != usuario_id:
        raise ErrorServicio(403, "Solo puede anular sus propios tickets")
    if ticket.estado == "anulado":
        raise ErrorServicio(409, "El ticket ya está anulado")
    if ticket.estado == "pagado":
        datos = ticket_a_dict(db, ticket)
        p = datos["pago"]
        raise ErrorServicio(409, f"El ticket ya fue pagado en la sucursal {p['sucursal']} el {p['fecha_hora']}")
    if any(j.pagada for j in ticket.jugadas):
        raise ErrorServicio(409, "Este ticket ya tiene premios pagados. No se puede anular.")
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
    motivo_txt = str(motivo or "").strip()[:200]
    ticket.anulado_motivo = motivo_txt or None
    sucursal = db.get(Sucursal, ticket.sucursal_vendedora_id)
    if not ticket.es_prueba:
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
        mover_caja_cajera(
            db, ticket.usuario_id, sucursal.id, "anulacion", D(ticket.total),
            f"Anulación ticket {ticket.id}", -1, motivo=ticket.anulado_motivo,
        )
    elif modo_desarrollo():
        mover_caja_cajera(
            db, ticket.usuario_id, sucursal.id, "anulacion_prueba", D(ticket.total),
            f"Anulación de prueba ticket {ticket.id}", -1, motivo=ticket.anulado_motivo,
            bolsa="prueba",
        )
    auditar(db, "ticket", ticket.id, "anulacion", usuario_id=usuario_id, terminal_id=terminal_id,
            detalle={"total_devuelto": "0.00" if ticket.es_prueba else str(D(ticket.total)),
                     "motivo": ticket.anulado_motivo, "usuario_id": usuario_id,
                     "fecha": ahora.isoformat(sep=" "), "es_prueba": bool(ticket.es_prueba)})
    db.commit()
    db.refresh(ticket)
    return ticket_a_dict(db, ticket)


def aplicar_limite_todas(db, tipo_codigo, numeros, monto, usuario_id, reemplazar=False, aplicar=False):
    """Crea el mismo límite en todos los sorteos configurados.

    Con reemplazar en falso conserva el límite individual que ya exista.
    Sin aplicar solo calcula el resumen y no escribe."""
    tipo = db.query(TipoJugada).filter_by(codigo=str(tipo_codigo).upper()).first()
    if tipo is None:
        raise ErrorServicio(404, "Tipo de jugada no válido")
    if D(monto) <= D(0):
        raise ErrorServicio(400, "El monto máximo debe ser mayor que cero")
    n1, n2 = _parse_numeros(tipo.codigo, numeros)
    clave = clave_numero(n1, n2)
    sorteos = db.query(Sorteo).order_by(Sorteo.id).all()
    creados = []
    actualizados = []
    omitidos = []
    for sorteo in sorteos:
        existente = db.query(LimiteVenta).filter_by(
            sorteo_id=sorteo.id, tipo_jugada_id=tipo.id, clave_numero=clave).first()
        if existente is None:
            creados.append({"id": sorteo.id, "sorteo": sorteo.nombre})
            if aplicar:
                db.add(LimiteVenta(
                    sorteo_id=sorteo.id, tipo_jugada_id=tipo.id, clave_numero=clave,
                    monto_max_acumulado=D(monto)))
        elif reemplazar:
            actualizados.append({"id": sorteo.id, "sorteo": sorteo.nombre})
            if aplicar:
                existente.monto_max_acumulado = D(monto)
        else:
            omitidos.append({"id": sorteo.id, "sorteo": sorteo.nombre,
                             "monto_max_acumulado": str(D(existente.monto_max_acumulado))})
    if aplicar:
        db.flush()
        auditar(db, "limite", clave, "aplicar_todas", usuario_id=usuario_id, detalle={
            "tipo": tipo.codigo, "clave": clave, "monto": str(D(monto)), "reemplazar": bool(reemplazar),
            "creados": len(creados), "actualizados": len(actualizados), "omitidos": len(omitidos),
        })
        db.commit()
    return {
        "tipo": tipo.codigo,
        "clave": clave,
        "monto_max_acumulado": str(D(monto)),
        "sorteos": len(sorteos),
        "creados": len(creados),
        "actualizados": len(actualizados),
        "omitidos": len(omitidos),
        "reemplazar": bool(reemplazar),
        "aplicado": bool(aplicar),
        "detalle_omitidos": omitidos,
    }


def limite_cajera_a_dict(db, fila):
    cajera = db.get(Usuario, fila.usuario_id)
    sucursal = db.get(Sucursal, fila.sucursal_id)
    tipo = db.get(TipoJugada, fila.tipo_jugada_id)
    sorteo = db.get(Sorteo, fila.sorteo_id) if fila.sorteo_id else None
    codigo = tipo.codigo if tipo else "?"
    if fila.clave_numero == CUALQUIER_NUMERO:
        numero = "Todos los números" if codigo == "QN" else "Cualquier combinación"
    else:
        numero = fila.clave_numero
    return {
        "id": fila.id,
        "usuario_id": fila.usuario_id,
        "cajera": cajera.nombre if cajera else "",
        "usuario": cajera.usuario if cajera else "",
        "sucursal_id": fila.sucursal_id,
        "sucursal": sucursal.nombre if sucursal else "",
        "sorteo_id": fila.sorteo_id,
        "sorteo": "Todas las loterías" if not fila.sorteo_id else (sorteo.nombre if sorteo else "?"),
        "tipo": codigo,
        "clave_numero": fila.clave_numero,
        "numero": numero,
        "monto_max_acumulado": str(D(fila.monto_max_acumulado)),
    }


def _clave_limite(tipo, numeros):
    if numeros is None or str(numeros).strip() in ("", "*", "TODOS"):
        return CUALQUIER_NUMERO
    n1, n2 = _parse_numeros(tipo.codigo, numeros)
    return clave_numero(n1, n2)


def guardar_limite_cajera(db, admin, usuario_id, sorteo_id, tipo_codigo, numeros, monto, limite_id=None):
    if admin is None or admin.rol != "admin":
        raise ErrorServicio(403, "Solo un administrador puede guardar límites de cajera")
    if D(monto) <= 0:
        raise ErrorServicio(400, "El monto máximo debe ser mayor que cero")
    cajera = db.get(Usuario, usuario_id)
    if cajera is None or cajera.rol != "operador" or not cajera.activo or not cajera.sucursal_id:
        raise ErrorServicio(400, "Seleccione una cajera activa")
    tipo = db.query(TipoJugada).filter_by(codigo=str(tipo_codigo).upper()).first()
    if tipo is None or tipo.codigo not in ("QN", "PL", "SP"):
        raise ErrorServicio(400, "El tipo de límite no es válido")
    sorteo = int(sorteo_id or 0)
    if sorteo and db.get(Sorteo, sorteo) is None:
        raise ErrorServicio(404, "La lotería no existe")
    clave = _clave_limite(tipo, numeros)
    otro = (
        db.query(LimiteCajera)
        .filter_by(usuario_id=cajera.id, sorteo_id=sorteo, tipo_jugada_id=tipo.id, clave_numero=clave)
        .first()
    )
    if limite_id:
        fila = db.get(LimiteCajera, limite_id)
        if fila is None:
            raise ErrorServicio(404, "El límite no existe")
        if otro is not None and otro.id != fila.id:
            raise ErrorServicio(409, "Esa cajera ya tiene ese límite")
    elif otro is not None:
        fila = otro
    else:
        fila = LimiteCajera(usuario_id=cajera.id, sucursal_id=cajera.sucursal_id)
        db.add(fila)
    fila.usuario_id = cajera.id
    fila.sucursal_id = cajera.sucursal_id
    fila.sorteo_id = sorteo
    fila.tipo_jugada_id = tipo.id
    fila.clave_numero = clave
    fila.monto_max_acumulado = D(monto)
    db.flush()
    auditar(db, "limite_cajera", fila.id, "limite_cajera", usuario_id=admin.id, detalle={
        "cajera_id": cajera.id, "sorteo_id": sorteo, "tipo": tipo.codigo, "clave": clave, "monto": str(D(monto)),
    })
    db.commit()
    db.refresh(fila)
    return limite_cajera_a_dict(db, fila)


def listar_limites_cajera(db, usuario_id=None, sucursal_id=None):
    q = db.query(LimiteCajera)
    if usuario_id is not None:
        q = q.filter(LimiteCajera.usuario_id == usuario_id)
    if sucursal_id is not None:
        q = q.filter(LimiteCajera.sucursal_id == sucursal_id)
    return [limite_cajera_a_dict(db, fila) for fila in q.order_by(LimiteCajera.id.desc()).all()]


def borrar_limite_cajera(db, admin, limite_id):
    if admin is None or admin.rol != "admin":
        raise ErrorServicio(403, "Solo un administrador puede eliminar límites de cajera")
    fila = db.get(LimiteCajera, limite_id)
    if fila is None:
        raise ErrorServicio(404, "El límite no existe")
    db.delete(fila)
    auditar(db, "limite_cajera", limite_id, "eliminacion", usuario_id=admin.id, detalle={})
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- resultados
def guardar_resultado(db, sorteo_id, fecha, p1, p2, p3, usuario, fuente="manual", simulado=False):
    """Crea o corrige un resultado en estado PROPUESTO. Nunca toca uno
    confirmado/liquidado: para corregirlo hay que revertirlo primero.

    Un resultado simulado solo existe en modo desarrollo. Liquida tickets de
    prueba y no se confirma como oficial ni reemplaza un resultado de RDLotto.
    """
    if simulado:
        if not modo_desarrollo():
            raise ErrorServicio(403, "Un resultado simulado solo existe en modo desarrollo")
        fuente = "simulado"
    sorteo = db.get(Sorteo, sorteo_id)
    if sorteo is None:
        raise ErrorServicio(404, "El sorteo no existe")
    numeros = [p1, p2, p3]
    for n in numeros:
        if n is None or int(n) < 0 or int(n) > 99:
            raise ErrorServicio(400, "Cada premio debe ser un número entre 00 y 99")
    if len(set(int(n) for n in numeros)) != 3:
        raise ErrorServicio(400, "Los tres premios deben ser números diferentes")
    premios = tuple(int(n) for n in numeros)
    r = db.query(Resultado).filter_by(sorteo_id=sorteo_id, fecha=fecha).first()
    if simulado and r is not None and (r.fuente in ("rdlotto", "conectate") or r.externo):
        raise ErrorServicio(
            409,
            "Esa lotería ya tiene un resultado de RDLotto. El resultado simulado no lo reemplaza.",
        )
    if r is not None and r.estado in ("confirmado", "liquidado"):
        raise ErrorServicio(
            409,
            "Este resultado ya fue confirmado/liquidado. Para corregirlo, primero revierta la liquidación.",
        )
    if simulado and r is not None and r.id is not None:
        pagados = motor.pruebas_pagadas_con(db, r)
        if pagados:
            db.add(
                CorreccionPendiente(
                    resultado_id=r.id,
                    premio1=premios[0], premio2=premios[1], premio3=premios[2],
                    fuente="simulado",
                    detalle="RESULTADO SIMULADO — NO OFICIAL. No se movió dinero.",
                )
            )
            db.commit()
            raise ErrorServicio(
                409,
                "Hay un pago de prueba con este resultado. La corrección quedó pendiente "
                "y no movió la caja.",
            )
        motor.reabrir_pruebas(db, r)
    if r is None:
        r = Resultado(sorteo_id=sorteo_id, fecha=fecha, estado="propuesto")
        db.add(r)
    r.premio1, r.premio2, r.premio3 = premios
    r.fuente = fuente
    if simulado:
        r.estado = "propuesto"
    r.propuesto_por = usuario.id
    r.propuesto_en = ahora_local()
    db.flush()
    auditar(db, "resultado", r.id, "registro_resultado",
            usuario_id=usuario.id,
            detalle={"sorteo": sorteo.nombre, "fecha": str(fecha),
                     "numeros": [f"{n:02d}" for n in premios], "fuente": fuente,
                     "leyenda": "RESULTADO SIMULADO — NO OFICIAL" if simulado else ""})
    if not simulado and fuente == "manual":
        from .estabilizacion import bloquear_manual
        bloquear_manual(db, sorteo_id, fecha)
    db.commit()
    db.refresh(r)
    r._tickets_prueba = 0
    if simulado:
        r._tickets_prueba = motor.liquidar_resultado_prueba(db, r)
        db.commit()
        db.refresh(r)
    return r


def confirmar_resultado(db, resultado_id, usuario):
    """Confirmar = liquidar en la misma operación: el motor evalúa QN/PL/SP
    y marca cada ticket. El resultado queda en estado LIQUIDADO."""
    r = db.get(Resultado, resultado_id)
    if r is None:
        raise ErrorServicio(404, "El resultado no existe")
    if r.fuente == "simulado":
        raise ErrorServicio(
            409,
            "RESULTADO SIMULADO — NO OFICIAL. No se confirma ni liquida tickets reales.",
        )
    if r.estado == "liquidado":
        raise ErrorServicio(409, "Este resultado ya fue confirmado y liquidado")
    if r.estado == "recibido":
        raise ErrorServicio(409, "El resultado todavía es provisional. No se habilita el pago.")
    if r.estado not in ("propuesto", "en_verificacion", "confirmado"):
        raise ErrorServicio(409, "Este resultado no está listo para confirmarse.")
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


_RESULTADOS_VISIBLES = ("propuesto", "en_verificacion", "recibido", "confirmado", "liquidado")
_RESULTADOS_CONFIRMADOS = ("confirmado", "liquidado")


def _estado_panel(sorteo, resultado, hoy, momento, fallo):
    from .conectate_widget import RECONOCIDOS, motivo_sin_fuente

    if sorteo.nombre not in RECONOCIDOS:
        return "SIN FUENTE", motivo_sin_fuente(sorteo.nombre)
    if resultado is not None and resultado.fecha == hoy and resultado.estado != "error_fuente":
        if resultado.estado in ("confirmado", "liquidado"):
            return "RESULTADO RECIBIDO", resultado.fuente or ""
        return "EN REVISIÓN", "PROVISIONAL. Faltan tres lecturas iguales o los 10 minutos."
    if fallo and momento.time() >= sorteo.hora_cierre:
        return "ERROR DE CONSULTA", fallo
    from .conectate_firmado import es_especial

    if es_especial(sorteo.nombre):
        return (
            "PENDIENTE",
            "Todavía no hay tres números. Hace falta que el operador y "
            "Conéctate coincidan en fecha, hora y números.",
        )
    return "PENDIENTE", "Todavía no hay tres números. La fuente es el widget de Conéctate."


def tablero_resultados(db, hoy=None):
    """Los 40 sorteos con el estado de su resultado. No confirma ni paga."""
    hoy = hoy or ahora_local().date()
    momento = ahora_local()
    ultima = (
        db.query(Importacion)
        .filter(Importacion.fecha_objetivo == hoy)
        .order_by(Importacion.id.desc())
        .first()
    )
    fallo = None
    if ultima is not None and not ultima.ok:
        fallo = ultima.detalle or "La última consulta falló"
    datos = consulta_resultados(db, hoy)
    por_id = {fila["id"]: fila for fila in datos["sorteos"]}
    sorteos = db.query(Sorteo).filter_by(activo=True).order_by(Sorteo.orden, Sorteo.id).all()
    filas = []
    for sorteo in sorteos:
        resultado = (
            db.query(Resultado)
            .filter(Resultado.sorteo_id == sorteo.id, Resultado.fecha == hoy, Resultado.estado != "error_fuente")
            .order_by(Resultado.id.desc())
            .first()
        )
        estado, motivo = _estado_panel(sorteo, resultado, hoy, momento, fallo)
        base = por_id.get(sorteo.id, {})
        base["estado_panel"] = estado
        base["motivo_fuente"] = motivo
        filas.append(base)
    return {"hoy": hoy.isoformat(), "zona": "America/Santo_Domingo", "sorteos": filas}


def consulta_resultados(db, hoy):
    """Lectura para la terminal. No confirma, no liquida y no mueve dinero.

    Si el sorteo tiene resultado en la fecha consultada, ese es el que se
    muestra. Si no, se conserva el último anterior. Un error de fuente no
    cuenta como resultado.
    """
    sorteos = db.query(Sorteo).filter_by(activo=True).order_by(Sorteo.orden, Sorteo.id).all()
    guardados = (
        db.query(Resultado)
        .filter(Resultado.estado.in_(_RESULTADOS_VISIBLES))
        .order_by(Resultado.fecha.desc(), Resultado.id.desc())
        .all()
    )
    por_sorteo = {}
    for resultado in guardados:
        por_sorteo.setdefault(resultado.sorteo_id, []).append(resultado)
    filas = []
    for sorteo in sorteos:
        elegido = None
        for resultado in por_sorteo.get(sorteo.id, []):
            if resultado.fecha == hoy:
                elegido = resultado
                break
        if elegido is None:
            for resultado in por_sorteo.get(sorteo.id, []):
                if resultado.fecha < hoy:
                    elegido = resultado
                    break
        if elegido is None:
            filas.append({
                "id": sorteo.id,
                "nombre": sorteo.nombre,
                "hora": sorteo.hora_sorteo.strftime("%H:%M"),
                "fecha": None,
                "premio1": None,
                "premio2": None,
                "premio3": None,
                "estado": None,
                "confirmado": False,
                "vigente": False,
                "pendiente": True,
            })
            continue
        filas.append({
            "id": sorteo.id,
            "nombre": sorteo.nombre,
            "hora": sorteo.hora_sorteo.strftime("%H:%M"),
            "fecha": elegido.fecha.isoformat(),
            "premio1": f"{elegido.premio1:02d}",
            "premio2": f"{elegido.premio2:02d}",
            "premio3": f"{elegido.premio3:02d}",
            "estado": elegido.estado,
            "confirmado": elegido.estado in _RESULTADOS_CONFIRMADOS,
            "vigente": elegido.fecha == hoy,
            "pendiente": False,
        })
    return {"hoy": hoy.isoformat(), "zona": "America/Santo_Domingo", "sorteos": filas}


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
        "leyenda": "RESULTADO SIMULADO — NO OFICIAL" if r.fuente == "simulado" else "",
        "no_oficial": r.fuente == "simulado",
        "version": int(r.version or 1),
        "externo": r.externo,
        "confirmado_en": r.confirmado_en.isoformat(sep=" ") if r.confirmado_en else None,
        "liquidado_en": r.liquidado_en.isoformat(sep=" ") if r.liquidado_en else None,
    }


def mover_caja_cajera(db, usuario_id, sucursal_id, tipo, monto, referencia, signo, motivo=None, bolsa="real"):
    """signo 1 suma al cajón de esa persona; signo -1 lo resta. No toca otra cajera.

    bolsa "prueba" mueve solo el balance de desarrollo. La caja real no cambia.
    """
    if not usuario_id:
        return None
    usuario = db.get(Usuario, usuario_id)
    if usuario is None or usuario.sucursal_id != sucursal_id:
        return None
    monto = D(monto)
    if bolsa == "prueba":
        actual = D(usuario.saldo_caja_prueba or 0)
        usuario.saldo_caja_prueba = actual + monto if signo > 0 else actual - monto
        resultante = usuario.saldo_caja_prueba
    else:
        actual = D(usuario.saldo_caja or 0)
        usuario.saldo_caja = actual + monto if signo > 0 else actual - monto
        resultante = usuario.saldo_caja
    mov = MovimientoCajera(
        usuario_id=usuario.id,
        sucursal_id=sucursal_id,
        tipo=tipo,
        monto=monto,
        saldo_resultante=resultante,
        referencia=referencia,
        motivo=(motivo or "")[:200] or None,
    )
    db.add(mov)
    return mov


_RECAUDACION_REAL = ("venta", "anulacion", "pago_premio")
_RECAUDACION_PRUEBA = ("venta_prueba", "anulacion_prueba", "pago_premio_prueba")
_FONDO_TIPOS = {"aporte_prueba", "transferencia_general"}
_FONDO_ETIQUETA = "FONDO ASIGNADO POR ADMINISTRADOR"


def fondo_a_dict(db, fondo):
    cajera = db.get(Usuario, fondo.usuario_id)
    sucursal = db.get(Sucursal, fondo.sucursal_id)
    admin = db.get(Usuario, fondo.autorizado_por)
    return {
        "id": fondo.id,
        "operacion_id": fondo.operacion_id,
        "usuario_id": fondo.usuario_id,
        "cajera": cajera.nombre if cajera else "",
        "usuario": cajera.usuario if cajera else "",
        "sucursal_id": fondo.sucursal_id,
        "sucursal": sucursal.nombre if sucursal else "",
        "autorizado_por": fondo.autorizado_por,
        "administrador": admin.nombre if admin else "",
        "tipo": fondo.tipo,
        "etiqueta": _FONDO_ETIQUETA,
        "origen": "Aporte de prueba" if fondo.tipo == "aporte_prueba" else "Transferencia desde caja general",
        "monto": str(D(fondo.monto)),
        "motivo": fondo.motivo or "",
        "mi_caja": str(mi_caja_de(cajera)),
        "saldo_caja": str(D(cajera.saldo_caja or 0)) if cajera else "0.00",
        "saldo_caja_prueba": str(D(cajera.saldo_caja_prueba or 0)) if cajera else "0.00",
        "saldo_cajera_resultante": str(D(fondo.saldo_cajera_resultante)),
        "saldo_general": str(D(sucursal.saldo_actual)) if sucursal else None,
        "saldo_general_resultante": str(D(fondo.saldo_general_resultante)),
        "es_venta": False,
        "sale_de_caja_general": fondo.tipo == "transferencia_general",
        "incluido_en_caja_general": False,
        "creado_en": fondo.creado_en.isoformat(sep=" ") if fondo.creado_en else None,
    }


def _fondo_repetido(previo, usuario_id, sucursal_id, monto, tipo, admin_id):
    return (
        previo.usuario_id == usuario_id
        and previo.sucursal_id == sucursal_id
        and D(previo.monto) == monto
        and previo.tipo == tipo
        and previo.autorizado_por == admin_id
    )


def asignar_fondo(db, admin, usuario_id, sucursal_id, monto, tipo, operacion_id, motivo=None):
    """Acredita el cajón de una cajera una sola vez por operación.

    El aporte de prueba no toca la caja general. La transferencia sale de
    esa caja y no se suma otra vez encima del consolidado.
    """
    if admin is None or admin.rol != "admin":
        raise ErrorServicio(403, "Solo un administrador puede asignar fondos")
    if not operacion_id or not str(operacion_id).strip():
        raise ErrorServicio(400, "La asignación necesita un identificador de operación")
    op = str(operacion_id).strip()[:40]
    monto = D(monto)
    if monto <= 0:
        raise ErrorServicio(400, "El fondo debe ser mayor que cero")
    if tipo not in _FONDO_TIPOS:
        raise ErrorServicio(400, "Elija un aporte de prueba o una transferencia desde la caja general")
    previa = db.query(FondoAsignado).filter_by(operacion_id=op).first()
    if previa is not None:
        if _fondo_repetido(previa, usuario_id, sucursal_id, monto, tipo, admin.id):
            return fondo_a_dict(db, previa)
        raise ErrorServicio(409, "Esa operación ya se registró con otros datos. No se acreditó de nuevo.")
    cajera = db.get(Usuario, usuario_id)
    if cajera is None or cajera.rol != "operador" or not cajera.activo:
        raise ErrorServicio(400, "Seleccione una cajera activa")
    if cajera.id == admin.id:
        raise ErrorServicio(403, "Una cajera no puede asignarse fondos")
    if cajera.sucursal_id != sucursal_id:
        raise ErrorServicio(400, "La cajera no pertenece a esa sucursal")
    sucursal = db.get(Sucursal, sucursal_id)
    if sucursal is None:
        raise ErrorServicio(404, "La sucursal no existe")
    general_antes = D(sucursal.saldo_actual)
    real_antes = D(cajera.saldo_caja or 0)
    prueba_antes = D(cajera.saldo_caja_prueba or 0)
    if tipo == "transferencia_general":
        filas = (
            db.execute(
                update(Sucursal)
                .where(Sucursal.id == sucursal.id, Sucursal.saldo_actual >= monto)
                .values(saldo_actual=Sucursal.saldo_actual - monto)
            ).rowcount
            or 0
        )
        if filas != 1:
            db.rollback()
            raise ErrorServicio(
                409,
                f"La caja general tiene ${general_antes} y el fondo es ${monto}. No se asignó.",
            )
        db.expire(sucursal)
        sucursal = db.get(Sucursal, sucursal_id)
        if D(sucursal.saldo_actual) != general_antes - monto:
            db.rollback()
            raise ErrorServicio(409, "La caja general cambió. No se asignó el fondo.")
        bolsa = "real"
        tipo_mov = "fondo_general"
        db.add(
            MovimientoSaldo(
                sucursal_id=sucursal.id,
                tipo="fondo_cajera",
                monto=monto,
                referencia=f"{_FONDO_ETIQUETA} {op}",
                saldo_resultante=sucursal.saldo_actual,
                creado_por=admin.id,
            )
        )
    else:
        bolsa = "prueba"
        tipo_mov = "fondo_prueba"
    mov = mover_caja_cajera(
        db, cajera.id, sucursal.id, tipo_mov, monto, _FONDO_ETIQUETA, 1,
        motivo=(motivo or "").strip()[:200] or None, bolsa=bolsa,
    )
    if mov is None:
        db.rollback()
        raise ErrorServicio(409, "No se pudo acreditar el cajón de la cajera")
    mov.creado_en = ahora_local()
    db.flush()
    db.expire(cajera)
    cajera = db.get(Usuario, usuario_id)
    db.expire(sucursal)
    sucursal = db.get(Sucursal, sucursal_id)
    if tipo == "aporte_prueba":
        if D(sucursal.saldo_actual) != general_antes or D(cajera.saldo_caja or 0) != real_antes:
            db.rollback()
            raise ErrorServicio(500, "Un aporte de prueba no puede mover la caja general ni la caja real")
        if D(cajera.saldo_caja_prueba or 0) != prueba_antes + monto:
            db.rollback()
            raise ErrorServicio(409, "El cajón de prueba cambió. No se asignó el fondo.")
        resultante = D(cajera.saldo_caja_prueba or 0)
    else:
        if D(cajera.saldo_caja or 0) != real_antes + monto or D(cajera.saldo_caja_prueba or 0) != prueba_antes:
            db.rollback()
            raise ErrorServicio(409, "El cajón real cambió o se mezcló con la caja de prueba. No se asignó.")
        resultante = D(cajera.saldo_caja or 0)
    fondo = FondoAsignado(
        operacion_id=op,
        usuario_id=cajera.id,
        sucursal_id=sucursal.id,
        autorizado_por=admin.id,
        tipo=tipo,
        monto=monto,
        motivo=(motivo or "").strip()[:200] or None,
        saldo_cajera_resultante=resultante,
        saldo_general_resultante=D(sucursal.saldo_actual),
        creado_en=ahora_local(),
    )
    db.add(fondo)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        previa = db.query(FondoAsignado).filter_by(operacion_id=op).first()
        if previa is not None and _fondo_repetido(previa, usuario_id, sucursal_id, monto, tipo, admin.id):
            return fondo_a_dict(db, previa)
        raise ErrorServicio(409, "Esa operación ya se registró. No se acreditó de nuevo.")
    auditar(
        db, "fondo", fondo.id, "fondo_asignado", usuario_id=admin.id,
        detalle={
            "cajera_id": cajera.id, "sucursal_id": sucursal.id, "tipo": tipo,
            "monto": str(monto), "operacion_id": op, "etiqueta": _FONDO_ETIQUETA,
        },
    )
    db.commit()
    db.refresh(fondo)
    return fondo_a_dict(db, fondo)


def listar_fondos(db, sucursal_id=None, usuario_id=None):
    q = db.query(FondoAsignado)
    if sucursal_id is not None:
        q = q.filter(FondoAsignado.sucursal_id == sucursal_id)
    if usuario_id is not None:
        q = q.filter(FondoAsignado.usuario_id == usuario_id)
    return [fondo_a_dict(db, fondo) for fondo in q.order_by(FondoAsignado.id.desc()).all()]


def indicadores_caja(db, usuario):
    """Cifras del ciclo abierto.

    MI CAJA es el efectivo que queda en el cajón.
    RECAUDACIÓN es ventas menos anulaciones menos premios pagados.
    El fondo asignado y las entregas explican la diferencia:
    MI CAJA = fondo asignado + recaudación − entregas del ciclo.
    """
    if usuario is None:
        cero = str(D(0))
        return {
            "mi_caja": cero,
            "efectivo_pendiente": cero,
            "entrega_pendiente": cero,
            "recaudacion_ciclo": cero,
            "fondo_inicial": None,
            "fondo_asignado": cero,
            "entregas_ciclo": cero,
            "cuadre": cero,
            "diferencia": cero,
            "es_prueba": modo_desarrollo(),
        }
    prueba = modo_desarrollo()
    saldo = mi_caja_de(usuario)
    if prueba:
        ventas = ("venta_prueba",)
        restas = ("anulacion_prueba", "pago_premio_prueba")
        fondos = ("fondo_prueba",)
        entregas_tipos = ("entrega_prueba",)
        otra = ("venta", "anulacion", "pago_premio", "fondo_general", "entrega")
    else:
        ventas = ("venta",)
        restas = ("anulacion", "pago_premio")
        fondos = ("fondo_general",)
        entregas_tipos = ("entrega",)
        otra = ("venta_prueba", "anulacion_prueba", "pago_premio_prueba", "fondo_prueba", "entrega_prueba")
    marca = usuario.ciclo_caja_prueba_movimiento_id if prueba else usuario.ciclo_caja_movimiento_id
    q = db.query(MovimientoCajera).filter(MovimientoCajera.usuario_id == usuario.id)
    if marca:
        q = q.filter(MovimientoCajera.id > marca)
    recaudacion = D(0)
    fondo = D(0)
    entregas = D(0)
    for mov in q.all():
        tipo = str(mov.tipo)
        monto = D(mov.monto)
        if tipo in otra:
            continue
        if tipo in ventas:
            recaudacion += monto
        elif tipo in restas:
            recaudacion -= monto
        elif tipo in fondos:
            fondo += monto
        elif tipo in entregas_tipos:
            entregas += monto
    cuadre = fondo + recaudacion - entregas
    return {
        "mi_caja": str(saldo),
        "efectivo_pendiente": str(saldo),
        "entrega_pendiente": str(saldo),
        "recaudacion_ciclo": str(recaudacion),
        "fondo_inicial": None,
        "fondo_asignado": str(fondo),
        "entregas_ciclo": str(entregas),
        "cuadre": str(cuadre),
        "diferencia": str(saldo - cuadre),
        "es_prueba": prueba,
    }


def estado_entrega(db, operador, sucursal, terminal):
    ahora = ahora_local()
    datos = {
        "cajera": operador.nombre,
        "sucursal": sucursal.nombre if sucursal else "?",
        "terminal": terminal.serial_sunmi if terminal else "?",
        "fecha_hora": ahora.strftime("%d-%m-%Y %I:%M %p"),
    }
    datos.update(indicadores_caja(db, operador))
    return datos


def entregar_efectivo(db, operador, sucursal, terminal, monto, operacion_id):
    """Descuenta solo el cajón de esta cajera. No toca la caja de la sucursal."""
    if not operacion_id or not str(operacion_id).strip():
        raise ErrorServicio(400, "La entrega necesita un identificador de operación")
    op = str(operacion_id).strip()[:40]
    previa = db.query(Entrega).filter_by(operacion_id=op).first()
    if previa is not None:
        if previa.usuario_id != operador.id:
            raise ErrorServicio(409, "Esa operación pertenece a otra cajera")
        datos = entrega_a_dict(db, previa)
        datos.update(indicadores_caja(db, db.get(Usuario, operador.id)))
        return datos
    monto = D(monto)
    if monto <= 0:
        raise ErrorServicio(400, "El monto a entregar debe ser mayor que cero")
    prueba = modo_desarrollo()
    usuario = db.get(Usuario, operador.id)
    if usuario is None:
        raise ErrorServicio(401, "La cajera de esta sesión no existe")
    columna = Usuario.saldo_caja_prueba if prueba else Usuario.saldo_caja
    anterior = D(usuario.saldo_caja_prueba if prueba else usuario.saldo_caja)
    if monto > anterior:
        raise ErrorServicio(
            409,
            f"No se puede entregar ${monto}. El efectivo disponible de esta cajera es ${anterior}.",
        )
    caja_sucursal = D(sucursal.saldo_actual) if sucursal is not None else D(0)
    otra_bolsa = D(usuario.saldo_caja if prueba else usuario.saldo_caja_prueba or 0)
    cambiado = (
        db.execute(
            update(Usuario).where(Usuario.id == usuario.id, columna >= monto).values({columna: columna - monto})
        ).rowcount
        or 0
    )
    if cambiado != 1:
        db.rollback()
        raise ErrorServicio(409, "No se pudo entregar: el efectivo disponible cambió. Consulte de nuevo.")
    db.expire(usuario)
    usuario = db.get(Usuario, operador.id)
    restante = D(usuario.saldo_caja_prueba if prueba else usuario.saldo_caja)
    if restante != anterior - monto:
        db.rollback()
        raise ErrorServicio(409, "No se pudo entregar: el efectivo disponible cambió. Consulte de nuevo.")
    if D(sucursal.saldo_actual) != caja_sucursal:
        db.rollback()
        raise ErrorServicio(500, "Una entrega de cajera no puede cambiar la caja de la sucursal")
    if D(usuario.saldo_caja if prueba else usuario.saldo_caja_prueba or 0) != otra_bolsa:
        db.rollback()
        raise ErrorServicio(500, "Una entrega no puede mezclar el dinero de prueba con el real")
    mov = MovimientoCajera(
        usuario_id=usuario.id,
        sucursal_id=sucursal.id,
        tipo="entrega_prueba" if prueba else "entrega",
        monto=monto,
        saldo_resultante=restante,
        referencia=f"Entrega {op}",
    )
    db.add(mov)
    db.flush()
    if restante == 0:
        if prueba:
            usuario.ciclo_caja_prueba_movimiento_id = mov.id
        else:
            usuario.ciclo_caja_movimiento_id = mov.id
    entrega = Entrega(
        operacion_id=op,
        usuario_id=usuario.id,
        sucursal_id=sucursal.id,
        terminal_id=terminal.id if terminal is not None else None,
        monto=monto,
        saldo_anterior=anterior,
        saldo_restante=restante,
        es_prueba=prueba,
        estado="confirmada",
    )
    db.add(entrega)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        previa = db.query(Entrega).filter_by(operacion_id=op).first()
        if previa is not None and previa.usuario_id == operador.id:
            return entrega_a_dict(db, previa)
        raise ErrorServicio(409, "Esa entrega ya fue registrada")
    ahora = ahora_local()
    entrega.texto = _texto_entrega(sucursal, terminal, usuario.nombre, entrega, ahora, prueba)
    auditar(db, "entrega", entrega.id, "entrega_cajera", usuario_id=usuario.id,
            terminal_id=terminal.id if terminal is not None else None,
            detalle={"monto": str(monto), "saldo_restante": str(restante), "es_prueba": prueba,
                     "operacion_id": op})
    db.commit()
    db.refresh(entrega)
    datos = entrega_a_dict(db, entrega)
    datos.update(indicadores_caja(db, usuario))
    return datos


def entrega_por_operacion(db, operador_id, operacion_id):
    if not operacion_id:
        raise ErrorServicio(404, "No hay una entrega registrada con esa operación")
    entrega = db.query(Entrega).filter_by(operacion_id=str(operacion_id).strip()[:40]).first()
    if entrega is None or entrega.usuario_id != operador_id:
        raise ErrorServicio(404, "No hay una entrega registrada con esa operación")
    return entrega_a_dict(db, entrega)


def entrega_para_reimprimir(db, operador_id, entrega_id):
    entrega = db.get(Entrega, int(entrega_id))
    if entrega is None or entrega.usuario_id != operador_id:
        raise ErrorServicio(404, "La entrega no existe")
    return entrega_a_dict(db, entrega)


def listar_entregas(db, usuario, sucursal_id=None):
    if usuario.rol not in ("admin", "supervisor"):
        raise ErrorServicio(403, "Su rol no puede consultar las entregas")
    q = db.query(Entrega)
    if usuario.rol == "supervisor":
        if sucursal_id and int(sucursal_id) != usuario.sucursal_id:
            raise ErrorServicio(403, "Solo puede consultar las entregas de su sucursal")
        q = q.filter(Entrega.sucursal_id == usuario.sucursal_id)
    elif sucursal_id:
        q = q.filter(Entrega.sucursal_id == int(sucursal_id))
    filas = [entrega_a_dict(db, e) for e in q.order_by(Entrega.id.desc()).limit(200).all()]
    return {
        "reales": [f for f in filas if not f["es_prueba"]],
        "prueba": [f for f in filas if f["es_prueba"]],
    }


def recibir_entrega(db, entrega_id, usuario):
    """Marca la recepción física. No vuelve a descontar el dinero."""
    if usuario.rol not in ("admin", "supervisor"):
        raise ErrorServicio(403, "Su rol no puede recibir una entrega")
    entrega = db.get(Entrega, int(entrega_id))
    if entrega is None:
        raise ErrorServicio(404, "La entrega no existe")
    if usuario.rol == "supervisor" and usuario.sucursal_id != entrega.sucursal_id:
        raise ErrorServicio(403, "Solo puede recibir las entregas de su sucursal")
    cajero = db.get(Usuario, entrega.usuario_id)
    sucursal = db.get(Sucursal, entrega.sucursal_id)
    caja_cajero = D(cajero.saldo_caja or 0) if cajero is not None else D(0)
    caja_prueba = D(cajero.saldo_caja_prueba or 0) if cajero is not None else D(0)
    caja_sucursal = D(sucursal.saldo_actual) if sucursal is not None else D(0)
    if entrega.recibida_en is None:
        entrega.recibida_en = ahora_local()
        entrega.recibida_por = usuario.id
        auditar(db, "entrega", entrega.id, "recepcion_efectivo", usuario_id=usuario.id,
                detalle={"monto": str(D(entrega.monto)), "es_prueba": bool(entrega.es_prueba)})
        db.commit()
        db.refresh(entrega)
    if cajero is not None and (D(cajero.saldo_caja or 0) != caja_cajero or D(cajero.saldo_caja_prueba or 0) != caja_prueba):
        raise ErrorServicio(500, "Recibir una entrega no puede cambiar la caja de la cajera")
    if sucursal is not None and D(sucursal.saldo_actual) != caja_sucursal:
        raise ErrorServicio(500, "Recibir una entrega no puede cambiar la caja de la sucursal")
    return entrega_a_dict(db, entrega)


def entrega_a_dict(db, entrega):
    usuario = db.get(Usuario, entrega.usuario_id)
    sucursal = db.get(Sucursal, entrega.sucursal_id)
    terminal = db.get(Terminal, entrega.terminal_id) if entrega.terminal_id else None
    return {
        "id": entrega.id,
        "numero": entrega.id,
        "operacion_id": entrega.operacion_id,
        "cajera": usuario.nombre if usuario else "?",
        "sucursal": sucursal.nombre if sucursal else "?",
        "sucursal_id": entrega.sucursal_id,
        "terminal": terminal.serial_sunmi if terminal else "?",
        "fecha_hora": entrega.creado_en.strftime("%d-%m-%Y %I:%M %p") if entrega.creado_en else "",
        "monto": str(D(entrega.monto)),
        "saldo_anterior": str(D(entrega.saldo_anterior)),
        "saldo_restante": str(D(entrega.saldo_restante)),
        "estado": "CONFIRMADA",
        "recepcion": "RECIBIDA" if entrega.recibida_en else "PENDIENTE",
        "recibida_en": entrega.recibida_en.isoformat(sep=" ") if entrega.recibida_en else None,
        "es_prueba": bool(entrega.es_prueba),
        "leyenda": "PRUEBA — NO OFICIAL" if entrega.es_prueba else "",
        "texto": entrega.texto or "",
    }


def _texto_entrega(sucursal, terminal, cajero, entrega, cuando, prueba):
    lineas = []
    if prueba:
        lineas.append("PRUEBA — NO OFICIAL")
    lineas += [
        (sucursal.nombre if sucursal else "SUCURSAL").upper(),
        "COMPROBANTE DE ENTREGA",
        cuando.strftime("%d-%m-%Y %I:%M %p"),
        f"Cajera: {cajero}",
        f"Sucursal: {sucursal.nombre if sucursal else '?'}",
        f"Terminal: {terminal.serial_sunmi if terminal else '?'}",
        f"Número de entrega: {entrega.id}",
        f"Saldo anterior: RD$ {D(entrega.saldo_anterior)}",
        f"Monto entregado: RD$ {D(entrega.monto)}",
        f"Saldo restante: RD$ {D(entrega.saldo_restante)}",
        "Estado: CONFIRMADA",
    ]
    return "\n".join(lineas)


def _filas_ganadores(db, fecha, sorteo_id, sucursal_id, usuario_id, estado, prueba):
    q = db.query(Ticket).filter(
        Ticket.es_prueba.is_(prueba), Ticket.estado.in_(("ganador", "parcial", "pagado")),
    )
    if fecha is not None:
        q = q.filter(Ticket.fecha == fecha)
    if sucursal_id:
        q = q.filter(Ticket.sucursal_vendedora_id == sucursal_id)
    if usuario_id:
        q = q.filter(Ticket.usuario_id == usuario_id)
    if estado == "ganador":
        q = q.filter(Ticket.estado.in_(("ganador", "parcial")))
    elif estado == "pagado":
        q = q.filter(Ticket.estado == estado)
    if sorteo_id:
        q = q.join(Jugada).filter((Jugada.sorteo_id == sorteo_id) | (Jugada.sorteo2_id == sorteo_id))
    vistos = []
    ids = set()
    for ticket in q.order_by(Ticket.id.desc()).all():
        if ticket.id in ids:
            continue
        ids.add(ticket.id)
        vistos.append(ticket)
    filas = []
    for ticket in vistos:
        datos = ticket_a_dict(db, ticket)
        pagador = db.get(Usuario, ticket.pagado_por_usuario_id) if ticket.pagado_por_usuario_id else None
        jugada = next((j for j in ticket.jugadas if j.premio and D(j.premio) > 0), None)
        filas.append({
            "id": ticket.id,
            "serial": ticket.serial,
            "loterias": " · ".join(" · ".join(j["loterias"]) for j in datos["jugadas"]),
            "fecha": datos["fecha"],
            "cajero": datos["cajero"],
            "banca": datos["banca"],
            "numero": jugada.numeros if jugada is not None else "",
            "modalidad": jugada.tipo.codigo if jugada is not None and jugada.tipo else "",
            "monto": str(D(jugada.monto)) if jugada is not None else datos["total"],
            "premio": datos["premio_total"],
            "estado": ticket.estado,
            "cajero_pago": pagador.nombre if pagador else "",
            "pagado_en": ticket.pagado_en.isoformat(sep=" ") if ticket.pagado_en else None,
            "no_oficial": prueba,
            "leyenda": "PRUEBA — NO OFICIAL" if prueba else "",
        })
    return filas


def listar_ganadores(db, fecha=None, sorteo_id=None, sucursal_id=None, usuario_id=None, estado=None):
    """Los totales son solo de tickets reales. Las pruebas van en otra lista."""
    filas = _filas_ganadores(db, fecha, sorteo_id, sucursal_id, usuario_id, estado, False)
    premios = sum((D(f["premio"]) for f in filas), D(0))
    pagados = sum((D(f["premio"]) for f in filas if f["estado"] == "pagado"), D(0))
    pruebas = _filas_ganadores(db, fecha, sorteo_id, sucursal_id, usuario_id, estado, True) if modo_desarrollo() else []
    return {
        "tickets": filas,
        "total_tickets": len(filas),
        "total_premios": str(premios),
        "premios_pagados": str(pagados),
        "premios_pendientes": str(premios - pagados),
        "prueba": pruebas,
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


def entregar_cuadre(db, sucursal_id, terminal_id, usuario_id, fecha=None, efectivo_contado=None,
                    limitar_a_usuario=None):
    """Cuadre del día: ventas − premios pagados − gastos + efectivo recibido.
    La diferencia entre lo contado y lo esperado queda registrada tal cual."""
    fecha = fecha or ahora_local().date()
    q = db.query(Cuadre).filter(Cuadre.fecha == fecha, Cuadre.sucursal_id == sucursal_id)
    q = q.filter(Cuadre.terminal_id == terminal_id) if terminal_id else q.filter(Cuadre.terminal_id.is_(None))
    if q.first() is not None:
        raise ErrorServicio(409, "Ya se entregó el cuadre de esta terminal/sucursal para esa fecha")

    f_ventas = [Ticket.fecha == fecha, Ticket.estado != "anulado", Ticket.es_prueba.is_(False)]
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
    if limitar_a_usuario is not None:
        f_ventas.append(Ticket.usuario_id == limitar_a_usuario)
        f_premios.append(Ticket.pagado_por_usuario_id == limitar_a_usuario)
        f_caja.append(TransaccionCaja.usuario_id == limitar_a_usuario)

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


def consolidado_cajas(db, sucursal_id):
    """Suma informativa de los cajones. No se escribe en la caja de la sucursal."""
    cajeras = (
        db.query(Usuario)
        .filter(Usuario.sucursal_id == sucursal_id, Usuario.rol == "operador")
        .all()
    )
    real = sum((D(u.saldo_caja or 0) for u in cajeras), D(0))
    prueba = sum((D(u.saldo_caja_prueba or 0) for u in cajeras), D(0))
    return {
        "cajeras": len(cajeras),
        "cajas_reales": str(real),
        "cajas_prueba": str(prueba),
        "informativo": True,
        "incluido_en_caja_general": False,
    }


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
def _tickets_rango(db, desde, hasta, sucursal_id=None, usuario_id=None):
    q = db.query(Ticket).filter(Ticket.fecha >= desde, Ticket.fecha <= hasta, Ticket.es_prueba.is_(False))
    if sucursal_id:
        q = q.filter(Ticket.sucursal_vendedora_id == sucursal_id)
    if usuario_id is not None:
        q = q.filter(Ticket.usuario_id == usuario_id)
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


def reporte_ventas(db, desde, hasta, usuario_id=None, sucursal_id=None, limite=500):
    """Todas las ventas del rango con el usuario que vendió cada ticket
    (la vista del consorcio para ver todo lo que vendió cada cajera).
    El total vendido excluye los anulados: ese dinero volvió al cliente."""
    q = db.query(Ticket).filter(Ticket.fecha >= desde, Ticket.fecha <= hasta)
    if usuario_id:
        q = q.filter(Ticket.usuario_id == usuario_id)
    if sucursal_id:
        q = q.filter(Ticket.sucursal_vendedora_id == sucursal_id)
    tickets = q.order_by(Ticket.id.desc()).limit(min(limite, 1000)).all()
    nombres = {}
    filas = []
    total_vendido = D(0)
    total_premios = D(0)
    for t in tickets:
        if t.usuario_id not in nombres:
            u = db.get(Usuario, t.usuario_id) if t.usuario_id else None
            nombres[t.usuario_id] = (u.nombre, u.usuario) if u else ("—", "—")
        nombre, login = nombres[t.usuario_id]
        fila = _ticket_resumen(db, t)
        fila["operador"] = nombre
        fila["operador_usuario"] = login
        fila["es_prueba"] = bool(t.es_prueba)
        fila["vendido_en"] = t.vendido_en.isoformat(sep=" ") if t.vendido_en else None
        filas.append(fila)
        if t.estado != "anulado":
            total_vendido += D(t.total)
        if t.estado in ("ganador", "pagado"):
            total_premios += D(t.premio_total)
    return {
        "desde": desde.isoformat(), "hasta": hasta.isoformat(),
        "tickets": filas, "total_tickets": len(filas),
        "total_vendido": str(total_vendido), "total_premios": str(total_premios),
        "modo_desarrollo": modo_desarrollo(),
        "aviso": "MODO DESARROLLO — DATOS DE PRUEBA" if modo_desarrollo() else "",
    }


_NOMBRE_JUGADA = {"QN": "QUINIELA", "PL": "PALÉ", "SP": "SÚPER PALÉ"}


def comprobante_premio(db, ticket):
    """Recibo de los premios ya cobrados. Reimprimirlo no vuelve a cobrar."""
    ganadoras = [j for j in ticket.jugadas if _premio_ya_cobrado(j, ticket)]
    if not ganadoras:
        return ""
    sucursal = ticket.sucursal_pago or ticket.sucursal_vendedora
    cajero = db.get(Usuario, ticket.pagado_por_usuario_id) if ticket.pagado_por_usuario_id else None
    if cajero is None:
        for jugada in ganadoras:
            if jugada.pagado_por_usuario_id:
                cajero = db.get(Usuario, jugada.pagado_por_usuario_id)
                break
    lineas = [
        (sucursal.nombre if sucursal else "?").upper(),
        "COMPROBANTE DE PREMIO PAGADO",
    ]
    if ticket.es_prueba:
        lineas.append("PRUEBA — NO OFICIAL")
    lineas.append(f"Ticket: {ticket.id}")
    lineas.append(f"Serial: {ticket.serial}")
    total = D(0)
    for jugada in ganadoras:
        codigo = jugada.tipo.codigo if jugada.tipo else ""
        tipo = _NOMBRE_JUGADA.get(codigo, jugada.tipo.nombre if jugada.tipo else "?")
        loterias = [jugada.sorteo.nombre] if jugada.sorteo else []
        if jugada.sorteo2 is not None:
            loterias.append(jugada.sorteo2.nombre)
        lineas.append("Lotería: " + " · ".join(loterias))
        lineas.append(f"Jugada: {tipo} {jugada.numeros}")
        lineas.append(f"Monto jugado: RD${D(jugada.monto)}")
        lineas.append(f"Premio: RD${D(jugada.premio)}")
        total += D(jugada.premio)
    if ticket.estado != "pagado":
        if any(not j.evaluada for j in ticket.jugadas):
            lineas.append("PAGO PARCIAL — QUEDAN SORTEOS PENDIENTES")
        else:
            lineas.append("PAGO PARCIAL — QUEDA PREMIO PENDIENTE")
    lineas.extend([
        f"PREMIO PAGADO: RD${total}",
        f"Cajero: {cajero.nombre if cajero else ''}",
        "Fecha y hora: " + (
            ticket.pagado_en.isoformat(sep=" ") if ticket.pagado_en else (
                max(j.pagado_en for j in ganadoras if j.pagado_en).isoformat(sep=" ")
                if any(j.pagado_en for j in ganadoras) else ""
            )
        ),
        "Pago: " + (ticket.pago_operacion_id or (ganadoras[0].pago_operacion_id or str(ticket.id))),
        "ESTADO: PAGADO",
        "GRACIAS POR SU VISITA",
    ])
    return "\n".join(lineas)


def periodo_quincena(anio, mes, cual):
    """Quincena 1: día 1 al 15. Quincena 2: día 16 al último día del mes."""
    if cual == 1:
        return datetime(anio, mes, 1).date(), datetime(anio, mes, 15).date()
    ultimo = calendar.monthrange(anio, mes)[1]
    return datetime(anio, mes, 16).date(), datetime(anio, mes, ultimo).date()


def _pct_texto(valor):
    texto = f"{D(valor):.2f}"
    if texto.endswith(".00"):
        return texto[:-3]
    if texto.endswith("0"):
        return texto[:-1]
    return texto


def _porcentaje_vigente(db, usuario_id, momento):
    fila = (
        db.query(ComisionCajera)
        .filter(ComisionCajera.usuario_id == usuario_id, ComisionCajera.vigente_desde <= momento)
        .order_by(ComisionCajera.vigente_desde.desc(), ComisionCajera.id.desc())
        .first()
    )
    return D(fila.porcentaje) if fila is not None else D(0)


def comision_a_dict(db, fila):
    cajera = db.get(Usuario, fila.usuario_id)
    admin = db.get(Usuario, fila.autorizado_por)
    return {
        "id": fila.id,
        "usuario_id": fila.usuario_id,
        "cajera": cajera.nombre if cajera else "",
        "usuario": cajera.usuario if cajera else "",
        "sucursal_id": fila.sucursal_id,
        "porcentaje": _pct_texto(fila.porcentaje),
        "porcentaje_anterior": None if fila.porcentaje_anterior is None else _pct_texto(fila.porcentaje_anterior),
        "vigente_desde": fila.vigente_desde.isoformat(sep=" "),
        "autorizado_por": fila.autorizado_por,
        "administrador": admin.nombre if admin else "",
        "creado_en": fila.creado_en.isoformat(sep=" ") if fila.creado_en else None,
    }


def guardar_comision(db, admin, usuario_id, porcentaje):
    if admin is None or admin.rol != "admin":
        raise ErrorServicio(403, "Solo un administrador puede modificar comisiones")
    pct = D(porcentaje)
    if pct < 0 or pct > 100:
        raise ErrorServicio(400, "El porcentaje debe estar entre 0 y 100")
    cajera = db.get(Usuario, usuario_id)
    if cajera is None or cajera.rol != "operador" or not cajera.activo or not cajera.sucursal_id:
        raise ErrorServicio(400, "Seleccione una cajera activa")
    ahora = ahora_local()
    ultima = (
        db.query(ComisionCajera)
        .filter(ComisionCajera.usuario_id == cajera.id)
        .order_by(ComisionCajera.vigente_desde.desc(), ComisionCajera.id.desc())
        .first()
    )
    if ultima is not None and D(ultima.porcentaje) == pct:
        return comision_a_dict(db, ultima)
    fila = ComisionCajera(
        usuario_id=cajera.id,
        sucursal_id=cajera.sucursal_id,
        porcentaje=pct,
        porcentaje_anterior=D(ultima.porcentaje) if ultima is not None else None,
        vigente_desde=ahora,
        autorizado_por=admin.id,
        creado_en=ahora,
    )
    db.add(fila)
    db.flush()
    auditar(
        db, "comision", fila.id, "comision_cajera", usuario_id=admin.id,
        detalle={"cajera_id": cajera.id, "anterior": None if ultima is None else str(D(ultima.porcentaje)),
                 "nuevo": str(pct)},
    )
    db.commit()
    db.refresh(fila)
    return comision_a_dict(db, fila)


def listar_comisiones(db, sucursal_id=None, usuario_id=None):
    q = db.query(ComisionCajera)
    if sucursal_id is not None:
        q = q.filter(ComisionCajera.sucursal_id == sucursal_id)
    if usuario_id is not None:
        q = q.filter(ComisionCajera.usuario_id == usuario_id)
    return [comision_a_dict(db, fila) for fila in q.order_by(ComisionCajera.id.desc()).all()]


def _comision_tickets(db, desde, hasta, sucursal_id, usuario_id, prueba):
    q = db.query(Ticket).filter(
        Ticket.fecha >= desde,
        Ticket.fecha <= hasta,
        Ticket.sucursal_vendedora_id == sucursal_id,
        Ticket.es_prueba.is_(prueba),
    )
    if usuario_id is not None:
        q = q.filter(Ticket.usuario_id == usuario_id)
    tickets = q.order_by(Ticket.id).all()
    grupos = {}
    anulados = 0
    vendidos = 0
    ventas = D(0)
    premios = D(0)
    for ticket in tickets:
        if ticket.estado == "anulado":
            anulados += 1
            continue
        vendidos += 1
        ventas += D(ticket.total)
        if ticket.estado == "pagado":
            premios += D(ticket.premio_total)
        momento = ticket.vendido_en or datetime.combine(ticket.fecha, datetime.min.time())
        pct = _porcentaje_vigente(db, ticket.usuario_id, momento)
        clave = (ticket.usuario_id, str(pct))
        grupo = grupos.setdefault(clave, {"ventas": D(0), "tickets": 0, "porcentaje": pct, "usuario_id": ticket.usuario_id})
        grupo["ventas"] += D(ticket.total)
        grupo["tickets"] += 1
    desglose = []
    total = D(0)
    for grupo in grupos.values():
        monto = D(grupo["ventas"] * grupo["porcentaje"] / D(100))
        total += monto
        cajera = db.get(Usuario, grupo["usuario_id"])
        desglose.append({
            "usuario_id": grupo["usuario_id"],
            "cajera": cajera.nombre if cajera else "",
            "porcentaje": _pct_texto(grupo["porcentaje"]),
            "ventas": str(D(grupo["ventas"])),
            "tickets": grupo["tickets"],
            "comision": str(monto),
        })
    desglose.sort(key=lambda fila: (fila["cajera"], fila["porcentaje"]))
    porcentajes = {fila["porcentaje"] for fila in desglose}
    return {
        "ventas_validas": str(D(ventas)),
        "tickets_vendidos": vendidos,
        "tickets_anulados": anulados,
        "premios_pagados": str(D(premios)),
        "porcentaje": next(iter(porcentajes)) if len(porcentajes) == 1 else None,
        "comision": str(D(total)),
        "desglose": desglose,
        "descuenta_mi_caja": False,
        "descuenta_caja_general": False,
    }


def liquidacion_a_dict(db, fila):
    cajera = db.get(Usuario, fila.usuario_id)
    responsable = db.get(Usuario, fila.pagada_por) if fila.pagada_por else None
    return {
        "id": fila.id,
        "operacion_id": fila.operacion_id,
        "usuario_id": fila.usuario_id,
        "cajera": cajera.nombre if cajera else "",
        "sucursal_id": fila.sucursal_id,
        "desde": fila.desde.isoformat(),
        "hasta": fila.hasta.isoformat(),
        "ventas_reales": str(D(fila.ventas_reales)),
        "comision_real": str(D(fila.comision_real)),
        "ventas_prueba": str(D(fila.ventas_prueba)),
        "comision_prueba": str(D(fila.comision_prueba)),
        "importe": str(D(fila.importe)),
        "es_prueba": bool(fila.es_prueba),
        "estado": fila.estado,
        "detalle": fila.detalle,
        "pagada_en": fila.pagada_en.isoformat(sep=" ") if fila.pagada_en else None,
        "pagada_por": fila.pagada_por,
        "responsable": responsable.nombre if responsable else "",
        "creado_en": fila.creado_en.isoformat(sep=" ") if fila.creado_en else None,
        "descuenta_mi_caja": False,
        "descuenta_caja_general": False,
    }


def registrar_liquidacion(db, admin, usuario_id, desde, hasta, operacion_id):
    if admin is None or admin.rol != "admin":
        raise ErrorServicio(403, "Solo un administrador puede liquidar comisiones")
    if hasta < desde:
        raise ErrorServicio(400, "La fecha hasta no puede ser anterior a la fecha desde")
    if not operacion_id or not str(operacion_id).strip():
        raise ErrorServicio(400, "La liquidación necesita un identificador de operación")
    op = str(operacion_id).strip()[:40]
    cajera = db.get(Usuario, usuario_id)
    if cajera is None or cajera.rol != "operador" or not cajera.sucursal_id:
        raise ErrorServicio(400, "Seleccione una cajera")
    previa_op = db.query(LiquidacionComision).filter_by(operacion_id=op).first()
    if previa_op is not None:
        if previa_op.usuario_id == cajera.id and previa_op.desde == desde and previa_op.hasta == hasta:
            return liquidacion_a_dict(db, previa_op)
        raise ErrorServicio(409, "Esa operación ya liquidó otro período")
    previa = db.query(LiquidacionComision).filter_by(usuario_id=cajera.id, desde=desde, hasta=hasta).first()
    if previa is not None:
        return liquidacion_a_dict(db, previa)
    calculo = comision_periodo(db, desde, hasta, cajera.sucursal_id, cajera.id)
    real = calculo["real"]
    prueba = calculo["prueba"] or {"ventas_validas": "0.00", "comision": "0.00", "desglose": []}
    prueba_activa = bool(modo_desarrollo() and D(prueba["ventas_validas"]) > 0 and D(real["ventas_validas"]) == 0)
    importe = D(prueba["comision"] if prueba_activa else real["comision"])
    fila = LiquidacionComision(
        operacion_id=op,
        usuario_id=cajera.id,
        sucursal_id=cajera.sucursal_id,
        desde=desde,
        hasta=hasta,
        ventas_reales=D(real["ventas_validas"]),
        comision_real=D(real["comision"]),
        ventas_prueba=D(prueba["ventas_validas"]),
        comision_prueba=D(prueba["comision"]),
        importe=importe,
        es_prueba=prueba_activa,
        estado="pendiente",
        detalle=json.dumps({"real": real["desglose"], "prueba": prueba["desglose"]}, ensure_ascii=False),
        creado_en=ahora_local(),
    )
    db.add(fila)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        previa = db.query(LiquidacionComision).filter_by(usuario_id=cajera.id, desde=desde, hasta=hasta).first()
        if previa is not None:
            return liquidacion_a_dict(db, previa)
        raise ErrorServicio(409, "Esa quincena ya tiene una liquidación")
    db.commit()
    db.refresh(fila)
    return liquidacion_a_dict(db, fila)


def pagar_liquidacion(db, admin, liquidacion_id):
    if admin is None or admin.rol != "admin":
        raise ErrorServicio(403, "Solo un administrador puede marcar una comisión como pagada")
    fila = db.get(LiquidacionComision, liquidacion_id)
    if fila is None:
        raise ErrorServicio(404, "La liquidación no existe")
    if fila.estado == "pagada":
        raise ErrorServicio(409, "Esa comisión ya está pagada. No se descontó dinero.")
    cajera = db.get(Usuario, fila.usuario_id)
    sucursal = db.get(Sucursal, fila.sucursal_id)
    general = D(sucursal.saldo_actual) if sucursal is not None else D(0)
    real = D(cajera.saldo_caja or 0) if cajera is not None else D(0)
    prueba = D(cajera.saldo_caja_prueba or 0) if cajera is not None else D(0)
    fila.estado = "pagada"
    fila.pagada_en = ahora_local()
    fila.pagada_por = admin.id
    db.flush()
    if sucursal is not None and D(sucursal.saldo_actual) != general:
        db.rollback()
        raise ErrorServicio(500, "Marcar la comisión no puede cambiar la caja general")
    if cajera is not None and (D(cajera.saldo_caja or 0) != real or D(cajera.saldo_caja_prueba or 0) != prueba):
        db.rollback()
        raise ErrorServicio(500, "Marcar la comisión no puede cambiar MI CAJA")
    auditar(
        db, "liquidacion", fila.id, "comision_pagada", usuario_id=admin.id,
        detalle={"importe": str(D(fila.importe)), "cajera_id": fila.usuario_id, "estado": "pagada"},
    )
    db.commit()
    db.refresh(fila)
    return liquidacion_a_dict(db, fila)


def listar_liquidaciones(db, sucursal_id=None, usuario_id=None):
    q = db.query(LiquidacionComision)
    if sucursal_id is not None:
        q = q.filter(LiquidacionComision.sucursal_id == sucursal_id)
    if usuario_id is not None:
        q = q.filter(LiquidacionComision.usuario_id == usuario_id)
    return [liquidacion_a_dict(db, fila) for fila in q.order_by(LiquidacionComision.id.desc()).all()]


def resumen_comisiones(db, desde, hasta, sucursal_id=None, usuario_id=None):
    if hasta < desde:
        raise ErrorServicio(400, "La fecha hasta no puede ser anterior a la fecha desde")
    q = db.query(Usuario).filter(Usuario.rol == "operador")
    if sucursal_id is not None:
        q = q.filter(Usuario.sucursal_id == sucursal_id)
    if usuario_id is not None:
        q = q.filter(Usuario.id == usuario_id)
    filas = []
    for cajera in q.order_by(Usuario.nombre).all():
        if cajera.sucursal_id is None:
            continue
        if sucursal_id is not None and cajera.sucursal_id != sucursal_id:
            continue
        calculo = comision_periodo(db, desde, hasta, cajera.sucursal_id, cajera.id)
        sucursal = db.get(Sucursal, cajera.sucursal_id)
        filas.append({
            "usuario_id": cajera.id,
            "cajera": cajera.nombre,
            "usuario": cajera.usuario,
            "sucursal_id": cajera.sucursal_id,
            "sucursal": sucursal.nombre if sucursal else "",
            "porcentaje_actual": _pct_texto(_porcentaje_vigente(db, cajera.id, ahora_local())),
            "real": calculo["real"],
            "prueba": calculo["prueba"],
            "liquidacion": calculo["liquidacion"],
        })
    return {"desde": desde.isoformat(), "hasta": hasta.isoformat(), "cajeras": filas}


def comision_periodo(db, desde, hasta, sucursal_id, usuario_id=None):
    real = _comision_tickets(db, desde, hasta, sucursal_id, usuario_id, False)
    prueba = _comision_tickets(db, desde, hasta, sucursal_id, usuario_id, True) if modo_desarrollo() else None
    liquidacion = None
    if usuario_id is not None:
        fila = (
            db.query(LiquidacionComision)
            .filter_by(usuario_id=usuario_id, desde=desde, hasta=hasta)
            .first()
        )
        if fila is not None:
            liquidacion = liquidacion_a_dict(db, fila)
    return {"real": real, "prueba": prueba, "liquidacion": liquidacion}


def _lineas_comision(bloque, titulo):
    if bloque is None:
        return []
    lineas = ["", titulo]
    lineas.append(f"VENTAS VÁLIDAS: RD${bloque['ventas_validas']}")
    lineas.append(f"TICKETS VENDIDOS: {bloque['tickets_vendidos']}")
    lineas.append(f"TICKETS ANULADOS: {bloque['tickets_anulados']}")
    lineas.append(f"PREMIOS PAGADOS: RD${bloque['premios_pagados']}")
    if len(bloque["desglose"]) <= 1:
        lineas.append(f"PORCENTAJE DE COMISIÓN: {bloque['porcentaje'] or '0'}%")
    else:
        for fila in bloque["desglose"]:
            lineas.append(
                f"{fila['cajera']} {fila['porcentaje']}% SOBRE RD${fila['ventas']} = RD${fila['comision']}"
            )
    lineas.append(f"COMISIÓN A COBRAR: RD${bloque['comision']}")
    return lineas


def resumen_dia(db, desde, hasta, operador, sucursal, terminal, alcance="cajero"):
    """Resumen de lectura. No vende, no paga y no mueve la caja.

    El alcance de una cajera son sus tickets. Un supervisor puede ver la
    sucursal de su terminal. Nunca incluye tickets de otra banca.
    """
    if alcance not in ("cajero", "sucursal"):
        raise ErrorServicio(400, "El alcance debe ser cajero o sucursal")
    if alcance == "sucursal" and operador.rol not in ("admin", "supervisor"):
        raise ErrorServicio(403, "Su rol solo puede consultar su propio resumen")
    usuario_id = None if alcance == "sucursal" else operador.id
    real = _bloque_resumen(db, desde, hasta, sucursal.id, usuario_id, False)
    prueba = _bloque_resumen(db, desde, hasta, sucursal.id, usuario_id, True) if modo_desarrollo() else None
    ahora = ahora_local()
    datos = {
        "alcance": "sucursal" if usuario_id is None else "cajera autenticada",
        "puede_sucursal": operador.rol in ("admin", "supervisor"),
        "sucursal": sucursal.nombre if sucursal else "?",
        "terminal": terminal.serial_sunmi if terminal else "?",
        "cajero": operador.nombre,
        "desde": desde.strftime("%d-%m-%Y"),
        "hasta": hasta.strftime("%d-%m-%Y"),
        "impreso": ahora.strftime("%d-%m-%Y %I:%M %p"),
        "real": real,
        "prueba": prueba,
        "comision": comision_periodo(db, desde, hasta, sucursal.id, usuario_id),
    }
    datos["texto"] = _texto_resumen(datos)
    return datos


def _bloque_resumen(db, desde, hasta, sucursal_id, usuario_id, prueba):
    q = db.query(Ticket).filter(
        Ticket.fecha >= desde,
        Ticket.fecha <= hasta,
        Ticket.sucursal_vendedora_id == sucursal_id,
        Ticket.es_prueba.is_(prueba),
    )
    if usuario_id is not None:
        q = q.filter(Ticket.usuario_id == usuario_id)
    tickets = q.order_by(Ticket.id).all()
    vigentes = [t for t in tickets if t.estado != "anulado"]
    nulos = [t for t in tickets if t.estado == "anulado"]
    pagados = [t for t in tickets if t.estado == "pagado"]
    otra = [t for t in pagados if t.pagado_en_sucursal_id not in (None, sucursal_id)]
    pendientes = [t for t in tickets if t.estado in ("ganador", "parcial")]
    ventas = sum((D(t.total) for t in vigentes), D(0))
    premios_pagados = sum((D(t.premio_total) for t in pagados), D(0))
    monto_pendiente = sum((_importe_sin_cobrar(t) for t in pendientes), D(0))
    pagado_otra = sum((D(t.premio_total) for t in otra), D(0))
    return {
        "ventas": str(D(ventas)),
        "anulados_monto": str(D(sum((D(t.total) for t in nulos), D(0)))),
        "premios_pagados": str(D(premios_pagados)),
        "premios_pendientes": str(D(monto_pendiente)),
        "pagado_en_otra": str(D(pagado_otra)),
        "total_pagado": str(D(premios_pagados)),
        "neto": str(D(ventas - premios_pagados)),
        "pendientes": [
            {"id": t.id, "premio": str(D(t.premio_total)), "fecha": t.fecha.strftime("%d-%m-%Y")}
            for t in pendientes
        ],
    }


def _texto_resumen(datos):
    lineas = [
        datos["sucursal"].upper(),
        "RESUMEN DE VENTAS Y PAGOS",
        f"DESDE: {datos['desde']}",
        f"HASTA: {datos['hasta']}",
        f"IMPRESO: {datos['impreso']}",
        f"Sucursal: {datos['sucursal']}",
        f"Terminal: {datos['terminal']}",
        f"Cajero: {datos['cajero']}",
        f"Alcance: {datos['alcance']}",
        "",
    ]
    lineas.extend(_lineas_bloque(datos["real"]))
    comision = datos.get("comision") or {}
    lineas.extend(_lineas_comision(comision.get("real"), "COMISIÓN"))
    if datos.get("prueba") is not None:
        lineas.extend(["", "PRUEBA — NO OFICIAL", ""])
        lineas.extend(_lineas_bloque(datos["prueba"]))
        lineas.extend(_lineas_comision(comision.get("prueba"), "COMISIÓN DE PRUEBA"))
    liquidacion = comision.get("liquidacion")
    if liquidacion is not None:
        lineas.append(f"LIQUIDACIÓN: {liquidacion['estado'].upper()} RD${liquidacion['importe']}")
    lineas.append("La comisión no se descuenta de MI CAJA ni de la caja general.")
    return "\n".join(lineas)


def _lineas_bloque(bloque):
    lineas = [
        f"VENTAS: RD$ {bloque['ventas']}",
        f"PREMIOS PAGADOS: RD$ {bloque['premios_pagados']}",
        f"TOTAL NETO: RD$ {bloque['neto']}",
        "",
        "TICKET | GANADO | FECHA",
    ]
    if not bloque["pendientes"]:
        lineas.append("Sin tickets pendientes")
    for fila in bloque["pendientes"]:
        lineas.append(f"{fila['id']} | RD$ {fila['premio']} | {fila['fecha']}")
    lineas.extend([
        f"MONTO PENDIENTE: RD$ {bloque['premios_pendientes']}",
        f"PAGADO EN OTRA SUC.: RD$ {bloque['pagado_en_otra']}",
        f"TOTAL PAGADO: RD$ {bloque['total_pagado']}",
        f"TOTAL NETO: RD$ {bloque['neto']}",
    ])
    return lineas


def _dia_guardado(momento):
    """La hora guardada es la de República Dominicana. Si viniera con zona, se convierte."""
    if momento is None:
        return None
    if momento.tzinfo is not None:
        return momento.astimezone(ZONA).date()
    return momento.date()


def _importe_sin_cobrar(ticket):
    """Lo que todavía no salió de caja. Un ganador sin tramos usa el total guardado."""
    if ticket.estado == "ganador":
        return D(ticket.premio_total)
    if ticket.estado != "parcial":
        return D(0)
    return sum(
        (D(j.premio) for j in ticket.jugadas
         if j.evaluada and j.premio is not None and D(j.premio) > 0 and not j.pagada),
        D(0),
    )


def _premio_pendiente_valido(db, ticket):
    """Un pendiente es un ganador sin pagar cuyo resultado sigue respaldando el premio.

    Un resultado simulado solo respalda un ticket de prueba. Un ticket real
    exige un resultado confirmado o liquidado, y nunca uno simulado.
    """
    if ticket.estado not in ("ganador", "parcial") or _importe_sin_cobrar(ticket) <= 0:
        return False
    jugadas = [
        j for j in ticket.jugadas
        if j.evaluada and j.premio is not None and D(j.premio) > 0 and not j.pagada
    ]
    if not jugadas:
        return False
    for jugada in jugadas:
        sorteos = [jugada.sorteo_id]
        if jugada.sorteo2_id:
            sorteos.append(jugada.sorteo2_id)
        for sorteo_id in sorteos:
            fila = db.query(Resultado).filter_by(sorteo_id=sorteo_id, fecha=jugada.fecha).first()
            if fila is None or fila.estado == "error_fuente":
                return False
            if fila.fuente == "simulado":
                if not ticket.es_prueba or fila.estado not in (
                    "propuesto", "en_verificacion", "confirmado", "liquidado",
                ):
                    return False
            elif not ticket.es_prueba and fila.estado not in ("confirmado", "liquidado"):
                return False
    return True


def _bloque_periodo(db, desde, hasta, prueba, sucursal_id=None, usuario_id=None):
    """Ventas por fecha de venta, premios pagados por fecha de pago, sin mezclar el otro grupo."""
    vendidos = (
        db.query(Ticket)
        .filter(
            Ticket.fecha >= desde,
            Ticket.fecha <= hasta,
            Ticket.es_prueba.is_(prueba),
            Ticket.estado != "anulado",
        )
        .order_by(Ticket.id)
        .all()
    )
    vistos = set()
    ventas = D(0)
    grupos = {}
    tickets = []
    for ticket in vendidos:
        if ticket.id in vistos:
            continue
        if sucursal_id is not None and ticket.sucursal_vendedora_id != sucursal_id:
            continue
        if usuario_id is not None and ticket.usuario_id != usuario_id:
            continue
        vistos.add(ticket.id)
        tickets.append(ticket)
        ventas += D(ticket.total)
        momento = ticket.vendido_en or datetime.combine(ticket.fecha, datetime.min.time())
        pct = _porcentaje_vigente(db, ticket.usuario_id, momento)
        clave = (ticket.usuario_id, str(pct))
        grupos[clave] = grupos.get(clave, D(0)) + D(ticket.total)
    comision = D(0)
    for (_, pct), ventas_grupo in grupos.items():
        comision += D(ventas_grupo * D(pct) / D(100))
    pagados = (
        db.query(Ticket)
        .filter(
            Ticket.estado == "pagado",
            Ticket.es_prueba.is_(prueba),
            Ticket.pagado_en.isnot(None),
        )
        .all()
    )
    premios_pagados = D(0)
    pagados_vistos = set()
    for ticket in pagados:
        if ticket.id in pagados_vistos:
            continue
        pagados_vistos.add(ticket.id)
        if sucursal_id is not None and ticket.sucursal_vendedora_id != sucursal_id:
            continue
        if usuario_id is not None and ticket.usuario_id != usuario_id:
            continue
        if desde <= _dia_guardado(ticket.pagado_en) <= hasta:
            premios_pagados += D(ticket.premio_total)
    candidatos = (
        db.query(Ticket)
        .filter(
            Ticket.estado.in_(("ganador", "parcial")),
            Ticket.es_prueba.is_(prueba),
            Ticket.fecha >= desde,
            Ticket.fecha <= hasta,
        )
        .order_by(Ticket.id)
        .all()
    )
    premios_pendientes = D(0)
    pendientes_vistos = set()
    for ticket in candidatos:
        if ticket.id in pendientes_vistos:
            continue
        if sucursal_id is not None and ticket.sucursal_vendedora_id != sucursal_id:
            continue
        if usuario_id is not None and ticket.usuario_id != usuario_id:
            continue
        pendientes_vistos.add(ticket.id)
        if _premio_pendiente_valido(db, ticket):
            premios_pendientes += _importe_sin_cobrar(ticket)
    return {
        "ventas": str(D(ventas)),
        "tickets": len(tickets),
        "premios_pagados": str(D(premios_pagados)),
        "premios_pendientes": str(D(premios_pendientes)),
        "neto": str(D(ventas - premios_pagados)),
        "comision": str(D(comision)),
    }


def resumen_inicio(db, desde, hasta):
    """Resumen del panel. Reales y prueba viajan separados y esta lectura no escribe."""
    if hasta < desde:
        raise ErrorServicio(400, "La fecha hasta no puede ser anterior a la fecha desde")
    return {
        "zona": "America/Santo_Domingo",
        "hoy": ahora_local().date().isoformat(),
        "desde": desde.isoformat(),
        "hasta": hasta.isoformat(),
        "reales": _bloque_periodo(db, desde, hasta, False),
        "prueba": _bloque_periodo(db, desde, hasta, True),
    }


def reporte_resumen(db, desde, hasta, vista, sucursal_id=None, usuario_id=None):
    tickets = _tickets_rango(db, desde, hasta, sucursal_id, usuario_id)
    base = {"vista": vista, "desde": desde.isoformat(), "hasta": hasta.isoformat()}
    if vista == "final":
        vigentes = [t for t in tickets if t.estado != "anulado"]
        nulos = [t for t in tickets if t.estado == "anulado"]
        ventas = sum((D(t.total) for t in vigentes), D(0))
        premios_pagados = sum((D(t.premio_total) for t in tickets if t.estado == "pagado"), D(0))
        premios_pendientes = sum(
            (_importe_sin_cobrar(t) for t in tickets if t.estado in ("ganador", "parcial")), D(0),
        )
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
        elegidos = [t for t in tickets if t.estado in ("ganador", "parcial", "pagado")]
    elif vista == "ganadores":  # ganadores aún sin pagar
        elegidos = [t for t in tickets if t.estado in ("ganador", "parcial")]
    elif vista == "pagados":
        elegidos = [t for t in tickets if t.estado == "pagado"]
    elif vista == "nulos":
        elegidos = [t for t in tickets if t.estado == "anulado"]
    else:
        raise ErrorServicio(400, f"Vista de reporte no válida: {vista}")
    base["tickets"] = [_ticket_resumen(db, t) for t in elegidos]
    base["cantidad"] = len(elegidos)
    if vista == "ganadores":
        monto = sum((_importe_sin_cobrar(t) for t in elegidos), D(0))
    elif vista == "nulos":
        monto = sum((D(t.total) for t in elegidos), D(0))
    else:
        monto = sum((D(t.premio_total) for t in elegidos), D(0))
    base["monto_total"] = str(D(monto))
    return base


def reporte_pendientes(db, desde, hasta, sucursal_id, usuario_id=None):
    tickets = _tickets_rango(db, desde, hasta, sucursal_id, usuario_id)
    pendientes = [t for t in tickets if t.estado in ("ganador", "parcial")]
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
        "monto_pendiente": str(D(sum((_importe_sin_cobrar(t) for t in pendientes), D(0)))),
        "pagados_en_otra": [_ticket_resumen(db, t) for t in pagados_en_otra],
        "pagado_en_otra_monto": str(D(sum((D(t.premio_total) for t in pagados_en_otra), D(0)))),
        "total_pagado": str(D(sum((D(t.premio_total) for t in pagados), D(0)))),
    }


def pendientes_texto(db, desde, hasta, sucursal_id, terminal=None, usuario_id=None):
    """Formato de texto imprimible en la térmica, como el observado en video 3."""
    sucursal = db.get(Sucursal, sucursal_id)
    rep = reporte_pendientes(db, desde, hasta, sucursal_id, usuario_id)
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


def _alcance_admin(usuario, sucursal_id):
    if usuario is None or usuario.rol not in ("admin", "supervisor"):
        raise ErrorServicio(403, "Su rol no puede consultar la administración")
    if usuario.rol == "supervisor":
        if not usuario.sucursal_id:
            raise ErrorServicio(403, "El supervisor no tiene sucursal asignada")
        if sucursal_id is not None and int(sucursal_id) != usuario.sucursal_id:
            raise ErrorServicio(403, "Solo puede consultar su sucursal")
        return usuario.sucursal_id
    return sucursal_id


def _ultima_actividad(db, usuario_id):
    venta = db.query(func.max(Ticket.vendido_en)).filter(Ticket.usuario_id == usuario_id).scalar()
    movimiento = db.query(func.max(MovimientoCajera.creado_en)).filter(MovimientoCajera.usuario_id == usuario_id).scalar()
    momentos = [m for m in (venta, movimiento) if m is not None]
    if not momentos:
        return None
    return max(momentos).isoformat(sep=" ")


def _lineas_periodo(bloque):
    return [
        f"Vendido RD${bloque['ventas']}",
        f"Tickets {bloque['tickets']}",
        f"Premios pagados RD${bloque['premios_pagados']}",
        f"Premios pendientes RD${bloque['premios_pendientes']}",
        f"Neto RD${bloque['neto']}",
        f"Comisión RD${bloque['comision']}",
    ]


def panel_movil(db, usuario, seccion, desde, hasta, sucursal_id=None, usuario_id=None, texto=""):
    """Lectura del administrador en el teléfono. No vende, no paga y no mezcla las cajas."""
    if hasta < desde:
        raise ErrorServicio(400, "La fecha hasta no puede ser anterior a la fecha desde")
    sucursal_id = _alcance_admin(usuario, sucursal_id)
    seccion = (seccion or "inicio").strip().lower()
    if seccion not in ("inicio", "ventas", "cajeras", "tickets", "premios", "caja", "reportes", "resultados"):
        raise ErrorServicio(400, "Sección desconocida")
    reales = _bloque_periodo(db, desde, hasta, False, sucursal_id, usuario_id)
    prueba = _bloque_periodo(db, desde, hasta, True, sucursal_id, usuario_id)
    base = {
        "seccion": seccion,
        "desde": desde.isoformat(),
        "hasta": hasta.isoformat(),
        "reales": reales,
        "prueba": prueba,
    }
    if seccion in ("inicio", "ventas", "reportes"):
        jugadas_reales = _contar_jugadas(db, desde, hasta, False, sucursal_id, usuario_id)
        jugadas_prueba = _contar_jugadas(db, desde, hasta, True, sucursal_id, usuario_id)
        base["jugadas_reales"] = jugadas_reales
        base["jugadas_prueba"] = jugadas_prueba
        base["por_cajera"] = _ventas_por_cajera(db, desde, hasta, sucursal_id)
        base["por_sucursal"] = _ventas_por_sucursal(db, desde, hasta, sucursal_id)
        base["lineas"] = (
            [f"{desde.isoformat()} a {hasta.isoformat()}", "REALES"]
            + _lineas_periodo(reales)
            + [f"Jugadas {jugadas_reales}", "PRUEBA"]
            + _lineas_periodo(prueba)
            + [f"Jugadas {jugadas_prueba}"]
        )
        return base
    if seccion == "resultados":
        from . import estabilizacion, resultados_auto
        from .models import Ticket

        from datetime import timedelta
        from .models import Resultado

        observaciones = estabilizacion.resumen_observaciones(db, hasta)
        momento = ahora_local()
        proceso = resultados_auto.estado_reloj(db, momento)
        pendientes = (
            db.query(Ticket)
            .filter(Ticket.estado.in_(("ganador", "parcial")), Ticket.premio_total > 0)
            .count()
        )
        recientes = (
            db.query(Resultado)
            .filter(
                Resultado.fuente == "conectate",
                Resultado.fecha.in_([momento.date(), momento.date() - timedelta(days=1)]),
            )
            .all()
        )
        provisionales = sum(1 for fila in recientes if fila.estado not in ("confirmado", "liquidado"))
        confirmados = sum(1 for fila in recientes if fila.estado in ("confirmado", "liquidado"))
        sin_resultado = sum(1 for fila in observaciones if fila["estado"] == "PENDIENTE")
        errores = proceso.get("errores_recientes") or []
        lineas = [
            f"Reloj {proceso['reloj']}",
            f"Última ejecución {proceso.get('ultima_ejecucion') or '—'}",
            f"Última consulta exitosa {proceso.get('ultima_consulta_ok') or '—'}",
            f"Próxima estimada {proceso.get('proxima_estimada') or '—'}",
            f"Recibidos {len(recientes)} · provisionales {provisionales} · confirmados {confirmados}",
            f"Sin resultado {sin_resultado}",
            f"Errores {errores[0] if errores else 'ninguno'}",
            f"Premios pendientes {pendientes}",
        ]
        for fila in observaciones:
            numero = fila["confirmado"] or fila["provisional"] or "—"
            lineas.append(
                f"{fila['sorteo']} · {fila['estado']} · {numero} · "
                f"lecturas {fila['lecturas']} · {fila['fuente'] or 'sin fuente'}"
            )
        base["observaciones"] = observaciones
        base["proceso"] = proceso
        base["premios_detectados"] = pendientes
        base["lineas"] = lineas
        return base
    if seccion == "cajeras":
        gente = []
        consulta = db.query(Usuario).filter(Usuario.rol == "operador").order_by(Usuario.nombre)
        if sucursal_id is not None:
            consulta = consulta.filter(Usuario.sucursal_id == sucursal_id)
        if usuario_id is not None:
            consulta = consulta.filter(Usuario.id == usuario_id)
        for cajera in consulta.all():
            sucursal = db.get(Sucursal, cajera.sucursal_id) if cajera.sucursal_id else None
            propios_reales = _bloque_periodo(db, desde, hasta, False, cajera.sucursal_id, cajera.id)
            propios_prueba = _bloque_periodo(db, desde, hasta, True, cajera.sucursal_id, cajera.id)
            gente.append({
                "id": cajera.id,
                "nombre": cajera.nombre,
                "usuario": cajera.usuario,
                "sucursal": sucursal.nombre if sucursal else "",
                "activo": bool(cajera.activo),
                "vendido_real": propios_reales["ventas"],
                "tickets_reales": propios_reales["tickets"],
                "premios_pagados_reales": propios_reales["premios_pagados"],
                "saldo_caja": str(D(cajera.saldo_caja or 0)),
                "saldo_caja_prueba": str(D(cajera.saldo_caja_prueba or 0)),
                "vendido_prueba": propios_prueba["ventas"],
                "tickets_prueba": propios_prueba["tickets"],
                "ultima_actividad": _ultima_actividad(db, cajera.id),
            })
        base["cajeras"] = gente
        base["lineas"] = [
            f"{c['nombre']} · {c['sucursal']} · {'activa' if c['activo'] else 'inactiva'} · "
            f"real RD${c['vendido_real']} · prueba RD${c['vendido_prueba']} · "
            f"caja RD${c['saldo_caja']} · prueba RD${c['saldo_caja_prueba']}"
            for c in gente
        ]
        return base
    if seccion == "tickets":
        filas = _buscar_tickets(db, desde, hasta, sucursal_id, usuario_id, texto)
        base["tickets"] = filas
        base["lineas"] = [
            f"#{t['id']} {t['serial']} {t['cajera']} {t['sucursal']} {t['estado']} RD${t['total']}"
            + (" PRUEBA" if t["es_prueba"] else "")
            for t in filas
        ]
        return base
    if seccion == "premios":
        premios = listar_ganadores(db, sucursal_id=sucursal_id, usuario_id=usuario_id)
        base["premios"] = premios
        base["lineas"] = [
            "REALES pendientes RD$" + premios["premios_pendientes"],
            "REALES pagados RD$" + premios["premios_pagados"],
            "PRUEBA " + str(len(premios["prueba"])) + " tickets",
        ]
        return base
    fondos = listar_fondos(db, sucursal_id, usuario_id)
    entregas = listar_entregas(db, usuario, sucursal_id)
    comisiones = resumen_comisiones(db, desde, hasta, sucursal_id, usuario_id)
    cuadres = db.query(Cuadre).order_by(Cuadre.id.desc())
    if sucursal_id is not None:
        cuadres = cuadres.filter(Cuadre.sucursal_id == sucursal_id)
    cuadres = [cuadre_a_dict(c) for c in cuadres.limit(20).all()]
    sucursales = []
    consulta_suc = db.query(Sucursal).order_by(Sucursal.codigo)
    if sucursal_id is not None:
        consulta_suc = consulta_suc.filter(Sucursal.id == sucursal_id)
    for sucursal in consulta_suc.all():
        cajas = consolidado_cajas(db, sucursal.id)
        sucursales.append({
            "id": sucursal.id,
            "nombre": sucursal.nombre,
            "caja_general": str(D(sucursal.saldo_actual)),
            "cajas_reales": cajas["cajas_reales"],
            "cajas_prueba": cajas["cajas_prueba"],
        })
    base["sucursales"] = sucursales
    base["fondos"] = fondos
    base["entregas"] = entregas
    base["comisiones"] = comisiones
    base["cuadres"] = cuadres
    lineas = []
    for sucursal in sucursales:
        lineas.append(
            f"{sucursal['nombre']} general RD${sucursal['caja_general']} · "
            f"cajeras RD${sucursal['cajas_reales']} · prueba RD${sucursal['cajas_prueba']}"
        )
    lineas.append(f"Fondos {len(fondos)}")
    lineas.append(f"Entregas {len(entregas['reales']) + len(entregas['prueba'])}")
    for cuadre in cuadres:
        if cuadre["diferencia"] is not None:
            lineas.append(f"Cuadre {cuadre['fecha']} diferencia RD${cuadre['diferencia']}")
    base["lineas"] = lineas
    return base


def _contar_jugadas(db, desde, hasta, prueba, sucursal_id, usuario_id):
    consulta = (
        db.query(Jugada)
        .join(Ticket, Jugada.ticket_id == Ticket.id)
        .filter(
            Ticket.fecha >= desde,
            Ticket.fecha <= hasta,
            Ticket.es_prueba.is_(prueba),
            Ticket.estado != "anulado",
        )
    )
    if sucursal_id is not None:
        consulta = consulta.filter(Ticket.sucursal_vendedora_id == sucursal_id)
    if usuario_id is not None:
        consulta = consulta.filter(Ticket.usuario_id == usuario_id)
    return consulta.count()


def _ventas_por_cajera(db, desde, hasta, sucursal_id):
    consulta = db.query(Usuario).filter(Usuario.rol == "operador").order_by(Usuario.nombre)
    if sucursal_id is not None:
        consulta = consulta.filter(Usuario.sucursal_id == sucursal_id)
    filas = []
    for cajera in consulta.all():
        reales = _bloque_periodo(db, desde, hasta, False, cajera.sucursal_id, cajera.id)
        prueba = _bloque_periodo(db, desde, hasta, True, cajera.sucursal_id, cajera.id)
        filas.append({
            "usuario_id": cajera.id,
            "nombre": cajera.nombre,
            "real": reales["ventas"],
            "prueba": prueba["ventas"],
            "tickets_reales": reales["tickets"],
            "tickets_prueba": prueba["tickets"],
        })
    return filas


def _ventas_por_sucursal(db, desde, hasta, sucursal_id):
    consulta = db.query(Sucursal).order_by(Sucursal.codigo)
    if sucursal_id is not None:
        consulta = consulta.filter(Sucursal.id == sucursal_id)
    filas = []
    for sucursal in consulta.all():
        reales = _bloque_periodo(db, desde, hasta, False, sucursal.id, None)
        prueba = _bloque_periodo(db, desde, hasta, True, sucursal.id, None)
        filas.append({
            "sucursal_id": sucursal.id,
            "nombre": sucursal.nombre,
            "real": reales["ventas"],
            "prueba": prueba["ventas"],
        })
    return filas


def _buscar_tickets(db, desde, hasta, sucursal_id, usuario_id, texto):
    consulta = db.query(Ticket).filter(Ticket.fecha >= desde, Ticket.fecha <= hasta)
    if sucursal_id is not None:
        consulta = consulta.filter(Ticket.sucursal_vendedora_id == sucursal_id)
    if usuario_id is not None:
        consulta = consulta.filter(Ticket.usuario_id == usuario_id)
    texto = (texto or "").strip()
    if texto.isdigit():
        consulta = consulta.filter(Ticket.id == int(texto))
    elif texto:
        like = f"%{texto.lower()}%"
        consulta = (
            consulta.outerjoin(Usuario, Ticket.usuario_id == Usuario.id)
            .outerjoin(Sucursal, Ticket.sucursal_vendedora_id == Sucursal.id)
            .filter(or_(
                func.lower(Ticket.serial).like(like),
                func.lower(Usuario.nombre).like(like),
                func.lower(Sucursal.nombre).like(like),
            ))
        )
    filas = []
    for ticket in consulta.order_by(Ticket.id.desc()).limit(80).all():
        cajera = db.get(Usuario, ticket.usuario_id) if ticket.usuario_id else None
        sucursal = ticket.sucursal_vendedora
        jugadas = []
        for jugada in ticket.jugadas:
            loterias = [jugada.sorteo.nombre] if jugada.sorteo else []
            if jugada.sorteo2 is not None:
                loterias.append(jugada.sorteo2.nombre)
            jugadas.append({
                "tipo": jugada.tipo.codigo if jugada.tipo else "",
                "numeros": jugada.numeros,
                "monto": str(D(jugada.monto)),
                "loterias": loterias,
                "premio": str(D(jugada.premio or 0)),
            })
        filas.append({
            "id": ticket.id,
            "serial": ticket.serial,
            "cajera": cajera.nombre if cajera else "",
            "sucursal": sucursal.nombre if sucursal else "",
            "vendido_en": ticket.vendido_en.isoformat(sep=" ") if ticket.vendido_en else "",
            "fecha": ticket.fecha.isoformat(),
            "total": str(D(ticket.total)),
            "estado": ticket.estado,
            "premio_total": str(D(ticket.premio_total)),
            "es_prueba": bool(ticket.es_prueba),
            "jugadas": jugadas,
        })
    return filas
