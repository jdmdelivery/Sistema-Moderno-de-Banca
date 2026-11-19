"""El cajero no recibe la caja de la sucursal ni la caja de otro cajero."""


def test_administrador_ve_5764_y_el_cajero_no(entorno):
    b = entorno.banca(saldo=5764, nombre="BANCA CASTILLO (PRUEBA)", usuario="jose", clave="prueba123")
    sucursales = entorno.c.get("/sucursales", headers=entorno.admin).json()
    assert float(next(s["saldo_actual"] for s in sucursales if s["id"] == b["sucursal"]["id"])) == 5764
    usuarios = entorno.c.get("/usuarios", headers=entorno.admin).json()
    jose = next(u for u in usuarios if u["usuario"] == "jose")
    assert "saldo_caja" in jose and "saldo_caja_prueba" in jose

    login = entorno.c.post("/terminal/login", json={"usuario": "jose", "clave": "prueba123"})
    assert login.status_code == 200
    cuerpo = login.json()
    assert "saldo" not in cuerpo
    assert "saldo_actual" not in cuerpo["sucursal"]
    assert "saldo_caja" not in cuerpo["operador"]
    assert "5764" not in login.text
    sorteos = entorno.c.get("/terminal/sorteos", headers=b["headers"])
    assert sorteos.status_code == 200
    assert "saldo" not in sorteos.json()
    assert "mi_caja" in sorteos.json()
    assert "5764" not in sorteos.text
    assert entorno.saldo(b["sucursal"]["id"]) == 5764

    for ruta in (
        "/sucursales",
        "/usuarios",
        "/reportes/ventas?desde=2026-11-14&hasta=2026-11-14",
        f"/sucursales/{b['sucursal']['id']}/movimientos",
        "/ganadores",
    ):
        respuesta = entorno.c.get(ruta, headers=b["headers"])
        assert respuesta.status_code == 401, ruta
    panel = entorno.c.post("/auth/login", json={"usuario": "jose", "clave": "prueba123"})
    assert panel.status_code == 401
    assert entorno.saldo(b["sucursal"]["id"]) == 5764


def test_cajero_no_ve_ventas_ni_caja_de_otra_cajera(entorno):
    b = entorno.banca(saldo=5764, usuario="jose", clave="prueba123")
    antes = entorno.saldo(b["sucursal"]["id"])
    entorno.operador("ana", "prueba123", b["sucursal"]["id"])
    ana = entorno.login_terminal("ana", "prueba123")
    sorteo = entorno.sorteo_id("La Primera 12")
    ajeno = entorno.vender_ok(ana, [{"tipo": "QN", "sorteos": [sorteo], "numeros": "11", "monto": 10}])
    propio = entorno.c.get("/terminal/sorteos", headers=b["headers"]).json()
    ajena = entorno.c.get("/terminal/sorteos", headers=ana).json()
    assert propio["mi_caja"] == "0.00"
    assert ajena["mi_caja"] == "10.00"
    assert "saldo" not in propio and "saldo" not in ajena
    resumen = entorno.c.get(
        "/terminal/reportes/resumen?desde=2026-11-14&hasta=2026-11-14&vista=final",
        headers=b["headers"],
    )
    assert resumen.status_code == 200
    assert resumen.json()["total_tickets"] == 0
    assert ajeno["serial"] not in resumen.text
    # Spoof alcance=sucursal: operador sin privilegio → 403 (no eleva ni filtra en silencio).
    sucursal = entorno.c.get("/terminal/reportes/dia?alcance=sucursal&usuario_id=99", headers=b["headers"])
    assert sucursal.status_code == 403
    assert ajeno["serial"] not in sucursal.text
    dia = entorno.c.get("/terminal/reportes/dia?cajero_id=2", headers=b["headers"])
    assert dia.status_code == 200
    assert ajeno["serial"] not in dia.text
    consulta = entorno.c.post(
        "/terminal/tickets/consultar",
        json={"id": ajeno["id"], "serial": ajeno["serial"], "cajero_id": 99},
        headers=b["headers"],
    )
    assert consulta.status_code == 403
    assert "OTRA CAJERA" in consulta.json()["detail"]
    anulacion = entorno.c.post(
        "/terminal/tickets/anular",
        json={"id": ajeno["id"], "serial": ajeno["serial"], "motivo": "ajena"},
        headers=b["headers"],
    )
    assert anulacion.status_code == 403
    assert entorno.c.get("/terminal/sorteos", headers=ana).json()["mi_caja"] == "10.00"
    assert entorno.c.get("/terminal/sorteos", headers=b["headers"]).json()["mi_caja"] == "0.00"
    assert entorno.saldo(b["sucursal"]["id"]) == antes + 10


