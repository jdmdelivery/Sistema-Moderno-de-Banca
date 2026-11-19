"""Cierre de ciclo de cajera: conciliación MI CAJA, pago completo y reinicio."""
from datetime import datetime

from apps.api.db import nueva_sesion
from apps.api.models import CierreCicloCajera


def _id(entorno, usuario):
    for fila in entorno.c.get("/usuarios", headers=entorno.admin).json():
        if fila["usuario"] == usuario:
            return fila["id"]
    raise AssertionError(usuario)


def _detalle(entorno, usuario_id):
    r = entorno.c.get(
        f"/reportes/ventas-cajeros/{usuario_id}?desde=2026-11-14&hasta=2026-11-14",
        headers=entorno.admin,
    )
    assert r.status_code == 200, r.text
    return r.json()


def _entregar_todo(entorno, headers, op="ent-ciclo"):
    mi = float(entorno.c.get("/terminal/sorteos", headers=headers).json()["mi_caja"])
    if mi <= 0:
        return
    r = entorno.c.post(
        "/terminal/entregas",
        json={"monto": mi, "operacion_id": op},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    assert float(entorno.c.get("/terminal/sorteos", headers=headers).json()["mi_caja"]) == 0


def test_pago_parcial_no_cierra_y_cierre_exige_caja_cero(entorno, monkeypatch, fijar_hora):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    fijar_hora(datetime(2026, 11, 14, 10, 0, 0))
    b = entorno.banca(saldo=8000, usuario="ciclo1", clave="prueba123")
    uid = _id(entorno, "ciclo1")
    lot = entorno.sorteo_id("LOTEDOM")
    entorno.c.post("/comisiones", json={"usuario_id": uid, "porcentaje": 15}, headers=entorno.admin)
    entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [lot], "numeros": "41", "monto": 1000}])

    det = _detalle(entorno, uid)
    assert det["resumen"]["ventas_ciclo"] == "1000.00"
    assert det["comision"]["comision_pendiente"] == "150.00"
    assert det["comision"]["puede_cerrar_ciclo"] is False
    assert any("MI CAJA" in x for x in det["comision"]["bloqueos_cierre"])

    # Cierre bloqueado con caja pendiente.
    bloqueado = entorno.c.post("/comisiones/cierres", json={
        "usuario_id": uid, "operacion_id": "cierre-bloqueado", "monto": 150,
    }, headers=entorno.admin)
    assert bloqueado.status_code == 409

    # Pago parcial: no cierra.
    parcial = entorno.c.post("/comisiones/pagos", json={
        "usuario_id": uid, "monto": 50, "operacion_id": "pago-ciclo-parcial",
    }, headers=entorno.admin)
    assert parcial.status_code == 201, parcial.text
    det2 = _detalle(entorno, uid)
    assert det2["comision"]["comision_pendiente"] == "100.00"
    assert det2["resumen"]["ventas_ciclo"] == "1000.00"
    assert entorno.c.get("/comisiones/cierres?usuario_id=" + str(uid), headers=entorno.admin).json() == []

    general_antes = entorno.saldo(b["sucursal"]["id"])
    _entregar_todo(entorno, b["headers"], "ent-ciclo-1")
    assert entorno.saldo(b["sucursal"]["id"]) == general_antes

    # Cierre con monto incompleto rechazado.
    incompleto = entorno.c.post("/comisiones/cierres", json={
        "usuario_id": uid, "operacion_id": "cierre-incompleto", "monto": 50,
    }, headers=entorno.admin)
    assert incompleto.status_code == 400

    cierre = entorno.c.post("/comisiones/cierres", json={
        "usuario_id": uid, "operacion_id": "cierre-ok-1", "monto": 100,
    }, headers=entorno.admin)
    assert cierre.status_code == 201, cierre.text
    assert cierre.json()["cierre"]["ventas_ciclo"] == "1000.00"
    assert cierre.json()["cierre"]["comision_pagada_en_cierre"] == "100.00"
    assert cierre.json()["ciclo_nuevo"]["ventas_ciclo"] == "0.00"
    assert cierre.json()["comision_nueva"]["comision_pendiente"] == "0.00"
    assert cierre.json()["descuenta_mi_caja"] is False

    # Idempotencia.
    rep = entorno.c.post("/comisiones/cierres", json={
        "usuario_id": uid, "operacion_id": "cierre-ok-1", "monto": 100,
    }, headers=entorno.admin)
    assert rep.status_code == 201
    assert rep.json()["cierre"]["id"] == cierre.json()["cierre"]["id"]

    det3 = _detalle(entorno, uid)
    assert det3["resumen"]["ventas_ciclo"] == "0.00"
    assert det3["resumen"]["premios_pagados"] == "0.00"
    assert det3["resumen"]["tickets_vendidos"] == 0
    assert det3["comision"]["comision_pendiente"] == "0.00"
    assert det3["comision"]["comision_acumulada"] == "0.00"
    assert len(det3["comision"]["historial_cierres"]) == 1
    assert float(det3["resumen"]["mi_caja"]) == 0
    assert entorno.saldo(b["sucursal"]["id"]) == general_antes

    # Nueva venta tras cierre acumula de nuevo.
    fijar_hora(datetime(2026, 11, 14, 11, 0, 0))
    entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [lot], "numeros": "42", "monto": 200}])
    det4 = _detalle(entorno, uid)
    assert det4["resumen"]["ventas_ciclo"] == "200.00"
    assert det4["comision"]["comision_pendiente"] == "30.00"
    assert det4["comision"]["comision_acumulada"] == "30.00"

    db = nueva_sesion()
    assert db.query(CierreCicloCajera).filter_by(operacion_id="cierre-ok-1").count() == 1
    db.close()


