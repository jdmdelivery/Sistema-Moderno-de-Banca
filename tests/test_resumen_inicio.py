"""El inicio del panel separa prueba y reales, y no escribe saldos."""
from datetime import datetime


def _inicio(entorno, desde=None, hasta=None):
    consulta = "/reportes/inicio"
    if desde:
        consulta += f"?desde={desde}&hasta={hasta}"
    return entorno.c.get(consulta, headers=entorno.admin)


def _usuario(entorno, usuario):
    for fila in entorno.c.get("/usuarios", headers=entorno.admin).json():
        if fila["usuario"] == usuario:
            return fila["id"]
    raise AssertionError(usuario)


def test_inicio_exige_sesion_y_rechaza_el_rango_invertido(entorno):
    assert entorno.c.get("/reportes/inicio").status_code == 401
    invertido = _inicio(entorno, "2026-11-15", "2026-11-14")
    assert invertido.status_code == 400


def test_reales_cuentan_el_pago_en_su_fecha_y_no_dejan_pendiente(entorno, fijar_hora):
    b = entorno.banca(saldo=100000)
    sorteo = entorno.sorteo_id("La Primera 12")
    entorno.c.post(
        "/comisiones",
        json={"usuario_id": _usuario(entorno, "vend1"), "porcentaje": 10},
        headers=entorno.admin,
    )
    ticket = entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [sorteo], "numeros": "19", "monto": 10}])
    anulado = entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [sorteo], "numeros": "20", "monto": 40}])
    baja = entorno.c.post(
        "/terminal/tickets/anular",
        json={"id": anulado["id"], "serial": anulado["serial"], "motivo": "error"},
        headers=b["headers"],
    )
    assert baja.status_code == 200, baja.text
    propuesto = entorno.guardar_resultado(sorteo, 19, 3, 45)
    sin_confirmar = _inicio(entorno, "2026-11-14", "2026-11-14")
    assert sin_confirmar.status_code == 200, sin_confirmar.text
    assert sin_confirmar.json()["reales"]["premios_pendientes"] == "0.00"
    assert sin_confirmar.json()["reales"]["ventas"] == "10.00"
    assert sin_confirmar.json()["reales"]["tickets"] == 1
    assert sin_confirmar.json()["reales"]["comision"] == "1.00"

    entorno.confirmar(propuesto["id"])
    saldo = entorno.saldo(b["sucursal"]["id"])
    pendiente = _inicio(entorno, "2026-11-14", "2026-11-14").json()
    assert pendiente["zona"] == "America/Santo_Domingo"
    assert pendiente["reales"]["premios_pendientes"] == "600.00"
    assert pendiente["reales"]["premios_pagados"] == "0.00"
    assert pendiente["prueba"]["ventas"] == "0.00"
    assert pendiente["prueba"]["premios_pendientes"] == "0.00"
    assert entorno.saldo(b["sucursal"]["id"]) == saldo

    fijar_hora(datetime(2026, 11, 15, 9, 0, 0))
    sesion = entorno.c.post("/auth/login", json={"usuario": "admin", "clave": "admin123"})
    assert sesion.status_code == 200, sesion.text
    entorno.admin = {"Authorization": f"Bearer {sesion.json()['token']}"}
    pago = entorno.c.post(
        "/panel/tickets/pagar",
        json={"id": ticket["id"], "serial": ticket["serial"], "sucursal_id": b["sucursal"]["id"]},
        headers=entorno.admin,
    )
    assert pago.status_code == 200, pago.text
    saldo_pagado = entorno.saldo(b["sucursal"]["id"])
    dia_pago = _inicio(entorno, "2026-11-15", "2026-11-15").json()
    dia_venta = _inicio(entorno, "2026-11-14", "2026-11-14").json()
    assert dia_pago["reales"]["ventas"] == "0.00"
    assert dia_pago["reales"]["premios_pagados"] == "600.00"
    assert dia_pago["reales"]["premios_pendientes"] == "0.00"
    assert dia_pago["reales"]["comision"] == "0.00"
    assert dia_venta["reales"]["ventas"] == "10.00"
    assert dia_venta["reales"]["premios_pagados"] == "0.00"
    assert dia_venta["reales"]["premios_pendientes"] == "0.00"
    assert dia_venta["reales"]["comision"] == "1.00"
    ambos = _inicio(entorno, "2026-11-14", "2026-11-15").json()
    assert ambos["reales"]["ventas"] == "10.00"
    assert ambos["reales"]["premios_pagados"] == "600.00"
    assert ambos["reales"]["neto"] == "-590.00"
    repetido = entorno.c.post(
        "/panel/tickets/pagar",
        json={"id": ticket["id"], "serial": ticket["serial"], "sucursal_id": b["sucursal"]["id"]},
        headers=entorno.admin,
    )
    assert repetido.status_code == 409
    assert entorno.saldo(b["sucursal"]["id"]) == saldo_pagado


def test_la_prueba_no_se_mezcla_con_lo_real(entorno, monkeypatch):
    b = entorno.banca(saldo=5764, usuario="jose", clave="prueba123")
    sorteo = entorno.sorteo_id("LOTEDOM")
    entorno.c.post(
        "/comisiones",
        json={"usuario_id": _usuario(entorno, "jose"), "porcentaje": 10},
        headers=entorno.admin,
    )
    entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [sorteo], "numeros": "25", "monto": 10}])
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [sorteo], "numeros": "01", "monto": 600}])
    ticket = entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [sorteo], "numeros": "25", "monto": 10}])
    saldo = entorno.saldo(b["sucursal"]["id"])
    simulado = entorno.c.post(
        "/resultados",
        json={"sorteo_id": sorteo, "fecha": "2026-11-14", "premio1": 25, "premio2": 54,
              "premio3": 78, "simulado": True},
        headers=entorno.admin,
    )
    assert simulado.status_code == 201, simulado.text
    resumen = _inicio(entorno, "2026-11-14", "2026-11-14").json()
    assert resumen["reales"]["ventas"] == "10.00"
    assert resumen["reales"]["premios_pendientes"] == "0.00"
    assert resumen["reales"]["premios_pagados"] == "0.00"
    assert resumen["reales"]["comision"] == "1.00"
    assert resumen["prueba"]["ventas"] == "610.00"
    assert resumen["prueba"]["tickets"] == 2
    assert resumen["prueba"]["premios_pendientes"] == "600.00"
    assert resumen["prueba"]["premios_pagados"] == "0.00"
    assert resumen["prueba"]["comision"] == "61.00"
    pago = entorno.c.post(
        "/terminal/tickets/pagar",
        json={"id": ticket["id"], "serial": ticket["serial"], "operacion_id": "pago-resumen-prueba"},
        headers=b["headers"],
    )
    assert pago.status_code == 200, pago.text
    repetido = entorno.c.post(
        "/terminal/tickets/pagar",
        json={"id": ticket["id"], "serial": ticket["serial"], "operacion_id": "pago-resumen-prueba-2"},
        headers=b["headers"],
    )
    assert repetido.status_code == 409
    pagado = _inicio(entorno, "2026-11-14", "2026-11-14").json()
    assert pagado["prueba"]["premios_pagados"] == "600.00"
    assert pagado["prueba"]["premios_pendientes"] == "0.00"
    assert pagado["reales"]["premios_pagados"] == "0.00"
    assert entorno.saldo(b["sucursal"]["id"]) == saldo
