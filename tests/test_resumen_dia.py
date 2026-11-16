"""El resumen del día solo lee. Premios por fecha de pago; no mezcla pruebas."""
from apps.api.models import Usuario
from apps.api import db as dbmod


def test_resumen_de_la_cajera_no_mueve_la_caja_ni_mezcla_pruebas(entorno, monkeypatch):
    b1 = entorno.banca(saldo=5764)
    s = entorno.sorteo_id("La Primera 12")
    vendido = entorno.vender_ok(b1["headers"], [
        {"tipo": "QN", "sorteos": [s], "numeros": "25", "monto": 10},
    ])
    anulado = entorno.vender_ok(b1["headers"], [
        {"tipo": "QN", "sorteos": [s], "numeros": "26", "monto": 15},
    ])
    entorno.c.post(
        "/terminal/tickets/anular",
        json={"id": anulado["id"], "serial": anulado["serial"], "motivo": "error"},
        headers=b1["headers"],
    )
    ganador = entorno.vender_ok(b1["headers"], [
        {"tipo": "QN", "sorteos": [s], "numeros": "19", "monto": 10},
    ])
    entorno.liquidar(s, 19, 3, 45)
    otra = entorno.banca(saldo=1000, codigo="2200", nombre="BANCA PEGUERO", usuario="vend2")
    pago = entorno.c.post(
        "/terminal/tickets/pagar",
        json={"id": ganador["id"], "serial": ganador["serial"]},
        headers=otra["headers"],
    )
    assert pago.status_code == 200, pago.text
    antes = entorno.saldo(b1["sucursal"]["id"])
    propio = entorno.c.get("/terminal/reportes/dia", headers=b1["headers"])
    assert propio.status_code == 200, propio.text
    datos = propio.json()
    assert datos["alcance"] == "cajera autenticada"
    assert datos["real"]["ventas"] == "20.00"
    # Premios por quien pagó (otra sucursal), no por quien vendió.
    assert datos["real"]["premios_pagados"] == "0.00"
    assert datos["real"]["pagado_en_otra"] == "600.00"
    assert datos["real"]["total_pagado"] == "0.00"
    assert datos["real"]["quedo"] == "20.00"
    assert datos["real"]["neto"] == "20.00"
    assert datos["real"]["premios_pendientes"] == "0.00"
    assert datos["prueba"] is None
    assert "PRUEBA — NO OFICIAL" not in datos["texto"]
    assert "VENTAS DEL DÍA: RD$20.00" in datos["texto"]
    assert "PREMIOS PAGADOS: RD$0.00" in datos["texto"]
    assert "QUEDÓ: RD$20.00" in datos["texto"]
    assert "PAGADO EN OTRA" not in datos["texto"]
    assert "TICKET" not in datos["texto"]
    assert "COMISI" not in datos["texto"].upper()
    assert entorno.saldo(b1["sucursal"]["id"]) == antes
    assert vendido["id"] != ganador["id"]
    ajeno = entorno.c.get("/terminal/reportes/dia", headers=otra["headers"]).json()
    assert ajeno["real"]["ventas"] == "0.00"
    assert ajeno["real"]["premios_pagados"] == "600.00"
    assert ajeno["real"]["quedo"] == "-600.00"
    prohibido = entorno.c.get("/terminal/reportes/dia?alcance=sucursal", headers=b1["headers"])
    assert prohibido.status_code == 403

    monkeypatch.setenv("MODO_DESARROLLO", "true")
    prueba = entorno.vender_ok(b1["headers"], [
        {"tipo": "QN", "sorteos": [s], "numeros": "25", "monto": 50},
    ])
    assert prueba["es_prueba"] is True
    mixto = entorno.c.get("/terminal/reportes/dia", headers=b1["headers"]).json()
    assert mixto["real"]["ventas"] == "20.00"
    assert mixto["prueba"]["ventas"] == "50.00"
    assert "PRUEBA — NO OFICIAL" in mixto["texto"]
    assert entorno.saldo(b1["sucursal"]["id"]) == antes

    db = dbmod.nueva_sesion()
    supervisor = db.query(Usuario).filter_by(usuario="vend1").one()
    supervisor.rol = "supervisor"
    db.commit()
    db.close()
    headers = entorno.login_terminal()
    sucursal = entorno.c.get("/terminal/reportes/dia?alcance=sucursal", headers=headers)
    assert sucursal.status_code == 200, sucursal.text
    assert sucursal.json()["alcance"] == "sucursal"
    assert sucursal.json()["real"]["ventas"] == "20.00"
