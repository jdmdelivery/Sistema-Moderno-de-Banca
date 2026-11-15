"""Administración: autenticación, CRUD, terminales y tokens, tabla de pagos,
saldos y auditoría (alcances 1, 2, 3 y 9)."""


def test_login_clave_incorrecta(entorno):
    r = entorno.c.post("/auth/login", json={"usuario": "admin", "clave": "mala"})
    assert r.status_code == 401


def test_sin_token_no_hay_panel(entorno):
    assert entorno.c.get("/sucursales").status_code == 401
    assert entorno.c.get("/reportes/resumen?desde=2026-11-14&hasta=2026-11-14").status_code == 401


def test_operador_no_entra_al_panel(entorno):
    entorno.banca()  # crea el operador vend1 con su contraseña de terminal
    r = entorno.c.post("/auth/login", json={"usuario": "vend1", "clave": "1234"})
    assert r.status_code == 401


def test_sucursal_duplicada_rechazada(entorno):
    entorno.sucursal(codigo="1301")
    r = entorno.c.post("/sucursales", json={"codigo": "1301", "nombre": "OTRA"}, headers=entorno.admin)
    assert r.status_code == 409


def test_terminal_revocada_no_opera_y_reactivada_si(entorno):
    b = entorno.banca(saldo=1000)
    # La terminal se creó sola cuando el operador entró: la buscamos en el panel
    ter = [t for t in entorno.c.get("/terminales", headers=entorno.admin).json()
           if t["sucursal_id"] == b["sucursal"]["id"]][0]
    r = entorno.c.post(f"/terminales/{ter['id']}/revocar", headers=entorno.admin)
    assert r.status_code == 200 and r.json()["activa"] is False
    # Con la terminal revocada, la sesión abierta ya no puede vender
    s = entorno.sorteo_id("La Primera 12")
    r = entorno.vender(b["headers"], [{"tipo": "QN", "sorteos": [s], "numeros": "01", "monto": 5}])
    assert r.status_code == 401
    # Ni siquiera puede volver a entrar
    r = entorno.c.post("/terminal/login", json={"usuario": "vend1", "clave": "1234"})
    assert r.status_code == 403
    # Al reactivarla, entra con su usuario y contraseña y vende de nuevo
    r = entorno.c.post(f"/terminales/{ter['id']}/reactivar", headers=entorno.admin)
    assert r.status_code == 200 and r.json()["activa"] is True
    headers = entorno.login_terminal()
    t = entorno.vender_ok(headers, [{"tipo": "QN", "sorteos": [s], "numeros": "01", "monto": 5}])
    assert t["estado"] == "vendido"


def test_operador_entra_solo_en_su_propia_sucursal(entorno):
    # Sin token de terminal ya no hay «terminal ajena»: cada operador entra
    # directo a SU sucursal y sus ventas caen en su propia caja.
    b1 = entorno.banca(saldo=100, codigo="1301", usuario="vend1")
    b2 = entorno.banca(saldo=100, codigo="2200", nombre="BANCA PEGUERO", usuario="vend2")
    s = entorno.sorteo_id("La Primera 12")
    t = entorno.vender_ok(b2["headers"], [{"tipo": "QN", "sorteos": [s], "numeros": "01", "monto": 5}])
    assert t["banca"] == "BANCA PEGUERO"
    assert entorno.saldo(b1["sucursal"]["id"]) == 100.00
    assert entorno.saldo(b2["sucursal"]["id"]) == 105.00


def test_clave_incorrecta(entorno):
    entorno.banca(saldo=100)
    r = entorno.c.post("/terminal/login", json={"usuario": "vend1", "clave": "no-es-esta"})
    assert r.status_code == 401


def test_tabla_cambio_cierra_la_vigencia_anterior(entorno):
    r = entorno.c.post("/tabla-pagos", json={
        "tipo": "QN", "clave": "1ro", "factor": 100, "vigente_desde": "2026-12-01",
    }, headers=entorno.admin)
    assert r.status_code == 201, r.text
    filas = entorno.c.get("/tabla-pagos", headers=entorno.admin).json()
    qn1 = [f for f in filas if f["tipo"] == "QN" and f["clave"] == "1ro"]
    vieja = [f for f in qn1 if f["factor"] == "60.00"][0]
    nueva = [f for f in qn1 if f["factor"] == "100.00"][0]
    assert vieja["vigente_hasta"] == "2026-12-01 00:00:00"
    assert nueva["vigente_hasta"] is None
    # Clave que no pertenece al tipo → 400; tipo inexistente → 404
    r = entorno.c.post("/tabla-pagos", json={
        "tipo": "QN", "clave": "sp", "factor": 10, "vigente_desde": "2026-12-01",
    }, headers=entorno.admin)
    assert r.status_code == 400
    r = entorno.c.post("/tabla-pagos", json={
        "tipo": "ZZ", "clave": "1ro", "factor": 10, "vigente_desde": "2026-12-01",
    }, headers=entorno.admin)
    assert r.status_code == 404


