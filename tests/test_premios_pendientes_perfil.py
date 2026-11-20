"""Tarjeta PREMIOS PENDIENTES en el perfil individual del cajero.

Misma fuente que el cierre de ciclo (premios_pendientes_mios / cond_cierre).
Solo lectura: no altera pago ni contabilidad. Local / SQLite.
"""


def _uid(entorno, usuario):
    for u in entorno.c.get("/usuarios", headers=entorno.admin).json():
        if u["usuario"] == usuario:
            return u["id"]
    raise AssertionError(usuario)


def _fondo(entorno, usuario, sucursal_id, monto, op):
    r = entorno.c.post("/fondos", json={
        "sucursal_id": sucursal_id, "usuario_id": _uid(entorno, usuario),
        "monto": monto, "tipo": "aporte_prueba", "operacion_id": op,
    }, headers=entorno.admin)
    assert r.status_code == 201, r.text


def _simular(entorno, sorteo, p1, p2=1, p3=2, fecha="2026-11-14"):
    r = entorno.c.post("/resultados", json={
        "sorteo_id": sorteo, "fecha": fecha,
        "premio1": p1, "premio2": p2, "premio3": p3, "simulado": True,
    }, headers=entorno.admin)
    assert r.status_code == 201, r.text
    return r.json()


def _detalle(entorno, usuario_id):
    r = entorno.c.get(
        f"/reportes/ventas-cajeros/{usuario_id}?desde=2026-11-14&hasta=2026-11-14",
        headers=entorno.admin,
    )
    assert r.status_code == 200, r.text
    return r.json()


def _pagar(entorno, headers, ticket, op):
    r = entorno.c.post("/terminal/tickets/pagar", json={
        "id": ticket["id"], "serial": ticket["serial"], "operacion_id": op,
    }, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def test_sin_premios_pendientes_cero(entorno, monkeypatch):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    b = entorno.banca(saldo=5000, codigo="PP00", usuario="ppcero", clave="prueba123")
    _fondo(entorno, "ppcero", b["sucursal"]["id"], 1000, "fondo-pp-0")
    lot = entorno.sorteo_id("LOTEDOM")
    entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [lot], "numeros": "99", "monto": 10}])
    det = _detalle(entorno, _uid(entorno, "ppcero"))
    assert det["resumen"]["premios_pendientes"] == "0.00"
    assert det["comision"]["premios_pendientes"] == "0.00"


def test_un_premio_pendiente_y_coincide_con_cierre(entorno, monkeypatch):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    b = entorno.banca(saldo=5000, codigo="PP01", usuario="ppuno", clave="prueba123")
    _fondo(entorno, "ppuno", b["sucursal"]["id"], 5000, "fondo-pp-1")
    lot = entorno.sorteo_id("LOTEDOM")
    entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [lot], "numeros": "25", "monto": 10}])
    _simular(entorno, lot, 25)
    uid = _uid(entorno, "ppuno")
    det = _detalle(entorno, uid)
    assert det["resumen"]["premios_pendientes"] == "600.00"
    assert det["comision"]["premios_pendientes"] == "600.00"
    assert det["resumen"]["premios_pendientes"] == det["comision"]["premios_pendientes"]


def test_varios_premios_pendientes(entorno, monkeypatch):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    b = entorno.banca(saldo=8000, codigo="PP02", usuario="ppvarios", clave="prueba123")
    _fondo(entorno, "ppvarios", b["sucursal"]["id"], 8000, "fondo-pp-2")
    lot = entorno.sorteo_id("LOTEDOM")
    h = b["headers"]
    entorno.vender_ok(h, [{"tipo": "QN", "sorteos": [lot], "numeros": "25", "monto": 10}])
    entorno.vender_ok(h, [{"tipo": "QN", "sorteos": [lot], "numeros": "25", "monto": 20}])
    _simular(entorno, lot, 25)
    det = _detalle(entorno, _uid(entorno, "ppvarios"))
    # 10→600 + 20→1200 = 1800
    assert det["resumen"]["premios_pendientes"] == "1800.00"
    assert det["comision"]["premios_pendientes"] == "1800.00"


def test_ticket_multi_loteria_suma_solo_confirmadas(entorno, monkeypatch):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    b = entorno.banca(saldo=5000, codigo="PP03", usuario="ppmulti", clave="prueba123")
    _fondo(entorno, "ppmulti", b["sucursal"]["id"], 5000, "fondo-pp-3")
    lot = entorno.sorteo_id("LOTEDOM")
    anguila = entorno.sorteo_id("La Anguila 1:00 PM")
    h = b["headers"]
    entorno.vender_ok(h, [
        {"tipo": "QN", "sorteos": [lot], "numeros": "25", "monto": 10},
        {"tipo": "QN", "sorteos": [anguila], "numeros": "25", "monto": 5},
    ])
    _simular(entorno, lot, 25)
    det = _detalle(entorno, _uid(entorno, "ppmulti"))
    # Solo LOTEDOM confirmado: 600; Anguila sin resultado no suma.
    assert det["resumen"]["premios_pendientes"] == "600.00"
    _simular(entorno, anguila, 25)
    det2 = _detalle(entorno, _uid(entorno, "ppmulti"))
    # 600 + 300 = 900 (una sola suma del ticket, sin duplicar)
    assert det2["resumen"]["premios_pendientes"] == "900.00"


