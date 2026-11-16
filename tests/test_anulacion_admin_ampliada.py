"""Anulación administrativa ampliada: sorteo cerrado, perdido, ganador pendiente."""
from datetime import datetime

from apps.api import db as dbmod
from apps.api.models import MovimientoCajera, Ticket


def _anular_panel(entorno, ticket, motivo="anulación admin"):
    return entorno.c.post(
        "/panel/tickets/anular",
        json={"id": ticket["id"], "serial": ticket["serial"], "motivo": motivo},
        headers=entorno.admin,
    )


def test_admin_anula_ticket_perdido(entorno, fijar_hora):
    fijar_hora(datetime(2026, 11, 14, 10, 0, 0))
    b = entorno.banca(saldo=5000, codigo="ANP1", usuario="anp1", clave="1234")
    s = entorno.sorteo_id("La Primera 12")
    t = entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [s], "numeros": "19", "monto": 40}])
    caja = float(entorno.c.get("/terminal/sorteos", headers=b["headers"]).json()["mi_caja"])
    entorno.liquidar(s, 1, 2, 3)  # no gana
    assert entorno.consultar(t)["estado"] == "no_ganador"
    r = _anular_panel(entorno, t, motivo="anular perdido")
    assert r.status_code == 200, r.text
    assert r.json()["estado"] == "anulado"
    assert float(entorno.c.get("/terminal/sorteos", headers=b["headers"]).json()["mi_caja"]) == caja - 40


def test_admin_anula_ganador_pendiente_e_invalida_premio(entorno, monkeypatch, fijar_hora):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    fijar_hora(datetime(2026, 11, 14, 10, 0, 0))
    b = entorno.banca(saldo=20000, codigo="ANP2", usuario="anp2", clave="1234")
    s = entorno.sorteo_id("La Primera 12")
    t = entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [s], "numeros": "19", "monto": 10}])
    sim = entorno.c.post("/resultados", json={
        "sorteo_id": s, "fecha": "2026-11-14",
        "premio1": 19, "premio2": 3, "premio3": 45, "simulado": True,
    }, headers=entorno.admin)
    assert sim.status_code == 201, sim.text
    cons = entorno.consultar(t)
    assert cons["estado"] == "ganador"
    assert float(cons["premio_pendiente"]) > 0
    info = entorno.c.get(f"/panel/tickets/{t['id']}/anulacion", headers=entorno.admin)
    assert info.status_code == 200
    assert info.json()["puede_anular"] is True
    assert float(info.json()["premios_pendientes_total"]) > 0

    caja = float(entorno.c.get("/terminal/sorteos", headers=b["headers"]).json()["mi_caja"])
    r = _anular_panel(entorno, t, motivo="anular ganador pendiente")
    assert r.status_code == 200, r.text
    assert r.json()["estado"] == "anulado"
    # Ya no es pagable
    cons2 = entorno.consultar(t)
    assert cons2["estado"] == "anulado"
    assert cons2["puede_pagar"] is False
    pago = entorno.c.post(
        "/terminal/tickets/pagar",
        json={"id": t["id"], "serial": t["serial"], "operacion_id": "no-pago-anulado"},
        headers=b["headers"],
    )
    assert pago.status_code == 409
    assert float(entorno.c.get("/terminal/sorteos", headers=b["headers"]).json()["mi_caja"]) == caja - 10
    # Auditoría conserva premios invalidados
    aud = entorno.c.get("/auditoria?entidad=ticket&accion=anulacion", headers=entorno.admin).json()
    fila = next(
        (a for a in aud if str(a.get("entidad_id")) == str(t["id"])),
        None,
    )
    assert fila is not None, aud[:3]
    assert fila["detalle"]["estado_previo"] == "ganador"
    assert float(fila["detalle"]["premios_pendientes_total"]) > 0


def test_admin_no_anula_parcialmente_pagado(entorno, monkeypatch, fijar_hora):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    fijar_hora(datetime(2026, 11, 14, 10, 0, 0))
    b = entorno.banca(saldo=50000, codigo="ANP3", usuario="anp3", clave="1234")
    users = entorno.c.get("/usuarios", headers=entorno.admin).json()
    cajera = next(u for u in users if u["usuario"] == "anp3")
    fondo = entorno.c.post("/fondos", json={
        "sucursal_id": b["sucursal"]["id"], "usuario_id": cajera["id"], "monto": 30000,
        "tipo": "aporte_prueba", "operacion_id": "fondo-anp3",
    }, headers=entorno.admin)
    assert fondo.status_code == 201, fondo.text
    s = entorno.sorteo_id("La Primera 12")
    t = entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [s], "numeros": "19", "monto": 10}])
    sim = entorno.c.post("/resultados", json={
        "sorteo_id": s, "fecha": "2026-11-14",
        "premio1": 19, "premio2": 3, "premio3": 45, "simulado": True,
    }, headers=entorno.admin)
    assert sim.status_code == 201, sim.text
    pago = entorno.c.post(
        "/terminal/tickets/pagar",
        json={"id": t["id"], "serial": t["serial"], "operacion_id": "pago-anp3"},
        headers=b["headers"],
    )
    assert pago.status_code == 200, pago.text
    r = _anular_panel(entorno, t, motivo="no debe")
    assert r.status_code == 409
    assert "pagad" in r.json()["detail"].lower() or "reversión" in r.json()["detail"].lower()


def test_cajero_no_usa_api_admin_anulacion(entorno, fijar_hora):
    fijar_hora(datetime(2026, 11, 14, 10, 0, 0))
    b = entorno.banca(saldo=1000, codigo="ANP4", usuario="anp4", clave="1234")
    s = entorno.sorteo_id("La Primera 12")
    t = entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [s], "numeros": "22", "monto": 10}])
    r = entorno.c.post(
        "/panel/tickets/anular",
        json={"id": t["id"], "serial": t["serial"], "motivo": "intento cajero"},
        headers=b["headers"],
    )
    assert r.status_code in (401, 403)


def test_admin_anula_sorteo_abierto_descuenta(entorno, fijar_hora):
    fijar_hora(datetime(2026, 11, 14, 10, 0, 0))
    b = entorno.banca(saldo=2000, codigo="ANP5", usuario="anp5", clave="1234")
    s = entorno.sorteo_id("La Primera 12")
    t = entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [s], "numeros": "11", "monto": 55}])
    caja = float(entorno.c.get("/terminal/sorteos", headers=b["headers"]).json()["mi_caja"])
    r = _anular_panel(entorno, t, motivo="abierto ok")
    assert r.status_code == 200
    assert float(entorno.c.get("/terminal/sorteos", headers=b["headers"]).json()["mi_caja"]) == caja - 55
    db = dbmod.nueva_sesion()
    assert db.get(Ticket, t["id"]).estado == "anulado"
    assert db.query(MovimientoCajera).filter(
        MovimientoCajera.referencia.contains(str(t["id"])),
        MovimientoCajera.tipo.in_(("anulacion", "anulacion_prueba")),
    ).count() == 1
    db.close()