def test_dos_telefonos_muestran_la_misma_caja_sin_duplicarla(entorno):
    entorno.banca(saldo=0, usuario="jose", clave="prueba123")
    sorteo = entorno.sorteo_id("La Primera 12")

    def entrar(serie):
        return entorno.c.post("/terminal/login", json={
            "usuario": "jose", "clave": "prueba123", "dispositivo_id": serie,
        })

    uno = entrar("TEL-JOSE-1")
    dos = entrar("TEL-JOSE-2")
    assert uno.status_code == 200 and dos.status_code == 200
    assert uno.json()["terminal"]["id"] != dos.json()["terminal"]["id"]
    h1 = {"Authorization": f"Bearer {uno.json()['token']}"}
    h2 = {"Authorization": f"Bearer {dos.json()['token']}"}
    entorno.vender_ok(h1, [{"tipo": "QN", "sorteos": [sorteo], "numeros": "25", "monto": 10}])
    assert entorno.c.get("/terminal/sorteos", headers=h1).json()["mi_caja"] == "10.00"
    assert entorno.c.get("/terminal/sorteos", headers=h2).json()["mi_caja"] == "10.00"
    otra = entrar("TEL-JOSE-2")
    assert otra.json()["terminal"]["id"] == dos.json()["terminal"]["id"]
    assert entorno.c.get("/terminal/sorteos", headers={
        "Authorization": f"Bearer {otra.json()['token']}",
    }).json()["mi_caja"] == "10.00"


def test_el_consolidado_no_se_suma_a_la_caja_general(entorno):
    b = entorno.banca(saldo=0, usuario="jose", clave="prueba123")
    entorno.operador("ana", "prueba123", b["sucursal"]["id"])
    ana = entorno.login_terminal("ana", "prueba123")
    sorteo = entorno.sorteo_id("La Primera 12")
    entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [sorteo], "numeros": "25", "monto": 40}])
    entorno.vender_ok(ana, [{"tipo": "QN", "sorteos": [sorteo], "numeros": "11", "monto": 15}])
    fila = next(s for s in entorno.c.get("/sucursales", headers=entorno.admin).json()
                if s["id"] == b["sucursal"]["id"])
    assert float(fila["saldo_actual"]) == 55
    assert float(fila["consolidado_cajas"]["cajas_reales"]) == 55
    assert fila["consolidado_cajas"]["incluido_en_caja_general"] is False
    assert float(fila["saldo_actual"]) != 110
    cuadre = entorno.c.post("/terminal/caja/cuadre", json={}, headers=ana)
    assert cuadre.status_code == 201, cuadre.text
    assert float(cuadre.json()["ventas_total"]) == 15
    assert entorno.saldo(b["sucursal"]["id"]) == 40
    assert entorno.c.get("/terminal/sorteos", headers=b["headers"]).json()["mi_caja"] == "40.00"
    assert entorno.c.get("/terminal/sorteos", headers=ana).json()["mi_caja"] == "15.00"