def test_cierre_con_porcentaje_cero_sin_pago(entorno, monkeypatch, fijar_hora):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    fijar_hora(datetime(2026, 11, 14, 10, 0, 0))
    b = entorno.banca(saldo=5000, usuario="ciclo0", clave="prueba123")
    uid = _id(entorno, "ciclo0")
    lot = entorno.sorteo_id("LOTEDOM")
    # Sin asignar % (0%): ventas no generan comisión; igual se puede cerrar tras conciliar.
    entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [lot], "numeros": "51", "monto": 300}])
    det = _detalle(entorno, uid)
    assert det["resumen"]["ventas_ciclo"] == "300.00"
    assert det["comision"]["comision_pendiente"] == "0.00"
    assert det["comision"]["puede_cerrar_ciclo"] is False
    _entregar_todo(entorno, b["headers"], "ent-ciclo-0")
    det2 = _detalle(entorno, uid)
    assert det2["comision"]["puede_cerrar_ciclo"] is True
    cierre = entorno.c.post("/comisiones/cierres", json={
        "usuario_id": uid, "operacion_id": "cierre-cero-1",
    }, headers=entorno.admin)
    assert cierre.status_code == 201, cierre.text
    assert cierre.json()["pago"] is None
    assert cierre.json()["ciclo_nuevo"]["ventas_ciclo"] == "0.00"
    assert _detalle(entorno, uid)["resumen"]["ventas_ciclo"] == "0.00"


def test_anulacion_y_porcentajes_en_ciclo(entorno, monkeypatch, fijar_hora):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    fijar_hora(datetime(2026, 11, 14, 10, 0, 0))
    a = entorno.banca(saldo=7000, usuario="ciclo_pct", clave="prueba123")
    otra = entorno.banca(saldo=3000, codigo="9901", nombre="OTRA CICLO", usuario="ciclo_otra", clave="prueba123")
    uid = _id(entorno, "ciclo_pct")
    uid2 = _id(entorno, "ciclo_otra")
    lot = entorno.sorteo_id("LOTEDOM")
    entorno.c.post("/comisiones", json={"usuario_id": uid, "porcentaje": 10}, headers=entorno.admin)
    entorno.c.post("/comisiones", json={"usuario_id": uid2, "porcentaje": 15}, headers=entorno.admin)
    entorno.vender_ok(a["headers"], [{"tipo": "QN", "sorteos": [lot], "numeros": "61", "monto": 500}])
    anulado = entorno.vender_ok(a["headers"], [{"tipo": "QN", "sorteos": [lot], "numeros": "62", "monto": 100}])
    entorno.c.post("/terminal/tickets/anular", json={
        "id": anulado["id"], "serial": anulado["serial"], "motivo": "error",
    }, headers=a["headers"])
    fijar_hora(datetime(2026, 11, 14, 11, 0, 0))
    entorno.c.post("/comisiones", json={"usuario_id": uid, "porcentaje": 15}, headers=entorno.admin)
    entorno.vender_ok(a["headers"], [{"tipo": "QN", "sorteos": [lot], "numeros": "63", "monto": 200}])
    entorno.vender_ok(otra["headers"], [{"tipo": "QN", "sorteos": [lot], "numeros": "64", "monto": 900}])

    det = _detalle(entorno, uid)
    # 500×10% + 200×15% = 80; anulado fuera; otra sucursal fuera.
    assert det["resumen"]["ventas_ciclo"] == "700.00"
    assert det["comision"]["comision_acumulada"] == "80.00"
    assert det["comision"]["comision_pendiente"] == "80.00"
    assert _detalle(entorno, uid2)["comision"]["comision_pendiente"] == "135.00"
