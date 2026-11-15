"""Pantalla 0.3.13 y reversión de un pago parcial. Base aislada."""
import threading

from sqlalchemy import text
from sqlalchemy.exc import DatabaseError

from apps.api import db as dbmod
from apps.api import servicios
from apps.api.comun import ErrorServicio


def _preparar(entorno):
    b = entorno.banca(saldo=5764, nombre="BANCA CASTILLO (PRUEBA)", usuario="0219", clave="prueba123")
    jose = next(f for f in entorno.c.get("/usuarios", headers=entorno.admin).json() if f["usuario"] == "0219")
    fondo = entorno.c.post("/fondos", json={
        "sucursal_id": b["sucursal"]["id"], "usuario_id": jose["id"], "monto": 20000,
        "tipo": "aporte_prueba", "operacion_id": "fondo-sunmi",
    }, headers=entorno.admin)
    assert fondo.status_code == 201, fondo.text
    return b, jose["id"]


def _consultar(entorno, headers, ticket):
    r = entorno.c.post("/terminal/tickets/consultar", json={
        "id": ticket["id"], "serial": ticket["serial"],
    }, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _simular(entorno, sorteo_id, p1, p2, p3):
    r = entorno.c.post("/resultados", json={
        "sorteo_id": sorteo_id, "fecha": "2026-11-14",
        "premio1": p1, "premio2": p2, "premio3": p3, "simulado": True,
    }, headers=entorno.admin)
    assert r.status_code == 201, r.text


def _caja(entorno, headers):
    return float(entorno.c.get("/terminal/sorteos", headers=headers).json()["mi_caja"])


def test_la_pantalla_muestra_total_pagado_y_cobra_solo_el_pendiente(entorno, monkeypatch):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    b, _jose = _preparar(entorno)
    lotedom = entorno.sorteo_id("LOTEDOM")
    florida = entorno.sorteo_id("Florida Día")
    ticket = entorno.vender_ok(b["headers"], [
        {"tipo": "QN", "sorteos": [lotedom], "numeros": "25", "monto": 10},
        {"tipo": "QN", "sorteos": [lotedom], "numeros": "99", "monto": 10},
        {"tipo": "QN", "sorteos": [florida], "numeros": "25", "monto": 10},
    ])
    _simular(entorno, lotedom, 25, 54, 78)
    consulta = _consultar(entorno, b["headers"], ticket)
    assert consulta["importe_a_cobrar"] == "600.00"
    assert consulta["premio_pendiente"] == "600.00"
    assert consulta["premio_pagado"] == "0.00"
    assert "PREMIO TOTAL: RD$600.00" in consulta["texto_pago"]
    assert "PREMIO YA PAGADO: RD$0.00" in consulta["texto_pago"]
    assert "PREMIO PENDIENTE: RD$600.00" in consulta["texto_pago"]
    assert "SE COBRARÁ: RD$600.00" in consulta["texto_pago"]
    assert "Jugada: 99" not in consulta["texto_pago"]
    assert len(consulta["jugadas"]) == 3
    assert "Florida 2:30 PM" in consulta["texto_pago"]
    caja_real = entorno.saldo(b["sucursal"]["id"])
    antes = _caja(entorno, b["headers"])
    pago = entorno.c.post("/terminal/tickets/pagar", json={
        "id": ticket["id"], "serial": ticket["serial"], "operacion_id": "sunmi-parcial",
    }, headers=b["headers"])
    assert pago.status_code == 200, pago.text
    cuerpo = pago.json()
    assert cuerpo["importe_a_cobrar"] == "0.00"
    assert "PREMIO PAGADO: RD$600.00" in cuerpo["comprobante"]
    assert "PAGO PARCIAL" in cuerpo["comprobante"]
    assert _caja(entorno, b["headers"]) == antes - 600
    assert entorno.saldo(b["sucursal"]["id"]) == caja_real


def test_dos_cajeros_no_cobran_el_mismo_tramo(entorno, monkeypatch):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    b, jose = _preparar(entorno)
    otra = entorno.operador("caja2", "1234", b["sucursal"]["id"])
    fondo = entorno.c.post("/fondos", json={
        "sucursal_id": b["sucursal"]["id"], "usuario_id": otra["id"], "monto": 20000,
        "tipo": "aporte_prueba", "operacion_id": "fondo-caja2",
    }, headers=entorno.admin)
    assert fondo.status_code == 201, fondo.text
    loteria = entorno.sorteo_id("LOTEDOM")
    ticket = entorno.vender_ok(b["headers"], [
        {"tipo": "QN", "sorteos": [loteria], "numeros": "25", "monto": 10},
    ])
    _simular(entorno, loteria, 25, 54, 78)
    antes = _caja(entorno, b["headers"])
    resultados = []
    barrera = threading.Barrier(2)

    def intento(usuario_id):
        sesion = dbmod.nueva_sesion()
        try:
            barrera.wait(timeout=10)
            servicios.pagar_ticket(
                sesion, ticket["id"], ticket["serial"], b["sucursal"]["id"], None, usuario_id,
            )
            resultados.append("ok")
        except ErrorServicio as exc:
            resultados.append(exc.status)
        finally:
            sesion.close()

    hilos = [
        threading.Thread(target=intento, args=(jose,)),
        threading.Thread(target=intento, args=(otra["id"],)),
    ]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join(timeout=30)
    assert resultados.count("ok") == 1 and resultados.count(409) == 1, resultados
    otra_headers = entorno.login_terminal("caja2", "1234")
    assert _caja(entorno, b["headers"]) + _caja(entorno, otra_headers) == antes + 20000 - 600


def test_el_pago_parcial_sigue_despues_de_cerrar_la_sesion(entorno, monkeypatch):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    b, _jose = _preparar(entorno)
    primera = entorno.sorteo_id("La Primera 12")
    florida = entorno.sorteo_id("Florida Día")
    ticket = entorno.vender_ok(b["headers"], [
        {"tipo": "QN", "sorteos": [primera], "numeros": "25", "monto": 10},
        {"tipo": "QN", "sorteos": [florida], "numeros": "25", "monto": 10},
    ])
    _simular(entorno, primera, 25, 1, 2)
    antes = _caja(entorno, b["headers"])
    pago = entorno.c.post("/terminal/tickets/pagar", json={
        "id": ticket["id"], "serial": ticket["serial"], "operacion_id": "antes-reinicio",
    }, headers=b["headers"])
    assert pago.status_code == 200, pago.text
    dbmod.engine().dispose()
    consulta = _consultar(entorno, b["headers"], ticket)
    assert consulta["premio_pagado"] == "600.00"
    assert consulta["premio_pendiente"] == "0.00"
    assert consulta["importe_a_cobrar"] == "0.00"
    assert "Florida 2:30 PM" in consulta["texto_pago"]
    repetido = entorno.c.post("/terminal/tickets/pagar", json={
        "id": ticket["id"], "serial": ticket["serial"], "operacion_id": "despues-reinicio",
    }, headers=b["headers"])
    assert repetido.status_code == 409
    assert _caja(entorno, b["headers"]) == antes - 600
    _simular(entorno, florida, 25, 8, 9)
    resto = _consultar(entorno, b["headers"], ticket)
    assert resto["estado"] == "parcial"
    assert resto["premio_total"] == "1200.00"
    assert resto["premio_pagado"] == "600.00"
    assert resto["importe_a_cobrar"] == "600.00"
    assert "SE COBRARÁ: RD$600.00" in resto["texto_pago"]
    segundo = entorno.c.post("/terminal/tickets/pagar", json={
        "id": ticket["id"], "serial": ticket["serial"], "operacion_id": "resto-tras-reinicio",
    }, headers=b["headers"])
    assert segundo.status_code == 200, segundo.text
    assert "PREMIO PAGADO: RD$1200.00" in segundo.json()["comprobante"]
    assert _caja(entorno, b["headers"]) == antes - 1200


def test_varias_loterias_dejan_el_pendiente_fuera_del_cobro(entorno, monkeypatch):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    b, _jose = _preparar(entorno)
    lotedom = entorno.sorteo_id("LOTEDOM")
    primera = entorno.sorteo_id("La Primera 12")
    florida = entorno.sorteo_id("Florida Día")
    ticket = entorno.vender_ok(b["headers"], [
        {"tipo": "QN", "sorteos": [lotedom, primera, florida], "numeros": "25", "monto": 10},
        {"tipo": "QN", "sorteos": [lotedom], "numeros": "99", "monto": 5},
    ])
    _simular(entorno, lotedom, 25, 1, 2)
    _simular(entorno, primera, 25, 3, 4)
    consulta = _consultar(entorno, b["headers"], ticket)
    assert consulta["premio_total"] == "1200.00"
    assert consulta["importe_a_cobrar"] == "1200.00"
    assert "SE COBRARÁ: RD$1200.00" in consulta["texto_pago"]
    assert "PREMIO TOTAL: RD$1200.00" in consulta["texto_pago"]
    assert "Jugada: 99" not in consulta["texto_pago"]
    assert any(j["numeros"] == "99" for j in consulta["jugadas"])
    assert "Florida 2:30 PM" in consulta["texto_pago"]
    antes = _caja(entorno, b["headers"])
    pago = entorno.c.post("/terminal/tickets/pagar", json={
        "id": ticket["id"], "serial": ticket["serial"], "operacion_id": "varias",
    }, headers=b["headers"])
    assert pago.status_code == 200, pago.text
    assert "PREMIO PAGADO: RD$1200.00" in pago.json()["comprobante"]
    assert _caja(entorno, b["headers"]) == antes - 1200
    _simular(entorno, florida, 25, 8, 9)
    resto = _consultar(entorno, b["headers"], ticket)
    assert resto["estado"] == "parcial"
    assert resto["premio_total"] == "1800.00"
    assert resto["premio_pagado"] == "1200.00"
    assert resto["importe_a_cobrar"] == "600.00"
    assert "SE COBRARÁ: RD$600.00" in resto["texto_pago"]
    assert "PREMIO TOTAL: RD$1800.00" in resto["texto_pago"]
    assert "PREMIO YA PAGADO: RD$1200.00" in resto["texto_pago"]


def test_la_reversion_no_vuelve_a_cobrar_lo_ya_pagado(entorno, monkeypatch):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    b, _jose = _preparar(entorno)
    primera = entorno.sorteo_id("La Primera 12")
    florida = entorno.sorteo_id("Florida Día")
    ticket = entorno.vender_ok(b["headers"], [
        {"tipo": "QN", "sorteos": [primera], "numeros": "25", "monto": 10},
        {"tipo": "QN", "sorteos": [florida], "numeros": "25", "monto": 10},
    ])
    _simular(entorno, primera, 25, 1, 2)
    antes = _caja(entorno, b["headers"])
    caja_real = entorno.saldo(b["sucursal"]["id"])
    pago = entorno.c.post("/terminal/tickets/pagar", json={
        "id": ticket["id"], "serial": ticket["serial"], "operacion_id": "tramo-1",
    }, headers=b["headers"])
    assert pago.status_code == 200, pago.text
    _simular(entorno, florida, 25, 3, 4)
    consulta = _consultar(entorno, b["headers"], ticket)
    assert consulta["estado"] == "parcial"
    assert consulta["premio_total"] == "1200.00"
    assert consulta["importe_a_cobrar"] == "600.00"
    assert consulta["estado"] != "ganador"
    db = dbmod.nueva_sesion()
    db.execute(text("UPDATE tickets SET estado = 'ganador' WHERE id = :id"), {"id": ticket["id"]})
    db.commit()
    try:
        db.execute(text(
            "UPDATE usuarios SET saldo_caja_prueba = saldo_caja_prueba - 1200 WHERE usuario = '0219'"
        ))
        db.execute(text("UPDATE tickets SET estado = 'pagado' WHERE id = :id"), {"id": ticket["id"]})
        db.commit()
        raise AssertionError("el codigo anterior habria cerrado el ticket completo")
    except DatabaseError:
        db.rollback()
    db.close()
    assert _caja(entorno, b["headers"]) == antes - 600
    assert entorno.saldo(b["sucursal"]["id"]) == caja_real
    resto = entorno.c.post("/terminal/tickets/pagar", json={
        "id": ticket["id"], "serial": ticket["serial"], "operacion_id": "tramo-2",
    }, headers=b["headers"])
    assert resto.status_code == 200, resto.text
    assert resto.json()["estado"] == "pagado"
    assert "PREMIO PAGADO: RD$1200.00" in resto.json()["comprobante"]
    assert _caja(entorno, b["headers"]) == antes - 1200
    assert entorno.saldo(b["sucursal"]["id"]) == caja_real


def test_el_comprobante_suma_solo_lo_cobrado(entorno, monkeypatch):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    b, _jose = _preparar(entorno)
    loteria = entorno.sorteo_id("LOTEDOM")
    ticket = entorno.vender_ok(b["headers"], [
        {"tipo": "QN", "sorteos": [loteria], "numeros": "25", "monto": 10},
        {"tipo": "QN", "sorteos": [loteria], "numeros": "54", "monto": 10},
    ])
    _simular(entorno, loteria, 25, 54, 78)
    pago = entorno.c.post("/terminal/tickets/pagar", json={
        "id": ticket["id"], "serial": ticket["serial"], "operacion_id": "recibo-real",
    }, headers=b["headers"])
    assert pago.status_code == 200, pago.text
    texto = pago.json()["comprobante"]
    assert "PREMIO PAGADO: RD$700.00" in texto
    assert "Monto jugado: RD$10.00" in texto
    assert "Jugada: QUINIELA 25" in texto
    assert "Jugada: QUINIELA 54" in texto
    assert "99" not in texto