def test_parcial_y_pago_completo_actualizan_tarjeta(entorno, monkeypatch):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    b = entorno.banca(saldo=0, codigo="PP04", usuario="ppparcial", clave="prueba123")
    _fondo(entorno, "ppparcial", b["sucursal"]["id"], 10000, "fondo-pp-4")
    h = b["headers"]
    a11 = entorno.sorteo_id("La Anguila 11:00 AM")
    a12 = entorno.sorteo_id("La Anguila 12:00 PM")
    ticket = entorno.vender_ok(h, [
        {"tipo": "QN", "sorteos": [a11, a12], "numeros": "25", "monto": 5},
    ])
    _simular(entorno, a11, 25)
    uid = _uid(entorno, "ppparcial")
    assert _detalle(entorno, uid)["resumen"]["premios_pendientes"] == "300.00"
    pago = _pagar(entorno, h, ticket, "pp-parcial-1")
    assert pago["estado"] == "parcial"
    assert _detalle(entorno, uid)["resumen"]["premios_pendientes"] == "0.00"
    _simular(entorno, a12, 25)
    assert _detalle(entorno, uid)["resumen"]["premios_pendientes"] == "300.00"
    pago2 = _pagar(entorno, h, ticket, "pp-parcial-2")
    assert pago2["estado"] == "pagado"
    assert _detalle(entorno, uid)["resumen"]["premios_pendientes"] == "0.00"


def test_anulado_y_no_ganador_excluidos(entorno, monkeypatch):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    b = entorno.banca(saldo=5000, codigo="PP05", usuario="ppanula", clave="prueba123")
    _fondo(entorno, "ppanula", b["sucursal"]["id"], 5000, "fondo-pp-5")
    h = b["headers"]
    lot = entorno.sorteo_id("LOTEDOM")
    anulado = entorno.vender_ok(h, [{"tipo": "QN", "sorteos": [lot], "numeros": "25", "monto": 10}])
    entorno.c.post("/terminal/tickets/anular", json={
        "id": anulado["id"], "serial": anulado["serial"], "motivo": "error",
    }, headers=h)
    entorno.vender_ok(h, [{"tipo": "QN", "sorteos": [lot], "numeros": "99", "monto": 10}])
    _simular(entorno, lot, 25)
    det = _detalle(entorno, _uid(entorno, "ppanula"))
    assert det["resumen"]["premios_pendientes"] == "0.00"


def test_aislamiento_por_cajero_y_sucursal(entorno, monkeypatch):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    a = entorno.banca(saldo=5000, codigo="PP06", usuario="ppa", clave="prueba123")
    entorno.operador("ppb", "prueba123", a["sucursal"]["id"])
    _fondo(entorno, "ppa", a["sucursal"]["id"], 5000, "fondo-ppa")
    _fondo(entorno, "ppb", a["sucursal"]["id"], 5000, "fondo-ppb")
    otra = entorno.banca(saldo=5000, codigo="PP07", nombre="OTRA PP", usuario="ppc", clave="prueba123")
    _fondo(entorno, "ppc", otra["sucursal"]["id"], 5000, "fondo-ppc")
    lot = entorno.sorteo_id("LOTEDOM")
    ha = entorno.login_terminal("ppa", "prueba123")
    hb = entorno.login_terminal("ppb", "prueba123")
    hc = otra["headers"]
    entorno.vender_ok(ha, [{"tipo": "QN", "sorteos": [lot], "numeros": "25", "monto": 10}])
    entorno.vender_ok(hb, [{"tipo": "QN", "sorteos": [lot], "numeros": "25", "monto": 20}])
    entorno.vender_ok(hc, [{"tipo": "QN", "sorteos": [lot], "numeros": "25", "monto": 50}])
    _simular(entorno, lot, 25)
    assert _detalle(entorno, _uid(entorno, "ppa"))["resumen"]["premios_pendientes"] == "600.00"
    assert _detalle(entorno, _uid(entorno, "ppb"))["resumen"]["premios_pendientes"] == "1200.00"
    assert _detalle(entorno, _uid(entorno, "ppc"))["resumen"]["premios_pendientes"] == "3000.00"
