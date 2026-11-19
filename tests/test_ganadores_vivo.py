"""Ganadores en vivo: una tarjeta por ticket, sin repetir loterías, estados de pago."""
from datetime import datetime


def _simular(entorno, sorteo_id, p1, p2, p3, fecha="2026-11-14"):
    """Resultado simulado: liquida solo tickets de prueba al guardar. No se confirma."""
    r = entorno.c.post(
        "/resultados",
        json={"sorteo_id": sorteo_id, "fecha": fecha, "premio1": p1, "premio2": p2,
              "premio3": p3, "simulado": True},
        headers=entorno.admin,
    )
    assert r.status_code in (200, 201), r.text
    return r.json()


def _fondo(entorno, usuario, sucursal_id, monto=20000):
    jose = next(u for u in entorno.c.get("/usuarios", headers=entorno.admin).json() if u["usuario"] == usuario)
    r = entorno.c.post("/fondos", json={
        "sucursal_id": sucursal_id, "usuario_id": jose["id"], "monto": monto,
        "tipo": "aporte_prueba", "operacion_id": f"fondo-{usuario}-{monto}-{jose['id']}",
    }, headers=entorno.admin)
    assert r.status_code == 201, r.text


def test_una_loteria_no_repite_el_nombre(entorno, monkeypatch):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    b = entorno.banca(saldo=5000, usuario="gv1", clave="prueba123")
    lotedom = entorno.sorteo_id("LOTEDOM")
    t = entorno.vender_ok(b["headers"], [
        {"tipo": "QN", "sorteos": [lotedom], "numeros": "25", "monto": 10},
        {"tipo": "QN", "sorteos": [lotedom], "numeros": "25", "monto": 5},
        {"tipo": "QN", "sorteos": [lotedom], "numeros": "11", "monto": 10},
    ])
    _simular(entorno, lotedom, 25, 54, 78)
    datos = entorno.c.get("/ganadores?fecha=2026-11-14", headers=entorno.admin).json()
    filas = [f for f in datos["prueba"] if f["id"] == t["id"]]
    assert len(filas) == 1
    fila = filas[0]
    assert fila["loterias"].count("Lotedom") == 1
    assert fila["estado_pago"] == "PENDIENTE"
    assert float(fila["importe_pendiente"]) == float(fila["premio"])
    assert float(fila["importe_pagado"]) == 0


def test_varias_loterias_aparecen_una_vez_cada_una(entorno, monkeypatch):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    b = entorno.banca(saldo=5000, usuario="gv2", clave="prueba123")
    a = entorno.sorteo_id("LOTEDOM")
    b2 = entorno.sorteo_id("La Primera 12")
    t = entorno.vender_ok(b["headers"], [
        {"tipo": "QN", "sorteos": [a], "numeros": "25", "monto": 10},
        {"tipo": "QN", "sorteos": [b2], "numeros": "25", "monto": 10},
        {"tipo": "QN", "sorteos": [a], "numeros": "25", "monto": 10},
    ])
    _simular(entorno, a, 25, 54, 78)
    _simular(entorno, b2, 25, 1, 2)
    datos = entorno.c.get("/ganadores?fecha=2026-11-14", headers=entorno.admin).json()
    fila = next(f for f in datos["prueba"] if f["id"] == t["id"])
    nombres = fila["loterias_lista"]
    assert len(nombres) == len(set(nombres))
    assert len(nombres) == 2
    det = entorno.c.get(f"/ganadores/{t['id']}", headers=entorno.admin).json()
    assert det["estado_pago"] == "PENDIENTE"
    assert all(float(j["premio"]) > 0 for g in det["grupos"] for j in g["jugadas"])
    assert len(det["grupos"]) == 2


