"""Pago de comisión pendiente: acumulación, parcial/total, aislamiento y cajas intactas."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from apps.api import db as dbmod
from apps.api.db import nueva_sesion
from apps.api.models import PagoComision, Usuario
from apps.api.security import hash_clave


def _id(entorno, usuario, headers=None):
    headers = headers or entorno.admin
    for fila in entorno.c.get("/usuarios", headers=headers).json():
        if fila["usuario"] == usuario:
            return fila["id"]
    raise AssertionError(usuario)


def _detalle(entorno, usuario_id, desde="2026-11-14", hasta="2026-11-14", headers=None):
    headers = headers or entorno.admin
    r = entorno.c.get(
        f"/reportes/ventas-cajeros/{usuario_id}?desde={desde}&hasta={hasta}",
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return r.json()


def _super(entorno):
    db = dbmod.nueva_sesion()
    try:
        existente = db.query(Usuario).filter_by(usuario="JDMCASHNOW").first()
        if existente is None:
            db.add(Usuario(
                nombre="JDMCASHNOW", usuario="JDMCASHNOW", rol="super_admin",
                sucursal_id=None, activo=True, eliminado=False, suspendido=False,
                estado_aprobacion="aprobado", clave_hash=hash_clave("SuperTest123!"),
            ))
        else:
            existente.rol = "super_admin"
            existente.activo = True
            existente.eliminado = False
            existente.suspendido = False
            existente.estado_aprobacion = "aprobado"
            existente.clave_hash = hash_clave("SuperTest123!")
        db.commit()
    finally:
        db.close()
    login = entorno.c.post("/auth/login", json={"usuario": "JDMCASHNOW", "clave": "SuperTest123!"})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['token']}"}


def test_acumula_anula_paga_parcial_total_y_nueva_venta(entorno, monkeypatch, fijar_hora):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    fijar_hora(datetime(2026, 11, 14, 10, 0, 0))
    b = entorno.banca(saldo=9000, nombre="BANCA CASTILLO", usuario="wanda_pay", clave="prueba123")
    jose = _id(entorno, "wanda_pay")
    lot = entorno.sorteo_id("LOTEDOM")

    # Sin %: venta no genera comisión; auditoría la reporta.
    entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [lot], "numeros": "10", "monto": 100}])
    audit = entorno.c.get(
        f"/comisiones/auditoria-sin-porcentaje?usuario_id={jose}",
        headers=entorno.admin,
    )
    assert audit.status_code == 200, audit.text
    assert audit.json()["ajuste_automatico"] is False
    assert audit.json()["total"] >= 1

    fijar_hora(datetime(2026, 11, 14, 10, 30, 0))
    assert entorno.c.post(
        "/comisiones", json={"usuario_id": jose, "porcentaje": 15}, headers=entorno.admin,
    ).status_code == 201

    # 1000 × 15% = 150; anulado no cuenta.
    entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [lot], "numeros": "11", "monto": 1000}])
    anulado = entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [lot], "numeros": "12", "monto": 400}])
    entorno.c.post(
        "/terminal/tickets/anular",
        json={"id": anulado["id"], "serial": anulado["serial"], "motivo": "error"},
        headers=b["headers"],
    )
    det = _detalle(entorno, jose)
    com = det["comision"]
    assert com["comision_acumulada"] == "150.00"
    assert com["comision_pagada"] == "0.00"
    assert com["comision_pendiente"] == "150.00"
    assert com["comision_periodo"] == "150.00"
    assert com["descuenta_mi_caja"] is False

    caja_antes = entorno.c.get("/terminal/sorteos", headers=b["headers"]).json()["mi_caja"]
    general_antes = entorno.saldo(b["sucursal"]["id"])

    # Pago parcial 50.
    parcial = entorno.c.post("/comisiones/pagos", json={
        "usuario_id": jose, "monto": 50, "operacion_id": "pago-parcial-1",
    }, headers=entorno.admin)
    assert parcial.status_code == 201, parcial.text
    assert parcial.json()["monto"] == "50.00"
    assert parcial.json()["saldo_pendiente"] == "100.00"
    assert parcial.json()["descuenta_mi_caja"] is False

    # Doble clic / reintento misma operación: idempotente.
    repetido = entorno.c.post("/comisiones/pagos", json={
        "usuario_id": jose, "monto": 50, "operacion_id": "pago-parcial-1",
    }, headers=entorno.admin)
    assert repetido.status_code == 201
    assert repetido.json()["id"] == parcial.json()["id"]
    assert repetido.json()["saldo_pendiente"] == "100.00"

    # Exceso rechazado.
    exceso = entorno.c.post("/comisiones/pagos", json={
        "usuario_id": jose, "monto": 100.01, "operacion_id": "pago-exceso",
    }, headers=entorno.admin)
    assert exceso.status_code == 400

    # Pago total del pendiente.
    total = entorno.c.post("/comisiones/pagos", json={
        "usuario_id": jose, "monto": 100, "operacion_id": "pago-total-1",
    }, headers=entorno.admin)
    assert total.status_code == 201, total.text
    assert total.json()["saldo_pendiente"] == "0.00"

    assert entorno.c.get("/terminal/sorteos", headers=b["headers"]).json()["mi_caja"] == caja_antes
    assert entorno.saldo(b["sucursal"]["id"]) == general_antes

    det2 = _detalle(entorno, jose)
    assert det2["comision"]["comision_pendiente"] == "0.00"
    assert det2["comision"]["comision_pagada"] == "150.00"
    assert det2["comision"]["comision_acumulada"] == "150.00"
    assert len(det2["comision"]["historial_pagos"]) == 2

    # Nueva venta tras pago: acumula de nuevo (hora distinta al cambio de %).
    fijar_hora(datetime(2026, 11, 14, 15, 0, 0))
    tarde = entorno.sorteo_id("Leidsa 3:55 PM")
    entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [tarde], "numeros": "13", "monto": 200}])
    fijar_hora(datetime(2026, 11, 14, 15, 10, 0))
    # Cambio de % no reescribe la venta anterior.
    assert entorno.c.post(
        "/comisiones", json={"usuario_id": jose, "porcentaje": 10}, headers=entorno.admin,
    ).status_code == 201
    fijar_hora(datetime(2026, 11, 14, 15, 20, 0))
    entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [tarde], "numeros": "14", "monto": 100}])
    # acumulada = 150 + 200×15% + 100×10% = 190; pagada 150; pendiente 40
    det3 = _detalle(entorno, jose)
    assert det3["comision"]["comision_acumulada"] == "190.00"
    assert det3["comision"]["comision_pagada"] == "150.00"
    assert det3["comision"]["comision_pendiente"] == "40.00"
    assert det3["comision"]["porcentaje_vigente"] == "10"
    # Los pagos previos no alteraron cajas; el Banco General sigue igual.
    assert entorno.saldo(b["sucursal"]["id"]) == general_antes

    hist = entorno.c.get(f"/comisiones/pagos?usuario_id={jose}", headers=entorno.admin)
    assert hist.status_code == 200
    assert len(hist.json()) == 2
    assert hist.json()[0]["administrador"]

    db = nueva_sesion()
    assert db.query(PagoComision).filter_by(usuario_id=jose).count() == 2
    db.close()


def test_aislamiento_sucursales_y_pagos_simultaneos(entorno, monkeypatch, fijar_hora):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    monkeypatch.delenv("COMPAT_GLOBAL_FORZADO", raising=False)
    fijar_hora(datetime(2026, 11, 14, 11, 0, 0))
    super_h = _super(entorno)
    entorno.super_admin = super_h

    a = entorno.banca(saldo=5000, codigo="1308", nombre="BANCA CASTILLO", usuario="caj_a", clave="prueba123")
    b = entorno.banca(saldo=5000, codigo="2200", nombre="BANCA PEGUERO", usuario="caj_b", clave="prueba123")
    id_a = _id(entorno, "caj_a", super_h)
    id_b = _id(entorno, "caj_b", super_h)
    lot = entorno.sorteo_id("LOTEDOM")
    entorno.c.post("/comisiones", json={"usuario_id": id_a, "porcentaje": 15}, headers=super_h)
    entorno.c.post("/comisiones", json={"usuario_id": id_b, "porcentaje": 15}, headers=super_h)
    entorno.vender_ok(a["headers"], [{"tipo": "QN", "sorteos": [lot], "numeros": "21", "monto": 1000}])
    entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [lot], "numeros": "22", "monto": 1000}])

    # Admin de sucursal B no puede pagar a cajera de A.
    adm_b = entorno.c.post("/usuarios", json={
        "nombre": "Admin Peguero", "usuario": "adm_peg_pay", "clave": "AdminPeg123!",
        "rol": "admin", "sucursal_id": b["sucursal"]["id"], "activo": True,
    }, headers=super_h)
    assert adm_b.status_code in (200, 201), adm_b.text
    login_b = entorno.c.post("/auth/login", json={"usuario": "adm_peg_pay", "clave": "AdminPeg123!"})
    assert login_b.status_code == 200, login_b.text
    headers_b = {"Authorization": f"Bearer {login_b.json()['token']}"}
    ajeno = entorno.c.post("/comisiones/pagos", json={
        "usuario_id": id_a, "monto": 10, "operacion_id": "pago-ajeno",
    }, headers=headers_b)
    assert ajeno.status_code in (401, 403, 404)

    # Carrera serializada: dos cobros de 100 sobre pendiente 150 → uno debe fallar.
    r1 = entorno.c.post("/comisiones/pagos", json={
        "usuario_id": id_a, "monto": 100, "operacion_id": "pago-sim-1",
    }, headers=super_h)
    r2 = entorno.c.post("/comisiones/pagos", json={
        "usuario_id": id_a, "monto": 100, "operacion_id": "pago-sim-2",
    }, headers=super_h)
    assert r1.status_code == 201, r1.text
    assert r2.status_code == 400, r2.text

    # Hilos concurrentes: no pueden dejar pagado > acumulado (FOR UPDATE / chequeo).
    def _pagar(op, monto):
        return entorno.c.post("/comisiones/pagos", json={
            "usuario_id": id_b, "monto": monto, "operacion_id": op,
        }, headers=super_h)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futuros = [
            pool.submit(_pagar, "pago-sim-b1", 100),
            pool.submit(_pagar, "pago-sim-b2", 100),
        ]
        resultados = [f.result() for f in as_completed(futuros)]
    det_b = _detalle(entorno, id_b, headers=super_h)
    pagada_b = float(det_b["comision"]["comision_pagada"])
    pendiente_b = float(det_b["comision"]["comision_pendiente"])
    assert pagada_b <= 150.0001
    assert abs((pagada_b + pendiente_b) - 150.0) < 0.001 or float(det_b["comision"]["pagado_en_exceso"]) > 0
    assert pendiente_b == max(0.0, 150.0 - pagada_b)
    assert any(r.status_code == 201 for r in resultados)

    det_a = _detalle(entorno, id_a, headers=super_h)
    assert det_a["comision"]["comision_pagada"] == "100.00"
    assert det_a["comision"]["comision_pendiente"] == "50.00"
    # Sucursales aisladas: pendiente de B no afecta a A.
    assert det_a["comision"]["comision_acumulada"] == "150.00"


def test_historial_persiste_tras_reinicio_sesion_db(entorno, monkeypatch, fijar_hora):
    """Los pagos viven en tabla propia; una sesión nueva los sigue leyendo."""
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    fijar_hora(datetime(2026, 11, 14, 10, 30, 0))
    b = entorno.banca(saldo=3000, usuario="caj_hist", clave="prueba123")
    jose = _id(entorno, "caj_hist")
    lot = entorno.sorteo_id("LOTEDOM")
    entorno.c.post("/comisiones", json={"usuario_id": jose, "porcentaje": 15}, headers=entorno.admin)
    entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [lot], "numeros": "30", "monto": 200}])
    pago = entorno.c.post("/comisiones/pagos", json={
        "usuario_id": jose, "monto": 15, "operacion_id": "pago-hist-1",
    }, headers=entorno.admin)
    assert pago.status_code == 201, pago.text

    db1 = nueva_sesion()
    n1 = db1.query(PagoComision).filter_by(operacion_id="pago-hist-1").count()
    db1.close()
    db2 = nueva_sesion()
    n2 = db2.query(PagoComision).filter_by(operacion_id="pago-hist-1").count()
    fila = db2.query(PagoComision).filter_by(operacion_id="pago-hist-1").one()
    assert n1 == n2 == 1
    assert str(fila.monto) in ("15", "15.00", "15.0")
    db2.close()
    lista = entorno.c.get(f"/comisiones/pagos?usuario_id={jose}", headers=entorno.admin).json()
    assert lista[0]["operacion_id"] == "pago-hist-1"
    assert lista[0]["saldo_pendiente"] == "15.00"
