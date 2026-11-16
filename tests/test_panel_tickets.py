"""Lista administrativa de tickets y anulación desde el Panel del Consorcio."""
from datetime import datetime
from pathlib import Path

from apps.api import db as dbmod
from apps.api.models import Ticket


def test_lista_tickets_filtra_y_pagina(entorno, fijar_hora):
    fijar_hora(datetime(2026, 11, 14, 10, 0, 0))
    b = entorno.banca(saldo=5000, codigo="TIC1", usuario="cajtic", clave="1234")
    s = entorno.sorteo_id("La Primera 12")
    t1 = entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [s], "numeros": "12", "monto": 10}])
    t2 = entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [s], "numeros": "13", "monto": 15}])

    lista = entorno.c.get("/panel/tickets", headers=entorno.admin)
    assert lista.status_code == 200, lista.text
    datos = lista.json()
    assert datos["total"] >= 2
    ids = [x["id"] for x in datos["tickets"]]
    assert t2["id"] in ids
    assert ids == sorted(ids, reverse=True)

    uno = entorno.c.get(f"/panel/tickets?ticket_id={t1['id']}", headers=entorno.admin).json()
    assert uno["total"] == 1
    assert uno["tickets"][0]["id"] == t1["id"]
    assert "cajera" in uno["tickets"][0]
    assert uno["tickets"][0]["estado"] == "vendido"
    assert uno["tickets"][0]["puede_anular"] is True

    det = entorno.c.get(f"/panel/tickets/{t1['id']}", headers=entorno.admin)
    assert det.status_code == 200
    assert det.json()["serial"] == t1["serial"]
    assert len(det.json()["jugadas"]) >= 1


def test_lista_filtra_por_estado_y_sucursal(entorno, fijar_hora):
    fijar_hora(datetime(2026, 11, 14, 10, 0, 0))
    b = entorno.banca(saldo=3000, codigo="TIC5", usuario="cajtic5", clave="1234")
    s = entorno.sorteo_id("La Primera 12")
    t = entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [s], "numeros": "21", "monto": 20}])
    an = entorno.c.post(
        "/panel/tickets/anular",
        json={"id": t["id"], "serial": t["serial"], "motivo": "filtro estado"},
        headers=entorno.admin,
    )
    assert an.status_code == 200, an.text

    anulados = entorno.c.get(
        f"/panel/tickets?estado=anulado&sucursal_id={b['sucursal']['id']}",
        headers=entorno.admin,
    ).json()
    assert any(x["id"] == t["id"] for x in anulados["tickets"])
    vendidos = entorno.c.get(
        f"/panel/tickets?estado=vendido&sucursal_id={b['sucursal']['id']}",
        headers=entorno.admin,
    ).json()
    assert all(x["id"] != t["id"] for x in vendidos["tickets"])


def test_anular_admin_descuenta_caja_y_no_borra(entorno, fijar_hora):
    fijar_hora(datetime(2026, 11, 14, 10, 0, 0))
    b = entorno.banca(saldo=5000, codigo="TIC2", usuario="cajtic2", clave="1234")
    s = entorno.sorteo_id("La Primera 12")
    ticket = entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [s], "numeros": "14", "monto": 25}])
    caja_antes = float(entorno.c.get("/terminal/sorteos", headers=b["headers"]).json()["mi_caja"])

    r = entorno.c.post(
        "/panel/tickets/anular",
        json={"id": ticket["id"], "serial": ticket["serial"], "motivo": "Prueba administrativa"},
        headers=entorno.admin,
    )
    assert r.status_code == 200, r.text
    assert r.json()["estado"] == "anulado"
    assert r.json()["anulado_motivo"] == "Prueba administrativa"

    det = entorno.c.get(f"/panel/tickets/{ticket['id']}", headers=entorno.admin).json()
    assert det["estado"] == "anulado"
    assert det["jugadas"]

    dup = entorno.c.post(
        "/panel/tickets/anular",
        json={"id": ticket["id"], "serial": ticket["serial"], "motivo": "otra"},
        headers=entorno.admin,
    )
    assert dup.status_code == 409

    caja_despues = float(entorno.c.get("/terminal/sorteos", headers=b["headers"]).json()["mi_caja"])
    assert caja_despues == caja_antes - 25


def test_anular_pagado_rechazado_desde_panel(entorno, monkeypatch, fijar_hora):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    fijar_hora(datetime(2026, 11, 14, 10, 0, 0))
    b = entorno.banca(saldo=20000, codigo="TIC3", usuario="cajtic3", clave="1234")
    users = entorno.c.get("/usuarios", headers=entorno.admin).json()
    cajera = next(u for u in users if u["usuario"] == "cajtic3")
    fondo = entorno.c.post("/fondos", json={
        "sucursal_id": b["sucursal"]["id"], "usuario_id": cajera["id"], "monto": 20000,
        "tipo": "aporte_prueba", "operacion_id": "fondo-panel-tic3",
    }, headers=entorno.admin)
    assert fondo.status_code == 201, fondo.text
    s = entorno.sorteo_id("La Primera 12")
    ticket = entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [s], "numeros": "19", "monto": 10}])
    sim = entorno.c.post("/resultados", json={
        "sorteo_id": s, "fecha": "2026-11-14",
        "premio1": 19, "premio2": 3, "premio3": 45, "simulado": True,
    }, headers=entorno.admin)
    assert sim.status_code == 201, sim.text
    pago = entorno.c.post(
        "/terminal/tickets/pagar",
        json={"id": ticket["id"], "serial": ticket["serial"], "operacion_id": "pago-panel-tic3"},
        headers=b["headers"],
    )
    assert pago.status_code == 200, pago.text

    r = entorno.c.post(
        "/panel/tickets/anular",
        json={"id": ticket["id"], "serial": ticket["serial"], "motivo": "no debe"},
        headers=entorno.admin,
    )
    assert r.status_code == 409


def test_supervisor_lista_pero_no_anula(entorno, fijar_hora):
    fijar_hora(datetime(2026, 11, 14, 10, 0, 0))
    b = entorno.banca(saldo=1000, codigo="TIC4", usuario="cajtic4", clave="1234")
    s = entorno.sorteo_id("La Primera 12")
    ticket = entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [s], "numeros": "22", "monto": 10}])
    cre = entorno.c.post(
        "/usuarios",
        json={
            "nombre": "SUPER TIC",
            "usuario": "suptic",
            "clave": "super123",
            "rol": "supervisor",
            "sucursal_id": b["sucursal"]["id"],
            "activo": True,
        },
        headers=entorno.admin,
    )
    assert cre.status_code == 201, cre.text
    login = entorno.c.post("/auth/login", json={"usuario": "suptic", "clave": "super123"})
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['token']}"}
    assert entorno.c.get("/panel/tickets", headers=headers).status_code == 200
    an = entorno.c.post(
        "/panel/tickets/anular",
        json={"id": ticket["id"], "serial": ticket["serial"], "motivo": "x"},
        headers=headers,
    )
    assert an.status_code == 403


def test_html_tiene_lista_tickets():
    html = Path("apps/web/index.html").read_text(encoding="utf-8")
    assert "tic-lista" in html
    assert "ELIMINAR / ANULAR" in html or "btn-tic-lista" in html
    assert "tic-modal" in html
    css = Path("apps/web/style.css").read_text(encoding="utf-8")
    assert ".tic-lista" in css
    assert ".tic-card" in css
