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
    sucursal = entorno.c.get("/terminal/reportes/dia?alcance=sucursal&usuario_id=99", headers=b["headers"])
    assert sucursal.status_code == 403
    dia = entorno.c.get("/terminal/reportes/dia?cajero_id=2", headers=b["headers"])
    assert dia.status_code == 200
    assert ajeno["serial"] not in dia.text
    consulta = entorno.c.post(
        "/terminal/tickets/consultar",
        json={"id": ajeno["id"], "serial": ajeno["serial"], "cajero_id": 99},
        headers=b["headers"],
    )
    assert consulta.status_code == 200
    assert "mi_caja" not in consulta.json()
    assert "saldo" not in consulta.json()
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
