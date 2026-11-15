"""Reimpresión, anulación con motivo, límites para todos los sorteos
y ventas de prueba fuera de la caja real."""


def test_reimprimir_no_cambia_venta_ni_caja(entorno):
    b = entorno.banca(saldo=100)
    s = entorno.sorteo_id("La Primera 12")
    t = entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [s], "numeros": "19", "monto": 10}])
    antes = entorno.saldo(b["sucursal"]["id"])
    r = entorno.c.post("/terminal/tickets/reimprimir",
                       json={"id": t["id"], "serial": t["serial"]}, headers=b["headers"])
    assert r.status_code == 200, r.text
    copia = r.json()
    assert copia["leyenda"] == "COPIA — REIMPRESIÓN"
    assert copia["reimpresion"] is True
    assert copia["reimpresiones"] == 1
    assert copia["estado"] == "vendido"
    assert copia["qr"] == f"LOT:{t['id']}:{t['serial']}"
    assert "monto" not in copia["qr"]
    assert entorno.saldo(b["sucursal"]["id"]) == antes
    otra = entorno.c.post("/terminal/tickets/reimprimir",
                          json={"id": t["id"], "serial": t["serial"]}, headers=b["headers"]).json()
    assert otra["reimpresiones"] == 2
    assert otra["estado"] == "vendido"
    filas = entorno.c.get("/auditoria?entidad=ticket&accion=reimpresion", headers=entorno.admin).json()
    assert len(filas) == 2
    assert filas[0]["detalle"]["cantidad"] == 2


def test_anular_exige_estado_valido_guarda_motivo_y_no_borra(entorno):
    b = entorno.banca(saldo=100)
    s = entorno.sorteo_id("La Primera 12")
    t = entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [s], "numeros": "08", "monto": 10}])
    r = entorno.c.post("/terminal/tickets/anular", json={
        "id": t["id"], "serial": t["serial"], "motivo": "Cliente se equivocó",
    }, headers=b["headers"])
    assert r.status_code == 200, r.text
    assert r.json()["estado"] == "anulado"
    assert entorno.saldo(b["sucursal"]["id"]) == 100.00
    repetida = entorno.c.post("/terminal/tickets/anular", json={
        "id": t["id"], "serial": t["serial"], "motivo": "otra vez",
    }, headers=b["headers"])
    assert repetida.status_code == 409
    consulta = entorno.consultar(t)
    assert consulta["id"] == t["id"] and consulta["estado"] == "anulado"
    filas = entorno.c.get("/auditoria?entidad=ticket&accion=anulacion", headers=entorno.admin).json()
    assert filas[0]["detalle"]["motivo"] == "Cliente se equivocó"


def test_aplicar_limite_para_todas_respeta_los_individuales(entorno):
    catalogo = entorno.c.get("/sorteos", headers=entorno.admin).json()
    primera = next(s for s in catalogo if s["nombre"] == "La Primera 12")
    vista = entorno.c.post("/limites/aplicar-todas", json={
        "tipo": "PL", "numeros": "26-58", "monto_max_acumulado": 1000, "aplicar": False,
    }, headers=entorno.admin)
    assert vista.status_code == 200, vista.text
    resumen = vista.json()
    assert resumen["aplicado"] is False
    assert resumen["sorteos"] == len(catalogo) >= 19
    assert resumen["creados"] == len(catalogo)
    assert entorno.c.get("/limites", headers=entorno.admin).json() == []
    hecho = entorno.c.post("/limites/aplicar-todas", json={
        "tipo": "PL", "numeros": "26-58", "monto_max_acumulado": 1000, "aplicar": True,
    }, headers=entorno.admin)
    assert hecho.status_code == 200, hecho.text
    assert hecho.json()["creados"] == len(catalogo)
    uno = entorno.c.post("/limites", json={
        "sorteo_id": primera["id"], "tipo": "PL", "numeros": "58-26", "monto_max_acumulado": 25,
    }, headers=entorno.admin)
    assert uno.status_code == 201, uno.text
    sin_reemplazo = entorno.c.post("/limites/aplicar-todas", json={
        "tipo": "PL", "numeros": "26-58", "monto_max_acumulado": 1000,
        "aplicar": True, "reemplazar": False,
    }, headers=entorno.admin).json()
    assert sin_reemplazo["omitidos"] == len(catalogo)
    assert sin_reemplazo["actualizados"] == 0
    guardado = next(l for l in entorno.c.get("/limites", headers=entorno.admin).json()
                    if l["sorteo_id"] == primera["id"])
    assert float(guardado["monto_max_acumulado"]) == 25.00
    con_reemplazo = entorno.c.post("/limites/aplicar-todas", json={
        "tipo": "PL", "numeros": "26-58", "monto_max_acumulado": 1000,
        "aplicar": True, "reemplazar": True,
    }, headers=entorno.admin).json()
    assert con_reemplazo["actualizados"] == len(catalogo)
    guardado = next(l for l in entorno.c.get("/limites", headers=entorno.admin).json()
                    if l["sorteo_id"] == primera["id"])
    assert float(guardado["monto_max_acumulado"]) == 1000.00
    filas = entorno.c.get("/auditoria?entidad=limite&accion=aplicar_todas", headers=entorno.admin).json()
    assert len(filas) == 3


def test_venta_de_prueba_no_consume_limite_ni_caja_de_otra_sucursal(entorno, monkeypatch):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    castillo = entorno.banca(saldo=0, codigo="1301", nombre="BANCA CASTILLO", usuario="vend1")
    s = entorno.sorteo_id("La Primera 12")
    entorno.c.post("/limites", json={
        "sorteo_id": s, "tipo": "QN", "numeros": "26", "monto_max_acumulado": 100,
    }, headers=entorno.admin)
    prueba = entorno.vender_ok(castillo["headers"], [{"tipo": "QN", "sorteos": [s], "numeros": "26", "monto": 80}])
    assert prueba["es_prueba"] is True
    assert entorno.saldo(castillo["sucursal"]["id"]) == 0.00
    monkeypatch.setenv("MODO_DESARROLLO", "false")
    peguero = entorno.banca(saldo=0, codigo="2200", nombre="BANCA PEGUERO", usuario="vend2")
    real = entorno.vender_ok(peguero["headers"], [{"tipo": "QN", "sorteos": [s], "numeros": "26", "monto": 60}])
    assert real["es_prueba"] is False
    assert entorno.saldo(peguero["sucursal"]["id"]) == 60.00
    assert entorno.saldo(castillo["sucursal"]["id"]) == 0.00
    exceso = entorno.vender(peguero["headers"], [{"tipo": "QN", "sorteos": [s], "numeros": "26", "monto": 50}])
    assert exceso.status_code == 409
