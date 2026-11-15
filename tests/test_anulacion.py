"""Anulación: 5 minutos para la cajera; después solo el admin del Panel.

No se anulan tickets pagados ni sorteos cerrados. La caja y ventas del día
se actualizan sin duplicar movimientos.
"""
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

from apps.api import db as dbmod
from apps.api.comun import MSG_ANULACION_VENCIDA
from apps.api.models import MovimientoCajera, MovimientoSaldo, Ticket


def _anular_terminal(entorno, headers, ticket, motivo="error de venta"):
    return entorno.c.post(
        "/terminal/tickets/anular",
        json={"id": ticket["id"], "serial": ticket["serial"], "motivo": motivo},
        headers=headers,
    )


def _anular_panel(entorno, ticket, motivo="anulación admin"):
    return entorno.c.post(
        "/panel/tickets/anular",
        json={"id": ticket["id"], "serial": ticket["serial"], "motivo": motivo},
        headers=entorno.admin,
    )


def test_anular_antes_del_cierre_saca_el_dinero_de_la_caja(entorno, fijar_hora):
    fijar_hora(datetime(2026, 11, 14, 10, 0, 0))
    b = entorno.banca(saldo=1000)
    s = entorno.sorteo_id("La Primera 12")
    caja0 = float(entorno.c.get("/terminal/sorteos", headers=b["headers"]).json()["mi_caja"])
    t = entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [s], "numeros": "19", "monto": 100}])
    caja1 = float(entorno.c.get("/terminal/sorteos", headers=b["headers"]).json()["mi_caja"])
    assert caja1 == caja0 + 100
    r = _anular_terminal(entorno, b["headers"], t)
    assert r.status_code == 200, r.text
    assert r.json()["estado"] == "anulado"
    caja2 = float(entorno.c.get("/terminal/sorteos", headers=b["headers"]).json()["mi_caja"])
    assert caja2 == caja0
    db = dbmod.nueva_sesion()
    tipos = {"anulacion", "anulacion_prueba"}
    movs = db.query(MovimientoCajera).filter(
        MovimientoCajera.tipo.in_(tipos),
        MovimientoCajera.referencia.contains(str(t["id"])),
    ).count()
    db.close()
    assert movs == 1
    assert entorno.consultar(t)["estado"] == "anulado"
    assert entorno.consultar(t)["anulado_motivo"] == "error de venta"


def test_cajera_puede_anular_a_los_4_min_59(entorno, fijar_hora):
    fijar_hora(datetime(2026, 11, 14, 10, 0, 0))
    b = entorno.banca(saldo=1000)
    s = entorno.sorteo_id("La Primera 12")
    t = entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [s], "numeros": "19", "monto": 10}])
    fijar_hora(datetime(2026, 11, 14, 10, 4, 59))
    r = _anular_terminal(entorno, b["headers"], t)
    assert r.status_code == 200, r.text
    assert r.json()["estado"] == "anulado"
    assert r.json()["anulado_motivo"] == "error de venta"


def test_cajera_bloqueada_a_los_5_minutos_exactos(entorno, fijar_hora):
    fijar_hora(datetime(2026, 11, 14, 10, 0, 0))
    b = entorno.banca(saldo=1000)
    s = entorno.sorteo_id("La Primera 12")
    t = entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [s], "numeros": "19", "monto": 10}])
    fijar_hora(datetime(2026, 11, 14, 10, 5, 0))
    r = _anular_terminal(entorno, b["headers"], t)
    assert r.status_code == 403
    assert r.json()["detail"] == MSG_ANULACION_VENCIDA
    assert entorno.consultar(t)["estado"] == "vendido"
    assert entorno.consultar(t)["puede_anular_cajera"] is False
    assert MSG_ANULACION_VENCIDA in (entorno.consultar(t).get("mensaje_anular") or "")


def test_admin_panel_anula_despues_de_5_minutos(entorno, fijar_hora):
    fijar_hora(datetime(2026, 11, 14, 10, 0, 0))
    b = entorno.banca(saldo=1000)
    s = entorno.sorteo_id("La Primera 12")
    t = entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [s], "numeros": "19", "monto": 50}])
    fijar_hora(datetime(2026, 11, 14, 10, 20, 0))
    assert _anular_terminal(entorno, b["headers"], t).status_code == 403
    r = _anular_panel(entorno, t, motivo="Corrección autorizada")
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["estado"] == "anulado"
    assert cuerpo["anulado_motivo"] == "Corrección autorizada"
    assert cuerpo["anulado_por"]
    assert entorno.saldo(b["sucursal"]["id"]) == 1000.00
    filas = entorno.c.get("/auditoria?entidad=ticket&accion=anulacion", headers=entorno.admin).json()
    assert filas[0]["detalle"]["motivo"] == "Corrección autorizada"
    assert filas[0]["detalle"]["desde_panel"] is True


