"""VENTAS DEL DÍA: por cajera y fecha local America/Santo_Domingo."""
from datetime import datetime

from apps.api import servicios
from apps.api.db import nueva_sesion
from apps.api.models import Ticket


def _caja(entorno, headers):
    r = entorno.c.get("/terminal/sorteos", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def test_ventas_del_dia_empieza_en_cero_y_sube_con_venta(entorno, monkeypatch):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    b = entorno.banca(saldo=5764, usuario="jose", clave="prueba123")
    caja = _caja(entorno, b["headers"])
    assert caja["ventas_dia"] == "0.00"
    assert caja["fecha_local"] == "2026-11-14"
    assert caja["zona"] == "America/Santo_Domingo"
    sorteo = entorno.sorteo_id("LOTEDOM")
    entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [sorteo], "numeros": "11", "monto": 100}])
    entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [sorteo], "numeros": "22", "monto": 50}])
    despues = _caja(entorno, b["headers"])
    assert despues["ventas_dia"] == "150.00"
    assert despues["mi_caja"] == "150.00"


def test_anular_hoy_resta_ventas_y_premio_no(entorno, monkeypatch):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    b = entorno.banca(saldo=5764, usuario="jose", clave="prueba123")
    jose = next(u for u in entorno.c.get("/usuarios", headers=entorno.admin).json() if u["usuario"] == "jose")
    fondo = entorno.c.post("/fondos", json={
        "sucursal_id": b["sucursal"]["id"], "usuario_id": jose["id"], "monto": 1000,
        "tipo": "aporte_prueba", "operacion_id": "fondo-ventas-dia",
    }, headers=entorno.admin)
    assert fondo.status_code == 201, fondo.text
    sorteo = entorno.sorteo_id("LOTEDOM")
    t1 = entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [sorteo], "numeros": "25", "monto": 10}])
    t2 = entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [sorteo], "numeros": "25", "monto": 20}])
    assert _caja(entorno, b["headers"])["ventas_dia"] == "30.00"
    anula = entorno.c.post("/terminal/tickets/anular", json={
        "id": t2["id"], "serial": t2["serial"], "motivo": "error",
    }, headers=b["headers"])
    assert anula.status_code == 200, anula.text
    assert _caja(entorno, b["headers"])["ventas_dia"] == "10.00"
    assert _caja(entorno, b["headers"])["mi_caja"] == "1010.00"
    simulado = entorno.c.post("/resultados", json={
        "sorteo_id": sorteo, "fecha": "2026-11-14",
        "premio1": 25, "premio2": 54, "premio3": 78, "simulado": True,
    }, headers=entorno.admin)
    assert simulado.status_code == 201, simulado.text
    pago = entorno.c.post("/terminal/tickets/pagar", json={
        "id": t1["id"], "serial": t1["serial"], "operacion_id": "pago-ventas-dia",
    }, headers=b["headers"])
    assert pago.status_code == 200, pago.text
    despues = _caja(entorno, b["headers"])
    assert despues["ventas_dia"] == "10.00"
    assert despues["mi_caja"] == "410.00"


def test_medianoche_reinicia_ventas_y_conserva_mi_caja(entorno, monkeypatch, fijar_hora):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    b = entorno.banca(saldo=5764, usuario="jose", clave="prueba123")
    sorteo = entorno.sorteo_id("LOTEDOM")
    viejo = entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [sorteo], "numeros": "11", "monto": 200}])
    assert _caja(entorno, b["headers"])["ventas_dia"] == "200.00"
    assert _caja(entorno, b["headers"])["mi_caja"] == "200.00"
    # 10:00 del día siguiente: ya cambió la fecha local y hay sorteos abiertos.
    fijar_hora(datetime(2026, 11, 15, 10, 0, 0))
    # La sesión anterior puede vencer al saltar de día; se vuelve a autenticar.
    b["headers"] = entorno.login_terminal("jose", "prueba123")
    nuevo_dia = _caja(entorno, b["headers"])
    assert nuevo_dia["fecha_local"] == "2026-11-15"
    assert nuevo_dia["ventas_dia"] == "0.00"
    assert nuevo_dia["mi_caja"] == "200.00"
    entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [sorteo], "numeros": "33", "monto": 75}])
    assert _caja(entorno, b["headers"])["ventas_dia"] == "75.00"
    assert _caja(entorno, b["headers"])["mi_caja"] == "275.00"
    # Ticket de ayer anulado: no entra en ventas de hoy (vendido_en es del día anterior).
    db = nueva_sesion()
    ticket = db.get(Ticket, viejo["id"])
    ticket.estado = "anulado"
    db.commit()
    db.close()
    final = _caja(entorno, b["headers"])
    assert final["ventas_dia"] == "75.00"
    assert final["mi_caja"] == "275.00"


def test_dos_cajeras_ven_solo_sus_ventas(entorno, monkeypatch):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    b = entorno.banca(saldo=5764, usuario="jose", clave="prueba123")
    entorno.operador("ana", "prueba123", b["sucursal"]["id"])
    ana = entorno.login_terminal("ana", "prueba123")
    sorteo = entorno.sorteo_id("LOTEDOM")
    entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [sorteo], "numeros": "11", "monto": 40}])
    entorno.vender_ok(ana, [{"tipo": "QN", "sorteos": [sorteo], "numeros": "22", "monto": 90}])
    jose = _caja(entorno, b["headers"])
    ana_caja = _caja(entorno, ana)
    assert jose["ventas_dia"] == "40.00"
    assert jose["mi_caja"] == "40.00"
    assert ana_caja["ventas_dia"] == "90.00"
    assert ana_caja["mi_caja"] == "90.00"


def test_reintento_de_venta_no_duplica_ventas_del_dia(entorno, monkeypatch):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    b = entorno.banca(saldo=5764, usuario="jose", clave="prueba123")
    sorteo = entorno.sorteo_id("LOTEDOM")
    cuerpo = {
        "jugadas": [{"tipo": "QN", "sorteos": [sorteo], "numeros": "11", "monto": 25}],
        "operacion_id": "venta-unica-25",
    }
    uno = entorno.c.post("/terminal/venta", json=cuerpo, headers=b["headers"])
    dos = entorno.c.post("/terminal/venta", json=cuerpo, headers=b["headers"])
    assert uno.status_code == 201, uno.text
    assert dos.status_code == 201, dos.text
    assert uno.json()["id"] == dos.json()["id"]
    assert _caja(entorno, b["headers"])["ventas_dia"] == "25.00"
    db = nueva_sesion()
    assert db.query(Ticket).filter_by(operacion_id="venta-unica-25").count() == 1
    db.close()


def test_ventas_del_dia_usa_usuario_de_sesion(entorno, monkeypatch):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    from apps.api.models import Usuario
    b = entorno.banca(saldo=5764, usuario="jose", clave="prueba123")
    db = nueva_sesion()
    jose = db.query(Usuario).filter_by(usuario="jose").one()
    assert servicios.ventas_del_dia(db, jose) == "0.00"
    db.close()
    sorteo = entorno.sorteo_id("LOTEDOM")
    entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [sorteo], "numeros": "11", "monto": 15}])
    # La ruta /terminal/sorteos toma al operador de la sesión, no un id del teléfono.
    assert _caja(entorno, b["headers"])["ventas_dia"] == "15.00"
