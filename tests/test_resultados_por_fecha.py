"""Un resultado del día 14 NUNCA hace ganar un ticket del día 15."""
from datetime import datetime, timedelta

from apps.api import db as dbmod
from apps.api import motor
from apps.api.models import Jugada, Resultado, Sesion


def _extender_sesiones(momento):
    """Al mover el reloj, las sesiones de prueba no deben vencer por fecha."""
    db = dbmod.nueva_sesion()
    limite = momento + timedelta(days=2)
    for sesion in db.query(Sesion).all():
        sesion.expira_en = limite
    db.commit()
    db.close()


def _mover(fijar_hora, momento):
    fijar_hora(momento)
    _extender_sesiones(momento)


def _consultar(entorno, headers, ticket):
    r = entorno.c.post("/terminal/tickets/consultar", json={
        "id": ticket["id"], "serial": ticket["serial"],
    }, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def test_resultado_dia_14_no_hace_ganar_ticket_dia_15(entorno, fijar_hora):
    b = entorno.banca(saldo=10000)
    sorteo = entorno.sorteo_id("La Anguila 1:00 PM")

    _mover(fijar_hora, datetime(2026, 11, 14, 10, 0, 0))
    t14 = entorno.vender_ok(b["headers"], [
        {"tipo": "QN", "sorteos": [sorteo], "numeros": "25", "monto": 10},
    ])
    entorno.liquidar(sorteo, 25, 48, 90, fecha="2026-11-14")
    c14 = entorno.consultar(t14)
    assert c14["estado"] == "ganador"
    assert float(c14["premio_total"]) == 600.00

    _mover(fijar_hora, datetime(2026, 11, 15, 10, 0, 0))
    t15 = entorno.vender_ok(b["headers"], [
        {"tipo": "QN", "sorteos": [sorteo], "numeros": "25", "monto": 10},
    ])
    pendiente = _consultar(entorno, b["headers"], t15)
    assert pendiente["estado"] == "vendido"
    assert pendiente["puede_pagar"] is False
    assert float(pendiente["premio_total"]) == 0
    assert float(pendiente["premio_pendiente"]) == 0
    assert "PENDIENTE DE SORTEO" in pendiente["texto_pago"]
    assert "25-48-90" not in pendiente["texto_pago"]

    # Reliquidar el 14 no debe tocar el ticket del 15.
    db = dbmod.nueva_sesion()
    fila14 = db.query(Resultado).filter_by(sorteo_id=sorteo, fecha=datetime(2026, 11, 14).date()).one()
    motor.liquidar_resultado(db, fila14)
    db.commit()
    db.close()
    sigue = entorno.consultar(t15)
    assert sigue["estado"] == "vendido"
    assert float(sigue["premio_total"]) == 0

    entorno.liquidar(sorteo, 11, 22, 33, fecha="2026-11-15")
    sin_premio = entorno.consultar(t15)
    assert sin_premio["estado"] == "no_ganador"
    assert float(sin_premio["premio_total"]) == 0
    assert entorno.consultar(t14)["estado"] == "ganador"


def test_mismo_numero_dia_15_con_resultado_coincidente_si_gana(entorno, fijar_hora):
    b = entorno.banca(saldo=10000)
    sorteo = entorno.sorteo_id("La Anguila 1:00 PM")
    _mover(fijar_hora, datetime(2026, 11, 14, 10, 0, 0))
    entorno.liquidar(sorteo, 25, 48, 90, fecha="2026-11-14")

    _mover(fijar_hora, datetime(2026, 11, 15, 10, 0, 0))
    t15 = entorno.vender_ok(b["headers"], [
        {"tipo": "QN", "sorteos": [sorteo], "numeros": "25", "monto": 10},
    ])
    assert entorno.consultar(t15)["estado"] == "vendido"
    entorno.liquidar(sorteo, 25, 1, 2, fecha="2026-11-15")
    gana = entorno.consultar(t15)
    assert gana["estado"] == "ganador"
    assert float(gana["premio_total"]) == 600.00


def test_ticket_ganador_del_14_se_cobra_el_16(entorno, fijar_hora, monkeypatch):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    b = entorno.banca(saldo=5764, nombre="BANCA CASTILLO (PRUEBA)", usuario="0219", clave="prueba123")
    jose = next(f for f in entorno.c.get("/usuarios", headers=entorno.admin).json() if f["usuario"] == "0219")
    fondo = entorno.c.post("/fondos", json={
        "sucursal_id": b["sucursal"]["id"], "usuario_id": jose["id"], "monto": 20000,
        "tipo": "aporte_prueba", "operacion_id": "fondo-fecha-14",
    }, headers=entorno.admin)
    assert fondo.status_code == 201, fondo.text
    sorteo = entorno.sorteo_id("La Anguila 1:00 PM")

    _mover(fijar_hora, datetime(2026, 11, 14, 10, 0, 0))
    ticket = entorno.vender_ok(b["headers"], [
        {"tipo": "QN", "sorteos": [sorteo], "numeros": "25", "monto": 10},
    ])
    sim = entorno.c.post("/resultados", json={
        "sorteo_id": sorteo, "fecha": "2026-11-14",
        "premio1": 25, "premio2": 48, "premio3": 90, "simulado": True,
    }, headers=entorno.admin)
    assert sim.status_code == 201, sim.text

    _mover(fijar_hora, datetime(2026, 11, 16, 10, 0, 0))
    vista = _consultar(entorno, b["headers"], ticket)
    assert vista["puede_pagar"] is True
    assert vista["premio_pendiente"] == "600.00"
    pago = entorno.c.post("/terminal/tickets/pagar", json={
        "id": ticket["id"], "serial": ticket["serial"], "operacion_id": "cobro-16",
    }, headers=b["headers"])
    assert pago.status_code == 200, pago.text
    assert pago.json()["estado"] == "pagado"
    otra = entorno.c.post("/terminal/tickets/pagar", json={
        "id": ticket["id"], "serial": ticket["serial"], "operacion_id": "cobro-16b",
    }, headers=b["headers"])
    assert otra.status_code == 409


def test_dos_horarios_misma_loteria_no_mezclan_fechas(entorno, fijar_hora):
    b = entorno.banca(saldo=10000)
    am = entorno.sorteo_id("La Anguila 11:00 AM")
    pm = entorno.sorteo_id("La Anguila 1:00 PM")
    _mover(fijar_hora, datetime(2026, 11, 14, 10, 0, 0))
    t = entorno.vender_ok(b["headers"], [
        {"tipo": "QN", "sorteos": [am, pm], "numeros": "25", "monto": 5},
    ])
    entorno.liquidar(am, 25, 1, 2, fecha="2026-11-14")
    c = entorno.consultar(t)
    assert c["estado"] == "ganador"
    assert float(c["premio_total"]) == 300.00
    assert c["puede_pagar"] is True
    _mover(fijar_hora, datetime(2026, 11, 15, 10, 0, 0))
    # Resultado del 15 en el horario AM no debe cambiar el premio del ticket del 14.
    entorno.liquidar(am, 25, 8, 9, fecha="2026-11-15")
    igual = entorno.consultar(t)
    assert igual["estado"] == "ganador"
    assert float(igual["premio_total"]) == 300.00


def test_super_pale_exige_misma_fecha_en_ambas_loterias(entorno, fijar_hora):
    b = entorno.banca(saldo=10000)
    a = entorno.sorteo_id("NY Tarde")
    bote = entorno.sorteo_id("Nacional Tarde")
    _mover(fijar_hora, datetime(2026, 11, 14, 10, 0, 0))
    ticket = entorno.vender_ok(b["headers"], [
        {"tipo": "SP", "sorteos": [a, bote], "numeros": "12-38", "monto": 5},
    ])
    entorno.liquidar(a, 12, 1, 2, fecha="2026-11-14")
    # Solo una lotería del 14: el SP sigue pendiente.
    assert entorno.consultar(ticket)["estado"] == "vendido"
    _mover(fijar_hora, datetime(2026, 11, 15, 10, 0, 0))
    # Resultado del 15 en la segunda lotería NO completa el SP del 14.
    entorno.liquidar(bote, 38, 11, 22, fecha="2026-11-15")
    assert entorno.consultar(ticket)["estado"] == "vendido"
    assert float(entorno.consultar(ticket)["premio_total"]) == 0
    _mover(fijar_hora, datetime(2026, 11, 14, 10, 0, 0))
    entorno.liquidar(bote, 38, 11, 22, fecha="2026-11-14")
    gana = entorno.consultar(ticket)
    assert gana["estado"] == "ganador"
    assert float(gana["premio_total"]) == 12500.00


def test_evaluar_jugada_rechaza_resultado_de_otra_fecha(entorno, fijar_hora):
    b = entorno.banca(saldo=10000)
    sorteo = entorno.sorteo_id("La Anguila 1:00 PM")
    _mover(fijar_hora, datetime(2026, 11, 15, 10, 0, 0))
    ticket = entorno.vender_ok(b["headers"], [
        {"tipo": "QN", "sorteos": [sorteo], "numeros": "25", "monto": 10},
    ])
    entorno.liquidar(sorteo, 25, 48, 90, fecha="2026-11-14")
    db = dbmod.nueva_sesion()
    jugada = db.query(Jugada).filter_by(ticket_id=ticket["id"]).one()
    viejo = db.query(Resultado).filter_by(sorteo_id=sorteo, fecha=datetime(2026, 11, 14).date()).one()
    try:
        motor.evaluar_jugada(jugada, viejo)
        raised = False
    except Exception:
        raised = True
    db.close()
    assert raised is True
    assert entorno.consultar(ticket)["estado"] == "vendido"


def test_terminal_no_muestra_numeros_de_ayer_como_hoy(entorno, fijar_hora):
    b = entorno.banca()
    sorteo = entorno.sorteo_id("La Anguila 1:00 PM")
    _mover(fijar_hora, datetime(2026, 11, 14, 10, 0, 0))
    entorno.liquidar(sorteo, 25, 48, 90, fecha="2026-11-14")
    _mover(fijar_hora, datetime(2026, 11, 15, 10, 0, 0))
    tablero = entorno.c.get("/terminal/resultados", headers=b["headers"]).json()
    assert "sorteos" in tablero, tablero
    fila = next(f for f in tablero["sorteos"] if f["nombre"] == "La Anguila 1:00 PM")
    assert fila["pendiente"] is True
    assert fila["vigente"] is False
    assert fila["premio1"] is None
    assert fila["fecha_anterior"] == "2026-11-14"
    assert fila["referencia"] == "25-48-90"