def test_anular_sin_motivo_rechazado(entorno, fijar_hora):
    fijar_hora(datetime(2026, 11, 14, 10, 0, 0))
    b = entorno.banca(saldo=1000)
    s = entorno.sorteo_id("La Primera 12")
    t = entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [s], "numeros": "19", "monto": 10}])
    r = entorno.c.post(
        "/terminal/tickets/anular",
        json={"id": t["id"], "serial": t["serial"], "motivo": "  "},
        headers=b["headers"],
    )
    assert r.status_code == 400
    assert "motivo" in r.json()["detail"].lower()


def test_anular_despues_del_cierre_rechazado(entorno, fijar_hora):
    fijar_hora(datetime(2026, 11, 14, 10, 0, 0))
    b = entorno.banca(saldo=1000)
    s = entorno.sorteo_id("La Primera 12")
    caja0 = float(entorno.c.get("/terminal/sorteos", headers=b["headers"]).json()["mi_caja"])
    t = entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [s], "numeros": "19", "monto": 10}])
    fijar_hora(datetime(2026, 11, 14, 12, 5))
    r = _anular_terminal(entorno, b["headers"], t)
    assert r.status_code in (403, 409)
    admin = _anular_panel(entorno, t)
    assert admin.status_code == 409 and "ya cerró" in admin.json()["detail"]
    assert entorno.consultar(t)["estado"] == "vendido"
    assert float(entorno.c.get("/terminal/sorteos", headers=b["headers"]).json()["mi_caja"]) == caja0 + 10


def test_anular_con_un_solo_sorteo_cerrado_rechazado(entorno, fijar_hora):
    fijar_hora(datetime(2026, 11, 14, 10, 0, 0))
    b = entorno.banca(saldo=1000)
    s1 = entorno.sorteo_id("La Primera 12")
    s2 = entorno.sorteo_id("Nacional Noche")
    t = entorno.vender_ok(b["headers"], [
        {"tipo": "SP", "sorteos": [s1, s2], "numeros": "26-58", "monto": 10},
    ])
    fijar_hora(datetime(2026, 11, 14, 10, 2, 0))
    # Dentro de 5 min pero con un sorteo ya cerrado: debe rechazar por cierre.
    fijar_hora(datetime(2026, 11, 14, 12, 5))
    # Pasó la ventana de cajera; admin tampoco puede.
    r = _anular_panel(entorno, t)
    assert r.status_code == 409 and "La Primera 12" in r.json()["detail"]


def test_anular_dos_veces_rechazado(entorno, fijar_hora):
    fijar_hora(datetime(2026, 11, 14, 10, 0, 0))
    b = entorno.banca(saldo=1000)
    s = entorno.sorteo_id("La Primera 12")
    t = entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [s], "numeros": "19", "monto": 10}])
    assert _anular_terminal(entorno, b["headers"], t).status_code == 200
    r = _anular_terminal(entorno, b["headers"], t)
    assert r.status_code == 409 and "ya está anulado" in r.json()["detail"]
    db = dbmod.nueva_sesion()
    movs = db.query(MovimientoCajera).filter(
        MovimientoCajera.referencia.contains(str(t["id"])),
        MovimientoCajera.tipo.in_(("anulacion", "anulacion_prueba")),
    ).count()
    db.close()
    assert movs == 1


