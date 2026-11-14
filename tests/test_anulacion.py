"""Anulación: solo antes del cierre de TODOS los sorteos, con reverso de saldo."""
from datetime import datetime


def test_anular_antes_del_cierre_devuelve_saldo(entorno):
    b = entorno.banca(saldo=1000)
    s = entorno.sorteo_id("La Primera 12")
    t = entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [s], "numeros": "19", "monto": 100}])
    assert entorno.saldo(b["sucursal"]["id"]) == 900.00
    r = entorno.c.post("/terminal/tickets/anular",
                       json={"id": t["id"], "serial": t["serial"]}, headers=b["headers"])
    assert r.status_code == 200, r.text
    assert r.json()["estado"] == "anulado"
    assert entorno.saldo(b["sucursal"]["id"]) == 1000.00  # reverso completo
    movs = entorno.c.get(f"/sucursales/{b['sucursal']['id']}/movimientos", headers=entorno.admin).json()
    credito = [m for m in movs if m["tipo"] == "credito_anulacion"]
    assert len(credito) == 1 and float(credito[0]["monto"]) == 100.00
    # Y aparece como nulo en los reportes
    rep = entorno.c.get("/reportes/resumen?desde=2026-11-14&hasta=2026-11-14&vista=nulos",
                        headers=entorno.admin).json()
    assert rep["cantidad"] == 1 and rep["tickets"][0]["id"] == t["id"]


def test_anular_despues_del_cierre_rechazado(entorno, fijar_hora):
    b = entorno.banca(saldo=1000)
    s = entorno.sorteo_id("La Primera 12")  # cierra 11:50
    t = entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [s], "numeros": "19", "monto": 10}])
    fijar_hora(datetime(2026, 11, 14, 12, 5))  # ya cerró
    r = entorno.c.post("/terminal/tickets/anular",
                       json={"id": t["id"], "serial": t["serial"]}, headers=b["headers"])
    assert r.status_code == 409 and "ya cerró" in r.json()["detail"]
    assert entorno.consultar(t)["estado"] == "vendido"
    assert entorno.saldo(b["sucursal"]["id"]) == 990.00


def test_anular_con_un_solo_sorteo_cerrado_rechazado(entorno, fijar_hora):
    b = entorno.banca(saldo=1000)
    s1 = entorno.sorteo_id("La Primera 12")   # cierra 11:50
    s2 = entorno.sorteo_id("Nacional Noche")  # cierra 20:50
    t = entorno.vender_ok(b["headers"], [
        {"tipo": "SP", "sorteos": [s1, s2], "numeros": "26-58", "monto": 10},
    ])
    fijar_hora(datetime(2026, 11, 14, 12, 5))  # cerró s1, s2 sigue abierto
    r = entorno.c.post("/terminal/tickets/anular",
                       json={"id": t["id"], "serial": t["serial"]}, headers=b["headers"])
    assert r.status_code == 409 and "La Primera 12" in r.json()["detail"]


def test_anular_dos_veces_rechazado(entorno):
    b = entorno.banca(saldo=1000)
    s = entorno.sorteo_id("La Primera 12")
    t = entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [s], "numeros": "19", "monto": 10}])
    r = entorno.c.post("/terminal/tickets/anular",
                       json={"id": t["id"], "serial": t["serial"]}, headers=b["headers"])
    assert r.status_code == 200
    r = entorno.c.post("/terminal/tickets/anular",
                       json={"id": t["id"], "serial": t["serial"]}, headers=b["headers"])
    assert r.status_code == 409 and "ya está anulado" in r.json()["detail"]


def test_anular_pagado_rechazado(entorno):
    b = entorno.banca()
    s = entorno.sorteo_id("La Primera 12")
    t = entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [s], "numeros": "19", "monto": 10}])
    entorno.liquidar(s, 19, 3, 45)
    r = entorno.c.post("/terminal/tickets/pagar",
                       json={"id": t["id"], "serial": t["serial"]}, headers=b["headers"])
    assert r.status_code == 200
    r = entorno.c.post("/terminal/tickets/anular",
                       json={"id": t["id"], "serial": t["serial"]}, headers=b["headers"])
    assert r.status_code == 409 and "ya fue pagado" in r.json()["detail"]


def test_ticket_anulado_no_cuenta_para_el_limite(entorno):
    b = entorno.banca(saldo=100000)
    s = entorno.sorteo_id("La Primera 12")
    entorno.c.post("/limites", json={
        "sorteo_id": s, "tipo": "QN", "numeros": "26", "monto_max_acumulado": 100,
    }, headers=entorno.admin)
    t = entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [s], "numeros": "26", "monto": 60}])
    entorno.c.post("/terminal/tickets/anular",
                   json={"id": t["id"], "serial": t["serial"]}, headers=b["headers"])
    # Si el anulado contara, esta venta de $60 pasaría el límite de $100
    entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [s], "numeros": "26", "monto": 60}])
