"""Ventas por cajero: premios al pagador, fondo separado, permisos admin."""
from datetime import datetime


def test_dos_cajeros_separados_y_premio_de_otro(entorno, monkeypatch, fijar_hora):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    fijar_hora(datetime(2026, 11, 14, 10, 0, 0))
    a = entorno.banca(saldo=5000, usuario="vc1", clave="prueba123")
    entorno.operador("vc2", "prueba123", a["sucursal"]["id"])
    paga = entorno.login_terminal("vc2", "prueba123")
    jose = next(u for u in entorno.c.get("/usuarios", headers=entorno.admin).json() if u["usuario"] == "vc2")
    fondo = entorno.c.post("/fondos", json={
        "sucursal_id": a["sucursal"]["id"], "usuario_id": jose["id"], "monto": 1000,
        "tipo": "aporte_prueba", "operacion_id": "fondo-vc2",
    }, headers=entorno.admin)
    assert fondo.status_code == 201, fondo.text
    lot = entorno.sorteo_id("LOTEDOM")
    t = entorno.vender_ok(a["headers"], [{"tipo": "QN", "sorteos": [lot], "numeros": "25", "monto": 10}])
    entorno.vender_ok(paga, [{"tipo": "QN", "sorteos": [lot], "numeros": "11", "monto": 5}])
    sim = entorno.c.post("/resultados", json={
        "sorteo_id": lot, "fecha": "2026-11-14", "premio1": 25, "premio2": 1, "premio3": 2, "simulado": True,
    }, headers=entorno.admin)
    assert sim.status_code == 201, sim.text
    pago = entorno.c.post("/terminal/tickets/pagar", json={
        "id": t["id"], "serial": t["serial"], "operacion_id": "pago-vc2",
    }, headers=paga)
    assert pago.status_code == 200, pago.text

    r = entorno.c.get("/reportes/ventas-cajeros?desde=2026-11-14&hasta=2026-11-14", headers=entorno.admin)
    assert r.status_code == 200, r.text
    filas = {f["usuario"]: f for f in r.json()["cajeros"]}
    assert "vc1" in filas and "vc2" in filas
    assert float(filas["vc1"]["ventas_netas"]) == 10
    assert float(filas["vc1"]["premios_pagados"]) == 0  # vendió, no pagó
    assert float(filas["vc2"]["ventas_netas"]) == 5
    assert float(filas["vc2"]["premios_pagados"]) == 600  # pagó el premio
    assert float(filas["vc2"]["fondo_asignado"]) == 1000
    assert float(filas["vc2"]["recaudacion"]) == 5 - 600

    det = entorno.c.get(f"/reportes/ventas-cajeros/{jose['id']}?desde=2026-11-14&hasta=2026-11-14", headers=entorno.admin)
    assert det.status_code == 200
    assert det.json()["premios_pagados"]
    assert det.json()["premios_pagados"][0]["vendedor_usuario"] == "vc1"


def test_supervisor_no_ve_ventas_cajeros(entorno):
    entorno.c.post("/usuarios", json={
        "nombre": "SUPER VC", "usuario": "supvc", "rol": "supervisor", "clave": "prueba123", "activo": True,
    }, headers=entorno.admin)
    login = entorno.c.post("/auth/login", json={"usuario": "supvc", "clave": "prueba123"})
    headers = {"Authorization": f"Bearer {login.json()['token']}"}
    r = entorno.c.get("/reportes/ventas-cajeros", headers=headers)
    assert r.status_code == 403


def test_panel_tiene_seccion_ventas_cajeros(entorno):
    html = entorno.c.get("/").text
    assert 'data-sec="ventas-cajeros"' in html
    assert 'id="sec-ventas-cajeros"' in html
    assert 'id="vc-lista"' in html
    js = entorno.c.get("/static/app.js").text
    assert "cargarVentasCajeros" in js
    assert "verDetalleCajero" in js
