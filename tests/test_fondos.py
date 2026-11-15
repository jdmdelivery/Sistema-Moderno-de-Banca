"""Fondo asignado por el administrador. No es una venta y no mezcla cajas."""


def _cajera(entorno, usuario):
    for fila in entorno.c.get("/usuarios", headers=entorno.admin).json():
        if fila["usuario"] == usuario:
            return fila
    raise AssertionError(usuario)


def _mi_caja(entorno, headers):
    return entorno.c.get("/terminal/sorteos", headers=headers).json()["mi_caja"]


def _asignar(entorno, cajera, sucursal_id, monto, tipo, operacion, motivo="Fondo de prueba"):
    return entorno.c.post("/fondos", json={
        "sucursal_id": sucursal_id,
        "usuario_id": cajera,
        "monto": monto,
        "tipo": tipo,
        "operacion_id": operacion,
        "motivo": motivo,
    }, headers=entorno.admin)


def test_aporte_de_prueba_no_toca_la_caja_general_ni_la_venta(entorno, monkeypatch):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    b = entorno.banca(saldo=5764, nombre="BANCA CASTILLO (PRUEBA)", usuario="jose", clave="prueba123")
    entorno.operador("ana", "prueba123", b["sucursal"]["id"])
    ana = entorno.login_terminal("ana", "prueba123")
    sorteo = entorno.sorteo_id("LOTEDOM")
    horas = next(s for s in entorno.c.get("/sorteos", headers=entorno.admin).json() if s["nombre"] == "Lotedom 12:00 PM")
    assert len(entorno.c.get("/sorteos", headers=entorno.admin).json()) == 40
    entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [sorteo], "numeros": "25", "monto": 10}])
    jose = _cajera(entorno, "jose")
    ana_id = _cajera(entorno, "ana")["id"]
    r = _asignar(entorno, jose["id"], b["sucursal"]["id"], 1000, "aporte_prueba", "fondo-jose-1000")
    assert r.status_code == 201, r.text
    cuerpo = r.json()
    assert cuerpo["etiqueta"] == "FONDO ASIGNADO POR ADMINISTRADOR"
    assert cuerpo["origen"] == "Aporte de prueba"
    assert cuerpo["es_venta"] is False
    assert cuerpo["sale_de_caja_general"] is False
    assert cuerpo["incluido_en_caja_general"] is False
    assert cuerpo["creado_en"].startswith("2026-11-14 10:00")
    assert cuerpo["motivo"] == "Fondo de prueba"
    assert _mi_caja(entorno, b["headers"]) == "1010.00"
    assert _mi_caja(entorno, ana) == "0.00"
    assert entorno.saldo(b["sucursal"]["id"]) == 5764
    repetida = _asignar(entorno, jose["id"], b["sucursal"]["id"], 1000, "aporte_prueba", "fondo-jose-1000")
    assert repetida.status_code == 201
    assert _mi_caja(entorno, b["headers"]) == "1010.00"
    assert len(entorno.c.get("/fondos", headers=entorno.admin).json()) == 1
    ajena = _asignar(entorno, ana_id, b["sucursal"]["id"], 1000, "aporte_prueba", "fondo-jose-1000")
    assert ajena.status_code == 409
    assert _mi_caja(entorno, ana) == "0.00"
    sorteos = entorno.c.get("/terminal/sorteos", headers=b["headers"]).json()
    assert sorteos["recaudacion_ciclo"] == "10.00"
    assert "efectivo_pendiente" in sorteos and "entrega_pendiente" in sorteos
    dia = entorno.c.get("/terminal/reportes/dia", headers=b["headers"]).json()
    assert dia["prueba"]["ventas"] == "10.00"
    fila = next(s for s in entorno.c.get("/sucursales", headers=entorno.admin).json()
                if s["id"] == b["sucursal"]["id"])
    assert float(fila["saldo_actual"]) == 5764
    assert float(fila["consolidado_cajas"]["cajas_prueba"]) == 1010
    assert float(fila["saldo_actual"]) + float(fila["consolidado_cajas"]["cajas_prueba"]) != 5764 + 1010 + 1000
    despues = next(s for s in entorno.c.get("/sorteos", headers=entorno.admin).json() if s["nombre"] == "Lotedom 12:00 PM")
    assert despues["hora_cierre"] == horas["hora_cierre"] and despues["hora_sorteo"] == horas["hora_sorteo"]
    assert len(entorno.c.get("/sorteos", headers=entorno.admin).json()) == 40