def test_premios_por_pagar_no_se_heredan_entre_cajeros(entorno, monkeypatch):
    """PAGAR del terminal es del cajero autenticado; no suma premios de otro de la misma banca."""
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    b = entorno.banca(saldo=0, usuario="cajero_a", clave="prueba123")
    entorno.operador("cajero_b", "prueba123", b["sucursal"]["id"])
    hb = entorno.login_terminal("cajero_b", "prueba123")
    sorteo = entorno.sorteo_id("LOTEDOM")
    ticket = entorno.vender_ok(b["headers"], [
        {"tipo": "QN", "sorteos": [sorteo], "numeros": "25", "monto": 10},
    ])
    sim = entorno.c.post("/resultados", json={
        "sorteo_id": sorteo, "fecha": "2026-11-14",
        "premio1": 25, "premio2": 1, "premio3": 2, "simulado": True,
    }, headers=entorno._headers_gestion())
    assert sim.status_code == 201, sim.text

    propios = entorno.c.get("/terminal/sorteos", headers=b["headers"]).json()
    ajenos = entorno.c.get("/terminal/sorteos", headers=hb).json()
    assert float(propios["mi_caja"]) == 10.00
    assert float(ajenos["mi_caja"]) == 0.00
    assert float(propios["mi_venta"]) == 10.00
    assert float(ajenos["mi_venta"]) == 0.00
    assert float(propios["premios_por_pagar"]) > 0
    assert float(ajenos["premios_por_pagar"]) == 0.00
    assert ajenos.get("premios_pendientes_sucursal") in (None, "0.00")
    assert propios.get("premios_pendientes_mios") == propios["premios_por_pagar"]
    assert ticket["serial"]  # ticket propio intacto; permiso de pago no se altera aquí


def test_ventas_y_reportes_no_mezclan_cajeros_ni_sucursales(entorno, monkeypatch):
    """Misma banca y bancas distintas: cada cajero solo ve lo suyo; no se spoofea alcance."""
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    peg = entorno.banca(saldo=0, nombre="BANCA PEGUERO TEST", usuario="peg_a", clave="prueba123")
    entorno.operador("peg_b", "prueba123", peg["sucursal"]["id"])
    hb = entorno.login_terminal("peg_b", "prueba123")
    cast = entorno.banca(saldo=0, nombre="BANCA CASTILLO TEST", usuario="cast_a", clave="prueba123")
    sorteo = entorno.sorteo_id("LOTEDOM")

    t_peg = entorno.vender_ok(peg["headers"], [
        {"tipo": "QN", "sorteos": [sorteo], "numeros": "11", "monto": 20},
    ])
    t_cast = entorno.vender_ok(cast["headers"], [
        {"tipo": "QN", "sorteos": [sorteo], "numeros": "22", "monto": 30},
    ])

    ind_a = entorno.c.get("/terminal/sorteos", headers=peg["headers"]).json()
    ind_b = entorno.c.get("/terminal/sorteos", headers=hb).json()
    ind_c = entorno.c.get("/terminal/sorteos", headers=cast["headers"]).json()
    assert float(ind_a["mi_venta"]) == 20.00 and float(ind_a["mi_caja"]) == 20.00
    assert float(ind_b["mi_venta"]) == 0.00 and float(ind_b["mi_caja"]) == 0.00
    assert float(ind_c["mi_venta"]) == 30.00 and float(ind_c["mi_caja"]) == 30.00

    # Spoof alcance=sucursal: operador sin privilegio → 403 (no eleva alcance).
    dia_b = entorno.c.get(
        "/terminal/reportes/dia?alcance=sucursal",
        headers=hb,
    )
    assert dia_b.status_code == 403

    res_a = entorno.c.get(
        "/terminal/reportes/resumen?desde=2026-11-14&hasta=2026-11-14&vista=final",
        headers=peg["headers"],
    ).json()
    res_b = entorno.c.get(
        "/terminal/reportes/resumen?desde=2026-11-14&hasta=2026-11-14&vista=final",
        headers=hb,
    ).json()
    # Resumen terminal usa tickets reales; en MODO_DESARROLLO las ventas de prueba
    # no entran a esa vista, pero sí deben permanecer aisladas en indicadores.
    assert t_peg["serial"] not in str(res_b)
    assert t_cast["serial"] not in str(res_a)

    pend_b = entorno.c.get(
        "/terminal/reportes/pendientes?desde=2026-11-14&hasta=2026-11-14",
        headers=hb,
    )
    assert pend_b.status_code == 200
    assert float(pend_b.json().get("monto_pendiente", 0)) == 0.00


