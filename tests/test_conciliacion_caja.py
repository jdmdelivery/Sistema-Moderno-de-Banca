"""MI CAJA y la recaudación del ciclo no son el mismo concepto.

MI CAJA = fondo asignado + recaudación − entregas.
La recaudación es ventas − anulaciones − premios pagados.
Un fondo que sigue en el cajón explica la diferencia y no se borra.
"""
from apps.api.db import nueva_sesion
from apps.api.models import MovimientoCajera, Usuario


def _cajera(entorno, usuario):
    for fila in entorno.c.get("/usuarios", headers=entorno.admin).json():
        if fila["usuario"] == usuario:
            return fila
    raise AssertionError(usuario)


def _caja(entorno, headers):
    r = entorno.c.get("/terminal/sorteos", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _asignar(entorno, cajera_id, sucursal_id, monto, operacion):
    r = entorno.c.post("/fondos", json={
        "sucursal_id": sucursal_id,
        "usuario_id": cajera_id,
        "monto": monto,
        "tipo": "aporte_prueba",
        "operacion_id": operacion,
    }, headers=entorno.admin)
    assert r.status_code == 201, r.text
    return r.json()


def test_mil_pesos_de_fondo_explican_4718_contra_3718(entorno, monkeypatch):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    b = entorno.banca(saldo=5764, nombre="BANCA CASTILLO (PRUEBA)", usuario="0219", clave="prueba123")
    jose = _cajera(entorno, "0219")
    _asignar(entorno, jose["id"], b["sucursal"]["id"], 1000, "fondo-jose-1000")
    loteria = entorno.sorteo_id("LOTEDOM")
    entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [loteria], "numeros": "11", "monto": 3510}])
    entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [loteria], "numeros": "22", "monto": 208}])
    caja = _caja(entorno, b["headers"])
    assert caja["mi_caja"] == "4718.00"
    assert caja["recaudacion_ciclo"] == "3718.00"
    assert caja["fondo_asignado"] == "1000.00"
    assert caja["entregas_ciclo"] == "0.00"
    assert caja["cuadre"] == "4718.00"
    assert caja["diferencia"] == "0.00"
    assert entorno.saldo(b["sucursal"]["id"]) == 5764


def test_el_premio_resta_una_vez_y_el_fondo_sigue_en_la_caja(entorno, monkeypatch):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    b = entorno.banca(saldo=5764, nombre="BANCA CASTILLO (PRUEBA)", usuario="0219", clave="prueba123")
    jose = _cajera(entorno, "0219")
    _asignar(entorno, jose["id"], b["sucursal"]["id"], 1000, "fondo-para-premio")
    loteria = entorno.sorteo_id("LOTEDOM")
    ticket = entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [loteria], "numeros": "25", "monto": 10}])
    simulado = entorno.c.post("/resultados", json={
        "sorteo_id": loteria, "fecha": "2026-11-14",
        "premio1": 25, "premio2": 54, "premio3": 78, "simulado": True,
    }, headers=entorno.admin)
    assert simulado.status_code == 201, simulado.text
    antes = _caja(entorno, b["headers"])
    assert antes["mi_caja"] == "1010.00"
    assert antes["recaudacion_ciclo"] == "10.00"
    assert antes["fondo_asignado"] == "1000.00"
    pago = entorno.c.post("/terminal/tickets/pagar", json={
        "id": ticket["id"], "serial": ticket["serial"], "operacion_id": "pago-unico-600",
    }, headers=b["headers"])
    assert pago.status_code == 200, pago.text
    assert pago.json()["mi_caja"] == "410.00"
    assert pago.json()["recaudacion_ciclo"] == "-590.00"
    assert pago.json()["fondo_asignado"] == "1000.00"
    assert pago.json()["diferencia"] == "0.00"
    repetido = entorno.c.post("/terminal/tickets/pagar", json={
        "id": ticket["id"], "serial": ticket["serial"], "operacion_id": "pago-unico-600-otra",
    }, headers=b["headers"])
    assert repetido.status_code == 409
    despues = _caja(entorno, b["headers"])
    assert despues["mi_caja"] == "410.00"
    assert despues["recaudacion_ciclo"] == "-590.00"
    db = nueva_sesion()
    usuario = db.query(Usuario).filter_by(usuario="0219").one()
    pagos = db.query(MovimientoCajera).filter_by(usuario_id=usuario.id, tipo="pago_premio_prueba").all()
    assert len(pagos) == 1
    assert str(pagos[0].monto) == "600.00" or float(pagos[0].monto) == 600
    db.close()
    assert entorno.saldo(b["sucursal"]["id"]) == 5764


def test_la_entrega_parcial_baja_la_caja_y_no_la_recaudacion(entorno, monkeypatch):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    b = entorno.banca(saldo=5764, usuario="0219", clave="prueba123")
    jose = _cajera(entorno, "0219")
    _asignar(entorno, jose["id"], b["sucursal"]["id"], 1000, "fondo-entrega")
    loteria = entorno.sorteo_id("LOTEDOM")
    entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [loteria], "numeros": "11", "monto": 500}])
    entrega = entorno.c.post("/terminal/entregas", json={
        "monto": 200, "operacion_id": "entrega-parcial-200",
    }, headers=b["headers"])
    assert entrega.status_code == 201, entrega.text
    caja = _caja(entorno, b["headers"])
    assert caja["fondo_asignado"] == "1000.00"
    assert caja["recaudacion_ciclo"] == "500.00"
    assert caja["entregas_ciclo"] == "200.00"
    assert caja["mi_caja"] == "1300.00"
    assert caja["cuadre"] == "1300.00"
    assert caja["diferencia"] == "0.00"
    assert entorno.saldo(b["sucursal"]["id"]) == 5764
