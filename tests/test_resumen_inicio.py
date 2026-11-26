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


def test_reales_cuentan_el_premio_en_fecha_de_sorteo_no_de_pago(entorno, fijar_hora):
    """Premio de ayer pagado hoy no reduce el neto de hoy (Dashboard RESUMEN)."""
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
    # Hoy (día del cobro): no debe cargar el premio del sorteo de ayer.
    dia_pago = _inicio(entorno, "2026-11-15", "2026-11-15").json()
    dia_sorteo = _inicio(entorno, "2026-11-14", "2026-11-14").json()
    assert dia_pago["reales"]["ventas"] == "0.00"
    assert dia_pago["reales"]["premios_pagados"] == "0.00"
    assert dia_pago["reales"]["premios_pendientes"] == "0.00"
    assert dia_pago["reales"]["neto"] == "0.00"
    assert dia_pago["reales"]["comision"] == "0.00"
    # Fecha del sorteo: el premio pagado se refleja aquí; pendientes bajan a 0.
    assert dia_sorteo["reales"]["ventas"] == "10.00"
    assert dia_sorteo["reales"]["premios_pagados"] == "600.00"
    assert dia_sorteo["reales"]["premios_pendientes"] == "0.00"
    assert dia_sorteo["reales"]["neto"] == "-590.00"
    assert dia_sorteo["reales"]["comision"] == "1.00"
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


def test_dashboard_multi_sorteo_asigna_cada_premio_a_su_fecha(entorno, monkeypatch, fijar_hora):
    """Ticket multi-sorteo: cada jugada cuenta en su jugada.fecha; cobro otro día no mueve el neto."""
    from datetime import date

    from apps.api import db as dbmod
    from apps.api.models import Jugada, Sesion

    monkeypatch.setenv("MODO_DESARROLLO", "true")
    fijar_hora(datetime(2026, 11, 14, 10, 0, 0))
    b = entorno.banca(saldo=50000, usuario="dashms1", clave="prueba123")
    s1 = entorno.sorteo_id("LOTEDOM")
    s2 = entorno.sorteo_id("Leidsa 3:55 PM")
    ticket = entorno.vender_ok(b["headers"], [
        {"tipo": "QN", "sorteos": [s1], "numeros": "25", "monto": 10},
        {"tipo": "QN", "sorteos": [s2], "numeros": "25", "monto": 20},
    ])
    # Simula ticket con jugadas en dos fechas de sorteo distintas (misma venta).
    db = dbmod.nueva_sesion()
    filas = db.query(Jugada).filter_by(ticket_id=ticket["id"]).order_by(Jugada.id).all()
    assert len(filas) == 2
    filas[0].fecha = date(2026, 11, 14)
    filas[1].fecha = date(2026, 11, 15)
    db.commit()
    db.close()

    sim1 = entorno.c.post("/resultados", json={
        "sorteo_id": s1, "fecha": "2026-11-14", "premio1": 25, "premio2": 1, "premio3": 2, "simulado": True,
    }, headers=entorno.admin)
    assert sim1.status_code == 201, sim1.text
    d14 = _inicio(entorno, "2026-11-14", "2026-11-14").json()["prueba"]
    assert float(d14["premios_pendientes"]) == 600  # 10×60 QN (solo jugada del 14)
    assert d14["premios_pagados"] == "0.00"

    fijar_hora(datetime(2026, 11, 15, 16, 0, 0))
    db = dbmod.nueva_sesion()
    limite = datetime(2026, 11, 17, 0, 0, 0)
    for sesion in db.query(Sesion).all():
        sesion.expira_en = limite
    db.commit()
    db.close()
    admin = entorno.c.post("/auth/login", json={"usuario": "admin", "clave": "admin123"})
    entorno.admin = {"Authorization": f"Bearer {admin.json()['token']}"}
    term = entorno.login_terminal("dashms1", "prueba123")
    sim2 = entorno.c.post("/resultados", json={
        "sorteo_id": s2, "fecha": "2026-11-15", "premio1": 25, "premio2": 3, "premio3": 4, "simulado": True,
    }, headers=entorno.admin)
    assert sim2.status_code == 201, sim2.text
    d14b = _inicio(entorno, "2026-11-14", "2026-11-14").json()["prueba"]
    d15 = _inicio(entorno, "2026-11-15", "2026-11-15").json()["prueba"]
    assert float(d14b["premios_pendientes"]) == 600
    assert float(d15["premios_pendientes"]) == 1200  # 20×60

    # Cobro el 16: pagado_en queda en historial; Dashboard usa fechas de sorteo.
    fijar_hora(datetime(2026, 11, 16, 11, 0, 0))
    db = dbmod.nueva_sesion()
    limite = datetime(2026, 11, 18, 0, 0, 0)
    for sesion in db.query(Sesion).all():
        sesion.expira_en = limite
    db.commit()
    db.close()
    admin = entorno.c.post("/auth/login", json={"usuario": "admin", "clave": "admin123"})
    entorno.admin = {"Authorization": f"Bearer {admin.json()['token']}"}
    term = entorno.login_terminal("dashms1", "prueba123")
    pago = entorno.c.post(
        "/terminal/tickets/pagar",
        json={"id": ticket["id"], "serial": ticket["serial"], "operacion_id": "pago-multi-dash"},
        headers=term,
    )
    assert pago.status_code == 200, pago.text
    d14c = _inicio(entorno, "2026-11-14", "2026-11-14").json()["prueba"]
    d15c = _inicio(entorno, "2026-11-15", "2026-11-15").json()["prueba"]
    d16 = _inicio(entorno, "2026-11-16", "2026-11-16").json()["prueba"]
    assert d14c["premios_pagados"] == "600.00"
    assert d14c["premios_pendientes"] == "0.00"
    assert d15c["premios_pagados"] == "1200.00"
    assert d15c["premios_pendientes"] == "0.00"
    # Día del cobro: cero premios (no reduce neto de hoy).
    assert d16["premios_pagados"] == "0.00"
    assert d16["premios_pendientes"] == "0.00"
    assert d16["neto"] == "0.00"
    # Rango 15 días / desde-hasta: sin duplicar.
    rango = _inicio(entorno, "2026-11-14", "2026-11-16").json()["prueba"]
    assert rango["premios_pagados"] == "1800.00"
    assert rango["premios_pendientes"] == "0.00"


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