def test_el_cajero_no_asigna_ni_consulta_fondos(entorno, monkeypatch):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    b = entorno.banca(saldo=5764, usuario="jose", clave="prueba123")
    jose = _cajera(entorno, "jose")
    for metodo, ruta in (("GET", "/fondos"), ("POST", "/fondos")):
        if metodo == "GET":
            respuesta = entorno.c.get(ruta, headers=b["headers"])
        else:
            respuesta = entorno.c.post(ruta, json={
                "sucursal_id": b["sucursal"]["id"], "usuario_id": jose["id"],
                "monto": 1000, "tipo": "aporte_prueba", "operacion_id": "fondo-propio",
            }, headers=b["headers"])
        assert respuesta.status_code == 401
    supervisor = entorno.c.post("/usuarios", json={
        "nombre": "Supervisor", "usuario": "sup1", "rol": "supervisor",
        "sucursal_id": b["sucursal"]["id"], "clave": "sup123",
    }, headers=entorno.admin)
    assert supervisor.status_code == 201, supervisor.text
    sesion = entorno.c.post("/auth/login", json={"usuario": "sup1", "clave": "sup123"})
    assert sesion.status_code == 200
    cabecera = {"Authorization": f"Bearer {sesion.json()['token']}"}
    assert entorno.c.get("/fondos", headers=cabecera).status_code == 403
    assert entorno.c.post("/fondos", json={
        "sucursal_id": b["sucursal"]["id"], "usuario_id": jose["id"],
        "monto": 50, "tipo": "aporte_prueba", "operacion_id": "fondo-supervisor",
    }, headers=cabecera).status_code == 403
    assert _mi_caja(entorno, b["headers"]) == "0.00"
    assert entorno.saldo(b["sucursal"]["id"]) == 5764


def test_transferencia_sale_de_la_caja_general_una_sola_vez(entorno):
    b = entorno.banca(saldo=5764, usuario="jose", clave="prueba123")
    jose = _cajera(entorno, "jose")
    r = _asignar(entorno, jose["id"], b["sucursal"]["id"], 1000, "transferencia_general", "fondo-real-1000", "")
    assert r.status_code == 201, r.text
    assert r.json()["sale_de_caja_general"] is True
    assert r.json()["incluido_en_caja_general"] is False
    assert entorno.saldo(b["sucursal"]["id"]) == 4764
    assert _mi_caja(entorno, b["headers"]) == "1000.00"
    assert _cajera(entorno, "jose")["saldo_caja_prueba"] == "0.00"
    fila = next(s for s in entorno.c.get("/sucursales", headers=entorno.admin).json()
                if s["id"] == b["sucursal"]["id"])
    assert float(fila["consolidado_cajas"]["cajas_reales"]) == 1000
    assert float(fila["saldo_actual"]) == 4764
    corta = entorno.banca(saldo=100, codigo="2200", nombre="BANCA PEGUERO", usuario="ana", clave="prueba123")
    ana = _cajera(entorno, "ana")
    rechazo = _asignar(entorno, ana["id"], corta["sucursal"]["id"], 1000, "transferencia_general", "fondo-sin-saldo")
    assert rechazo.status_code == 409
    assert entorno.saldo(corta["sucursal"]["id"]) == 100
    assert _mi_caja(entorno, corta["headers"]) == "0.00"


def test_dos_telefonos_ven_el_fondo_y_el_pago_sale_de_mi_caja(entorno, monkeypatch):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    entorno.banca(saldo=5764, usuario="jose", clave="prueba123")
    jose = _cajera(entorno, "jose")

    def entrar(serie):
        r = entorno.c.post("/terminal/login", json={
            "usuario": "jose", "clave": "prueba123", "dispositivo_id": serie,
        })
        assert r.status_code == 200, r.text
        return r.json()

    uno = entrar("TEL-FONDO-1")
    dos = entrar("TEL-FONDO-2")
    assert uno["terminal"]["id"] != dos["terminal"]["id"]
    h1 = {"Authorization": f"Bearer {uno['token']}"}
    h2 = {"Authorization": f"Bearer {dos['token']}"}
    sorteo = entorno.sorteo_id("LOTEDOM")
    ticket = entorno.vender_ok(h1, [{"tipo": "QN", "sorteos": [sorteo], "numeros": "25", "monto": 10}])
    r = _asignar(entorno, jose["id"], jose["sucursal_id"], 1000, "aporte_prueba", "fondo-dos-telefonos")
    assert r.status_code == 201, r.text
    assert _mi_caja(entorno, h1) == "1010.00"
    assert _mi_caja(entorno, h2) == "1010.00"
    simulado = entorno.c.post("/resultados", json={
        "sorteo_id": sorteo, "fecha": "2026-11-14",
        "premio1": 25, "premio2": 54, "premio3": 78, "simulado": True,
    }, headers=entorno.admin)
    assert simulado.status_code == 201, simulado.text
    pago = entorno.c.post("/terminal/tickets/pagar", json={
        "id": ticket["id"], "serial": ticket["serial"], "operacion_id": "pago-fondo-600",
    }, headers=h1)
    assert pago.status_code == 200, pago.text
    assert pago.json()["estado"] == "pagado"
    assert _mi_caja(entorno, h1) == "410.00"
    assert _mi_caja(entorno, h2) == "410.00"
    assert entorno.saldo(jose["sucursal_id"]) == 5764
    from apps.api.db import nueva_sesion
    from apps.api.models import FondoAsignado

    db = nueva_sesion()
    guardados = db.query(FondoAsignado).all()
    assert len(guardados) == 1
    assert str(guardados[0].monto) == "1000.00" or float(guardados[0].monto) == 1000
    db.close()