def test_parcial_y_pagado_distinguen_vendedor_y_pagador(entorno, monkeypatch, fijar_hora):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    fijar_hora(datetime(2026, 11, 14, 10, 0, 0))
    b = entorno.banca(saldo=5000, usuario="vende1", clave="prueba123")
    entorno.operador("paga1", "prueba123", b["sucursal"]["id"])
    paga = entorno.login_terminal("paga1", "prueba123")
    _fondo(entorno, "vende1", b["sucursal"]["id"], 20000)
    _fondo(entorno, "paga1", b["sucursal"]["id"], 20000)
    a = entorno.sorteo_id("LOTEDOM")
    b2 = entorno.sorteo_id("La Primera 12")
    t = entorno.vender_ok(b["headers"], [
        {"tipo": "QN", "sorteos": [a], "numeros": "25", "monto": 10},
        {"tipo": "QN", "sorteos": [b2], "numeros": "25", "monto": 10},
    ])
    _simular(entorno, a, 25, 54, 78)
    fila = next(f for f in entorno.c.get("/ganadores?fecha=2026-11-14", headers=entorno.admin).json()["prueba"] if f["id"] == t["id"])
    assert fila["estado_pago"] == "PENDIENTE"
    assert fila["cajero"]
    assert not fila["cajero_pago"]

    # Terminal: otra cajera no puede cobrar el ticket (403). La seguridad no se debilita.
    ajeno = entorno.c.post("/terminal/tickets/pagar", json={
        "id": t["id"], "serial": t["serial"], "operacion_id": "pago-otro-cajero",
    }, headers=paga)
    assert ajeno.status_code == 403, ajeno.text
    assert "OTRA CAJERA" in ajeno.json()["detail"]

    # Solo la vendedora cobra el tramo ya confirmado.
    pago = entorno.c.post("/terminal/tickets/pagar", json={
        "id": t["id"], "serial": t["serial"], "operacion_id": "pago-vendedor",
    }, headers=b["headers"])
    assert pago.status_code == 200, pago.text

    fila_pag = next(f for f in entorno.c.get("/ganadores?fecha=2026-11-14", headers=entorno.admin).json()["prueba"] if f["id"] == t["id"])
    assert fila_pag["estado_pago"] == "PAGADO"
    assert fila_pag["cajero_pago"]
    assert fila_pag["cajero"] == fila_pag["cajero_pago"]
    assert float(fila_pag["importe_pendiente"]) == 0

    _simular(entorno, b2, 25, 1, 2)
    datos = entorno.c.get("/ganadores?fecha=2026-11-14", headers=entorno.admin).json()
    fila2 = next(f for f in datos["prueba"] if f["id"] == t["id"])
    assert fila2["estado_pago"] == "PARCIALMENTE PAGADO"
    assert float(fila2["importe_pagado"]) > 0
    assert float(fila2["importe_pendiente"]) > 0
    assert fila2["cajero_pago"]
    assert fila2["cajero"]

    det = entorno.c.get(f"/ganadores/{t['id']}", headers=entorno.admin).json()
    assert det["estado_pago"] == "PARCIALMENTE PAGADO"
    assert det["cajero"]
    assert det["cajero_pago"]
    assert len(det["grupos"]) == 2
    estados = {j["estado_premio"] for g in det["grupos"] for j in g["jugadas"]}
    assert "PAGADO" in estados and "PENDIENTE" in estados


def test_filtro_estado_parcial(entorno, monkeypatch, fijar_hora):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    fijar_hora(datetime(2026, 11, 14, 10, 0, 0))
    b = entorno.banca(saldo=5000, usuario="gv3", clave="prueba123")
    _fondo(entorno, "gv3", b["sucursal"]["id"], 20000)
    a = entorno.sorteo_id("LOTEDOM")
    b2 = entorno.sorteo_id("La Primera 12")
    t = entorno.vender_ok(b["headers"], [
        {"tipo": "QN", "sorteos": [a], "numeros": "25", "monto": 10},
        {"tipo": "QN", "sorteos": [b2], "numeros": "25", "monto": 10},
    ])
    _simular(entorno, a, 25, 54, 78)
    pago = entorno.c.post("/terminal/tickets/pagar", json={
        "id": t["id"], "serial": t["serial"], "operacion_id": "pago-filtro-parcial",
    }, headers=b["headers"])
    assert pago.status_code == 200, pago.text
    _simular(entorno, b2, 25, 1, 2)
    r = entorno.c.get("/ganadores?fecha=2026-11-14&estado=parcial", headers=entorno.admin)
    assert r.status_code == 200
    ids = {f["id"] for f in r.json()["prueba"]}
    assert t["id"] in ids
    fila = next(f for f in r.json()["prueba"] if f["id"] == t["id"])
    assert fila["estado_pago"] == "PARCIALMENTE PAGADO"


def test_panel_html_tiene_tarjetas_y_modal(entorno):
    html = entorno.c.get("/").text
    assert 'id="gan-lista"' in html
    assert 'id="gan-modal"' in html
    assert 'id="gan-cajera"' in html
    js = entorno.c.get("/static/app.js").text
    assert "tarjetaGanador" in js
    assert "verTicketGanador" in js
    assert "importe_pendiente" in js
    assert "GANADORES_RELOJ" in js
