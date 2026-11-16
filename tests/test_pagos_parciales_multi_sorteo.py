"""Pagos parciales por sorteo: un premio confirmado se cobra sin esperar a los demás."""
import threading

from apps.api import db as dbmod
from apps.api import servicios
from apps.api.comun import ErrorServicio


def _simular(entorno, sorteo_id, p1, p2, p3):
    r = entorno.c.post("/resultados", json={
        "sorteo_id": sorteo_id, "fecha": "2026-11-14",
        "premio1": p1, "premio2": p2, "premio3": p3, "simulado": True,
    }, headers=entorno.admin)
    assert r.status_code == 201, r.text


def _preparar(entorno):
    b = entorno.banca(saldo=5764, nombre="BANCA CASTILLO (PRUEBA)", usuario="0219", clave="prueba123")
    jose = next(f for f in entorno.c.get("/usuarios", headers=entorno.admin).json() if f["usuario"] == "0219")
    fondo = entorno.c.post("/fondos", json={
        "sucursal_id": b["sucursal"]["id"], "usuario_id": jose["id"], "monto": 20000,
        "tipo": "aporte_prueba", "operacion_id": "fondo-parcial-multi",
    }, headers=entorno.admin)
    assert fondo.status_code == 201, fondo.text
    return b


def _consultar(entorno, headers, ticket):
    r = entorno.c.post("/terminal/tickets/consultar", json={
        "id": ticket["id"], "serial": ticket["serial"],
    }, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _pagar(entorno, headers, ticket, op):
    return entorno.c.post("/terminal/tickets/pagar", json={
        "id": ticket["id"], "serial": ticket["serial"], "operacion_id": op,
    }, headers=headers)


def test_tres_sorteos_solo_uno_ganador_se_paga_ya(entorno, monkeypatch):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    b = _preparar(entorno)
    a11 = entorno.sorteo_id("La Anguila 11:00 AM")
    a12 = entorno.sorteo_id("La Anguila 12:00 PM")
    a13 = entorno.sorteo_id("La Anguila 1:00 PM")
    ticket = entorno.vender_ok(b["headers"], [
        {"tipo": "QN", "sorteos": [a11, a12, a13], "numeros": "25", "monto": 5},
    ])
    _simular(entorno, a11, 25, 1, 2)
    vista = _consultar(entorno, b["headers"], ticket)
    assert vista["estado"] == "ganador"
    assert vista["puede_pagar"] is True
    assert vista["premio_pendiente"] == "300.00"
    assert len(vista["sorteos_pendientes"]) == 2
    assert float(entorno.c.get("/terminal/sorteos", headers=b["headers"]).json()["premios_por_pagar"]) == 300
    pago = _pagar(entorno, b["headers"], ticket, "op-anguila-11")
    assert pago.status_code == 200, pago.text
    assert pago.json()["estado"] == "parcial"
    assert pago.json()["premio_pendiente"] == "0.00"
    assert float(pago.json()["premios_por_pagar"]) == 0
    reescaneo = _consultar(entorno, b["headers"], ticket)
    assert "Estado: PAGADO" in reescaneo["texto_pago"]
    assert "SORTEOS PENDIENTES" in reescaneo["texto_pago"]
    assert reescaneo["puede_pagar"] is False


def test_segundo_sorteo_se_paga_despues_sin_repetir_el_primero(entorno, monkeypatch):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    b = _preparar(entorno)
    a11 = entorno.sorteo_id("La Anguila 11:00 AM")
    a12 = entorno.sorteo_id("La Anguila 12:00 PM")
    a13 = entorno.sorteo_id("La Anguila 1:00 PM")
    ticket = entorno.vender_ok(b["headers"], [
        {"tipo": "QN", "sorteos": [a11, a12, a13], "numeros": "25", "monto": 5},
    ])
    _simular(entorno, a11, 25, 1, 2)
    caja0 = float(entorno.c.get("/terminal/sorteos", headers=b["headers"]).json()["mi_caja"])
    assert _pagar(entorno, b["headers"], ticket, "op-1").status_code == 200
    _simular(entorno, a12, 25, 3, 4)
    medio = _consultar(entorno, b["headers"], ticket)
    assert medio["estado"] == "parcial"
    assert medio["premio_pendiente"] == "300.00"
    assert medio["premio_pagado"] == "300.00"
    assert float(entorno.c.get("/terminal/sorteos", headers=b["headers"]).json()["premios_por_pagar"]) == 300
    segundo = _pagar(entorno, b["headers"], ticket, "op-2")
    assert segundo.status_code == 200, segundo.text
    assert segundo.json()["premio_pagado"] == "600.00"
    assert float(segundo.json()["mi_caja"]) == caja0 - 600
    _simular(entorno, a13, 99, 8, 9)
    final = _consultar(entorno, b["headers"], ticket)
    assert final["puede_pagar"] is False
    assert final["estado"] == "parcial" or final["estado"] == "pagado"
    # El 13 no ganó: si ya no hay impagos y todas evaluadas → pagado
    assert final["estado"] == "pagado"
    doble = _pagar(entorno, b["headers"], ticket, "op-doble")
    assert doble.status_code == 409


def test_varias_jugadas_del_mismo_sorteo_se_cobran_juntas(entorno, monkeypatch):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    b = _preparar(entorno)
    loteria = entorno.sorteo_id("LOTEDOM")
    ticket = entorno.vender_ok(b["headers"], [
        {"tipo": "QN", "sorteos": [loteria], "numeros": "25", "monto": 10},
        {"tipo": "QN", "sorteos": [loteria], "numeros": "25", "monto": 5},
    ])
    _simular(entorno, loteria, 25, 1, 2)
    vista = _consultar(entorno, b["headers"], ticket)
    assert vista["premio_pendiente"] == "900.00"
    assert vista["texto_pago"].count("Estado: PENDIENTE DE PAGO") == 2
    pago = _pagar(entorno, b["headers"], ticket, "op-doble-jugada")
    assert pago.status_code == 200
    assert pago.json()["estado"] == "pagado"


def test_dos_cajeros_solo_uno_cobra(entorno, monkeypatch):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    b = _preparar(entorno)
    loteria = entorno.sorteo_id("LOTEDOM")
    ticket = entorno.vender_ok(b["headers"], [
        {"tipo": "QN", "sorteos": [loteria], "numeros": "25", "monto": 10},
    ])
    _simular(entorno, loteria, 25, 54, 78)
    jose = next(f for f in entorno.c.get("/usuarios", headers=entorno.admin).json() if f["usuario"] == "0219")
    resultados = []
    barrera = threading.Barrier(2)

    def intento():
        db = dbmod.nueva_sesion()
        try:
            barrera.wait(timeout=10)
            servicios.pagar_ticket(
                db, ticket["id"], ticket["serial"], b["sucursal"]["id"], None, jose["id"],
            )
            resultados.append("ok")
        except ErrorServicio as exc:
            resultados.append(exc.status)
        finally:
            db.close()

    hilos = [threading.Thread(target=intento), threading.Thread(target=intento)]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join(timeout=30)
    assert resultados.count("ok") == 1, resultados
    assert resultados.count(409) == 1, resultados