def test_premio_pagado_cuenta_al_pagador_no_al_vendedor_ajeno(entorno, monkeypatch):
    """Terminal bloquea pago ajeno; la cajera vendedora sí cobra y baja su caja."""
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    b = entorno.banca(saldo=0, usuario="vend_a", clave="prueba123")
    entorno.operador("pag_b", "prueba123", b["sucursal"]["id"])
    usuarios = entorno.c.get("/usuarios", headers=entorno.admin).json()
    vend_a = next(u for u in usuarios if u["usuario"] == "vend_a")
    pag_b = next(u for u in usuarios if u["usuario"] == "pag_b")
    fondo_a = entorno.c.post("/fondos", json={
        "sucursal_id": b["sucursal"]["id"], "usuario_id": vend_a["id"], "monto": 5000,
        "tipo": "aporte_prueba", "operacion_id": "fondo-vend-a",
    }, headers=entorno.admin)
    assert fondo_a.status_code == 201, fondo_a.text
    fondo_b = entorno.c.post("/fondos", json={
        "sucursal_id": b["sucursal"]["id"], "usuario_id": pag_b["id"], "monto": 5000,
        "tipo": "aporte_prueba", "operacion_id": "fondo-pag-b",
    }, headers=entorno.admin)
    assert fondo_b.status_code == 201, fondo_b.text
    ha = entorno.login_terminal("vend_a", "prueba123")
    hb = entorno.login_terminal("pag_b", "prueba123")

    sorteo = entorno.sorteo_id("LOTEDOM")
    ticket = entorno.vender_ok(ha, [
        {"tipo": "QN", "sorteos": [sorteo], "numeros": "25", "monto": 10},
    ])
    sim = entorno.c.post("/resultados", json={
        "sorteo_id": sorteo, "fecha": "2026-11-14",
        "premio1": 25, "premio2": 1, "premio3": 2, "simulado": True,
    }, headers=entorno._headers_gestion())
    assert sim.status_code == 201, sim.text
    premio = float(entorno.c.get("/terminal/sorteos", headers=ha).json()["premios_por_pagar"])
    assert premio > 0

    # B no puede pagar el ticket de A (aunque sea la misma sucursal).
    ajeno = entorno.c.post("/terminal/tickets/pagar", json={
        "id": ticket["id"], "serial": ticket["serial"], "operacion_id": "pago-por-b",
    }, headers=hb)
    assert ajeno.status_code == 403
    assert "OTRA CAJERA" in ajeno.json()["detail"]

    pago = entorno.c.post("/terminal/tickets/pagar", json={
        "id": ticket["id"], "serial": ticket["serial"], "operacion_id": "pago-por-a",
    }, headers=ha)
    assert pago.status_code == 200, pago.text

    ind_a = entorno.c.get("/terminal/sorteos", headers=ha).json()
    ind_b = entorno.c.get("/terminal/sorteos", headers=hb).json()
    assert float(ind_a["premios_por_pagar"]) == 0.00
    assert float(ind_b["premios_por_pagar"]) == 0.00
    assert float(ind_a["mi_venta"]) == 10.00
    assert float(ind_a["mi_caja"]) == 5000.00 + 10.00 - premio
    assert float(ind_b["mi_caja"]) == 5000.00

    q = "desde=2026-11-14&hasta=2026-11-14"
    dia_a = entorno.c.get(f"/terminal/reportes/dia?{q}", headers=ha).json()
    dia_b = entorno.c.get(f"/terminal/reportes/dia?{q}", headers=hb).json()
    assert float(dia_a["prueba"]["premios_pagados"]) == premio
    assert float(dia_a["prueba"]["ventas"]) == 10.00
    assert float(dia_b["prueba"]["premios_pagados"]) == 0.00
    assert float(dia_b["prueba"]["ventas"]) == 0.00