def test_recargas_y_cadena_de_saldos(entorno):
    s = entorno.sucursal()
    entorno.recargar(s["id"], 500)
    entorno.recargar(s["id"], 250)
    assert entorno.saldo(s["id"]) == 750.00
    r = entorno.c.post(f"/sucursales/{s['id']}/recargar", json={"monto": -5}, headers=entorno.admin)
    assert r.status_code == 400
    movs = entorno.c.get(f"/sucursales/{s['id']}/movimientos", headers=entorno.admin).json()
    assert [float(m["saldo_resultante"]) for m in movs] == [750.00, 500.00]  # más reciente primero


def test_sorteo_crud_y_cierre_reflejado_en_terminal(entorno):
    b = entorno.banca(saldo=100)
    r = entorno.c.post("/sorteos", json={
        "nombre": "Prueba Mediodía", "hora_sorteo": "12:00", "hora_cierre": "11:55",
        "dias_activos": [1, 2, 3, 4, 5, 6, 7], "orden": 5,
    }, headers=entorno.admin)
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    lista = entorno.c.get("/terminal/sorteos", headers=b["headers"]).json()["sorteos"]
    fila = [x for x in lista if x["id"] == sid][0]
    assert fila["abierto"] is True  # a las 10:00 aún no cierra (11:55)
    r = entorno.c.put(f"/sorteos/{sid}", json={
        "nombre": "Prueba Mediodía", "hora_sorteo": "12:00", "hora_cierre": "09:00",
        "dias_activos": [1, 2, 3, 4, 5, 6, 7], "orden": 5, "activo": True,
    }, headers=entorno.admin)
    assert r.status_code == 200
    lista = entorno.c.get("/terminal/sorteos", headers=b["headers"]).json()["sorteos"]
    fila = [x for x in lista if x["id"] == sid][0]
    assert fila["abierto"] is False and "cerró" in fila["motivo_cierre"]


def test_limite_upsert(entorno):
    s = entorno.sorteo_id("La Primera 12")
    entorno.c.post("/limites", json={"sorteo_id": s, "tipo": "QN", "numeros": "26",
                                     "monto_max_acumulado": 100}, headers=entorno.admin)
    entorno.c.post("/limites", json={"sorteo_id": s, "tipo": "QN", "numeros": "26",
                                     "monto_max_acumulado": 300}, headers=entorno.admin)
    filas = entorno.c.get("/limites", headers=entorno.admin).json()
    assert len(filas) == 1 and float(filas[0]["monto_max_acumulado"]) == 300.00


def test_usuario_operador_necesita_contrasena(entorno):
    s = entorno.sucursal()
    r = entorno.c.post("/usuarios", json={"nombre": "X", "usuario": "x1", "rol": "operador",
                                          "sucursal_id": s["id"]}, headers=entorno.admin)
    assert r.status_code == 400
    r = entorno.c.post("/usuarios", json={"nombre": "X", "usuario": "x1", "rol": "operador",
                                          "sucursal_id": s["id"], "clave": "su-clave"}, headers=entorno.admin)
    assert r.status_code == 201


def test_auditoria_registra_venta_pago_y_es_solo_admin(entorno):
    b = entorno.banca()
    s = entorno.sorteo_id("La Primera 12")
    t = entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [s], "numeros": "19", "monto": 10}])
    entorno.liquidar(s, 19, 3, 45)
    entorno.c.post("/terminal/tickets/pagar",
                   json={"id": t["id"], "serial": t["serial"]}, headers=b["headers"])
    filas = entorno.c.get("/auditoria?entidad=ticket", headers=entorno.admin).json()
    acciones = {f["accion"] for f in filas}
    assert {"venta", "pago"} <= acciones
    # Un supervisor NO puede ver la auditoría (solo admin)
    entorno.c.post("/usuarios", json={"nombre": "Sup", "usuario": "sup1", "rol": "supervisor",
                                      "clave": "sup1234"}, headers=entorno.admin)
    r = entorno.c.post("/auth/login", json={"usuario": "sup1", "clave": "sup1234"})
    sup = {"Authorization": f"Bearer {r.json()['token']}"}
    assert entorno.c.get("/auditoria", headers=sup).status_code == 403