def test_anular_pagado_rechazado(entorno, monkeypatch, fijar_hora):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    fijar_hora(datetime(2026, 11, 14, 10, 0, 0))
    b = entorno.banca(saldo=20000)
    # Fondo de prueba para poder pagar el premio simulado.
    jose = next(u for u in entorno.c.get("/usuarios", headers=entorno.admin).json() if u["usuario"] == "vend1")
    fondo = entorno.c.post("/fondos", json={
        "sucursal_id": b["sucursal"]["id"], "usuario_id": jose["id"], "monto": 20000,
        "tipo": "aporte_prueba", "operacion_id": "fondo-anula-pago",
    }, headers=entorno.admin)
    assert fondo.status_code == 201, fondo.text
    s = entorno.sorteo_id("La Primera 12")
    t = entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [s], "numeros": "19", "monto": 10}])
    sim = entorno.c.post("/resultados", json={
        "sorteo_id": s, "fecha": "2026-11-14",
        "premio1": 19, "premio2": 3, "premio3": 45, "simulado": True,
    }, headers=entorno.admin)
    assert sim.status_code == 201, sim.text
    r = entorno.c.post(
        "/terminal/tickets/pagar",
        json={"id": t["id"], "serial": t["serial"], "operacion_id": "pago-anula-1"},
        headers=b["headers"],
    )
    assert r.status_code == 200, r.text
    baja = _anular_panel(entorno, t)
    assert baja.status_code == 409
    assert "pagado" in baja.json()["detail"].lower() or "premio" in baja.json()["detail"].lower()


def test_ticket_anulado_no_cuenta_para_el_limite(entorno, fijar_hora):
    fijar_hora(datetime(2026, 11, 14, 10, 0, 0))
    b = entorno.banca(saldo=100000)
    s = entorno.sorteo_id("La Primera 12")
    entorno.c.post("/limites", json={
        "sorteo_id": s, "tipo": "QN", "numeros": "26", "monto_max_acumulado": 100,
    }, headers=entorno.admin)
    t = entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [s], "numeros": "26", "monto": 60}])
    assert _anular_terminal(entorno, b["headers"], t).status_code == 200
    entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [s], "numeros": "26", "monto": 60}])


def test_anulaciones_simultaneas_no_duplican_movimientos(entorno, fijar_hora):
    fijar_hora(datetime(2026, 11, 14, 10, 0, 0))
    b = entorno.banca(saldo=5000)
    s = entorno.sorteo_id("La Primera 12")
    t = entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [s], "numeros": "19", "monto": 100}])
    caja0 = float(entorno.c.get("/terminal/sorteos", headers=b["headers"]).json()["mi_caja"])

    def intento():
        return _anular_panel(entorno, t, motivo="carrera")

    with ThreadPoolExecutor(max_workers=2) as pool:
        resultados = list(pool.map(lambda _: intento(), range(2)))
    oks = [r for r in resultados if r.status_code == 200]
    conflictos = [r for r in resultados if r.status_code >= 400]
    assert len(oks) >= 1
    assert len(oks) + len(conflictos) == 2
    db = dbmod.nueva_sesion()
    assert db.get(Ticket, t["id"]).estado == "anulado"
    movs = db.query(MovimientoCajera).filter(
        MovimientoCajera.referencia.contains(str(t["id"])),
        MovimientoCajera.tipo.in_(("anulacion", "anulacion_prueba")),
    ).count()
    db.close()
    assert movs == 1
    caja1 = float(entorno.c.get("/terminal/sorteos", headers=b["headers"]).json()["mi_caja"])
    assert caja1 == caja0 - 100
    # Segunda anulación secuencial tampoco duplica.
    otra = _anular_panel(entorno, t, motivo="otra")
    assert otra.status_code == 409
    db = dbmod.nueva_sesion()
    assert db.query(MovimientoCajera).filter(
        MovimientoCajera.referencia.contains(str(t["id"])),
        MovimientoCajera.tipo.in_(("anulacion", "anulacion_prueba")),
    ).count() == 1
    db.close()


def test_ventas_dia_y_mi_caja_restan_anulacion(entorno, fijar_hora):
    fijar_hora(datetime(2026, 11, 14, 10, 0, 0))
    b = entorno.banca(saldo=2000, codigo="1401", usuario="caja1", clave="1234")
    s = entorno.sorteo_id("La Primera 12")
    t = entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [s], "numeros": "19", "monto": 80}])
    mi_antes = float(entorno.c.get("/terminal/sorteos", headers=b["headers"]).json()["mi_caja"])
    assert _anular_terminal(entorno, b["headers"], t).status_code == 200
    mi_despues = float(entorno.c.get("/terminal/sorteos", headers=b["headers"]).json()["mi_caja"])
    assert mi_despues == mi_antes - 80
    assert entorno.consultar(t)["estado"] == "anulado"
    assert entorno.saldo(b["sucursal"]["id"]) == 2000.00
