"""Tickets ganadores de prueba: resultado simulado, premio vigente y un solo pago.

No usa RDLotto ni cambia la caja de la sucursal.
"""
from datetime import datetime


def _simular(entorno, sorteo_id, p1, p2, p3, fecha="2026-11-14"):
    r = entorno.c.post(
        "/resultados",
        json={
            "sorteo_id": sorteo_id, "fecha": fecha,
            "premio1": p1, "premio2": p2, "premio3": p3, "simulado": True,
        },
        headers=entorno.admin,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _consultar(entorno, headers, ticket):
    r = entorno.c.post(
        "/terminal/tickets/consultar",
        json={"id": ticket["id"], "serial": ticket["serial"]},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return r.json()


def _pagar(entorno, headers, ticket, operacion):
    return entorno.c.post(
        "/terminal/tickets/pagar",
        json={"id": ticket["id"], "serial": ticket["serial"], "operacion_id": operacion},
        headers=headers,
    )


def test_simulado_fuera_de_desarrollo_se_rechaza(entorno):
    b = entorno.banca(saldo=5764, nombre="BANCA CASTILLO (PRUEBA)", usuario="jose")
    sorteo = entorno.sorteo_id("LOTEDOM")
    r = entorno.c.post(
        "/resultados",
        json={"sorteo_id": sorteo, "fecha": "2026-11-14", "premio1": 25, "premio2": 54,
              "premio3": 78, "simulado": True},
        headers=entorno.admin,
    )
    assert r.status_code == 403
    assert entorno.saldo(b["sucursal"]["id"]) == 5764


def test_simulado_no_reemplaza_rdlotto(entorno, monkeypatch):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    b = entorno.banca(saldo=5764, nombre="BANCA CASTILLO (PRUEBA)", usuario="jose")
    sorteo = entorno.sorteo_id("LOTEDOM")
    guardado = entorno.guardar_resultado(sorteo, 1, 2, 3)
    from apps.api.db import nueva_sesion
    from apps.api.models import Resultado

    db = nueva_sesion()
    fila = db.get(Resultado, guardado["id"])
    fila.fuente = "rdlotto"
    fila.externo = "quiniela-loteka"
    db.commit()
    db.close()
    r = entorno.c.post(
        "/resultados",
        json={"sorteo_id": sorteo, "fecha": "2026-11-14", "premio1": 25, "premio2": 54,
              "premio3": 78, "simulado": True},
        headers=entorno.admin,
    )
    assert r.status_code == 409
    assert "RDLotto" in r.json()["detail"]
    assert entorno.saldo(b["sucursal"]["id"]) == 5764


def test_qn_pl_sp_pago_unico_y_correccion(entorno, monkeypatch, fijar_hora):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    b = entorno.banca(saldo=5764, nombre="BANCA CASTILLO (PRUEBA)", usuario="jose", clave="prueba123")
    headers = b["headers"]
    lotedom = entorno.sorteo_id("LOTEDOM")
    nacional = entorno.sorteo_id("Nacional Tarde")
    ny = entorno.sorteo_id("NY Tarde")
    florida = entorno.sorteo_id("Florida Día")
    sucursal_id = b["sucursal"]["id"]

    fondo = entorno.vender_ok(headers, [{"tipo": "QN", "sorteos": [lotedom], "numeros": "01", "monto": 600}])
    primero = entorno.vender_ok(headers, [{"tipo": "QN", "sorteos": [lotedom], "numeros": "25", "monto": 10}])
    segundo = entorno.vender_ok(headers, [{"tipo": "QN", "sorteos": [lotedom], "numeros": "54", "monto": 10}])
    tercero = entorno.vender_ok(headers, [{"tipo": "QN", "sorteos": [lotedom], "numeros": "78", "monto": 10}])
    pale = entorno.vender_ok(headers, [{"tipo": "PL", "sorteos": [lotedom], "numeros": "25-54", "monto": 5}])
    superpale = entorno.vender_ok(headers, [
        {"tipo": "SP", "sorteos": [ny, nacional], "numeros": "12-38", "monto": 5},
    ])
    perdedor = entorno.vender_ok(headers, [{"tipo": "QN", "sorteos": [lotedom], "numeros": "99", "monto": 10}])
    anulado = entorno.vender_ok(headers, [{"tipo": "QN", "sorteos": [lotedom], "numeros": "25", "monto": 10}])
    pendiente = entorno.vender_ok(headers, [{"tipo": "QN", "sorteos": [florida], "numeros": "25", "monto": 10}])
    baja = entorno.c.post(
        "/terminal/tickets/anular",
        json={"id": anulado["id"], "serial": anulado["serial"], "motivo": "prueba"},
        headers=headers,
    )
    assert baja.status_code == 200, baja.text
    assert primero["es_prueba"] is True
    assert primero["qr"] == f"LOT:{primero['id']}:{primero['serial']}"
    assert entorno.saldo(sucursal_id) == 5764

    resultado = _simular(entorno, lotedom, 25, 54, 78)
    assert resultado["leyenda"] == "RESULTADO SIMULADO — NO OFICIAL"
    assert resultado["estado"] == "propuesto"
    assert resultado["fuente"] == "simulado"
    assert resultado["no_oficial"] is True
    _simular(entorno, ny, 12, 1, 2)
    otro = _simular(entorno, nacional, 38, 11, 22)
    assert otro["leyenda"] == "RESULTADO SIMULADO — NO OFICIAL"

    consulta = _consultar(entorno, headers, primero)
    assert consulta["estado"] == "ganador"
    assert consulta["veredicto"] == "TICKET GANADOR — PENDIENTE DE PAGO — NO OFICIAL"
    assert consulta["puede_pagar"] is True
    assert float(consulta["premio_total"]) == 600
    assert consulta["jugadas"][0]["loterias"] == ["Lotedom 12:00 PM"]
    assert consulta["jugadas"][0]["numeros"] == "25"
    assert float(consulta["jugadas"][0]["monto"]) == 10
    assert consulta["jugadas"][0]["detalle_eval"] == "1ro"
    assert float(_consultar(entorno, headers, segundo)["premio_total"]) == 100
    assert _consultar(entorno, headers, segundo)["jugadas"][0]["detalle_eval"] == "2do"
    assert float(_consultar(entorno, headers, tercero)["premio_total"]) == 50
    assert _consultar(entorno, headers, tercero)["jugadas"][0]["detalle_eval"] == "3ro"
    assert float(_consultar(entorno, headers, pale)["premio_total"]) == 6000
    assert _consultar(entorno, headers, pale)["jugadas"][0]["detalle_eval"] == "1-2"
    assert float(_consultar(entorno, headers, superpale)["premio_total"]) == 12500
    assert _consultar(entorno, headers, superpale)["jugadas"][0]["detalle_eval"] == "sp"
    assert _consultar(entorno, headers, perdedor)["estado"] == "no_ganador"
    assert _consultar(entorno, headers, anulado)["estado"] == "anulado"
    assert _consultar(entorno, headers, pendiente)["estado"] == "vendido"
    assert _consultar(entorno, headers, fondo)["estado"] == "no_ganador"
    assert entorno.saldo(sucursal_id) == 5764

    corregido = _simular(entorno, lotedom, 11, 54, 78)
    assert corregido["premio1"] == "11"
    assert _consultar(entorno, headers, primero)["estado"] == "no_ganador"
    assert float(_consultar(entorno, headers, segundo)["premio_total"]) == 100
    assert _consultar(entorno, headers, pale)["estado"] == "no_ganador"
    restaurado = _simular(entorno, lotedom, 25, 54, 78)
    assert restaurado["premio1"] == "25"
    assert float(_consultar(entorno, headers, primero)["premio_total"]) == 600
    assert _consultar(entorno, headers, primero)["estado"] == "ganador"

    caja_antes = float(entorno.c.get("/terminal/sorteos", headers=headers).json()["mi_caja"])
    pago = _pagar(entorno, headers, primero, "pago-prueba-qn25")
    assert pago.status_code == 200, pago.text
    pagado = pago.json()
    assert pagado["estado"] == "pagado"
    assert pagado["veredicto"] == "TICKET YA PAGADO — NO OFICIAL"
    assert pagado["puede_pagar"] is False
    assert float(pagado["mi_caja"]) == caja_antes - 600
    assert "saldo_restante" not in pagado
    assert entorno.saldo(sucursal_id) == 5764

    repetido = _pagar(entorno, headers, primero, "pago-prueba-qn25-otra")
    assert repetido.status_code == 409
    assert "dos veces" in repetido.json()["detail"]
    assert float(entorno.c.get("/terminal/sorteos", headers=headers).json()["mi_caja"]) == caja_antes - 600

    entorno.operador("ana", "prueba123", sucursal_id)
    ana = entorno.login_terminal("ana", "prueba123")
    entorno.vender_ok(ana, [{"tipo": "QN", "sorteos": [florida], "numeros": "01", "monto": 600}])
    ajena = _pagar(entorno, ana, primero, "pago-ana")
    assert ajena.status_code == 409
    assert entorno.saldo(sucursal_id) == 5764

    bloqueo = entorno.c.post(
        "/resultados",
        json={"sorteo_id": lotedom, "fecha": "2026-11-14", "premio1": 19, "premio2": 54,
              "premio3": 78, "simulado": True},
        headers=entorno.admin,
    )
    assert bloqueo.status_code == 409
    assert float(_consultar(entorno, headers, primero)["premio_total"]) == 600
    assert _consultar(entorno, headers, primero)["estado"] == "pagado"
    assert entorno.saldo(sucursal_id) == 5764
    confirmar = entorno.c.post(f"/resultados/{resultado['id']}/confirmar", headers=entorno.admin)
    assert confirmar.status_code == 409

    ganadores = entorno.c.get("/ganadores?fecha=2026-11-14", headers=entorno.admin).json()
    assert ganadores["total_tickets"] == 0
    assert float(ganadores["total_premios"]) == 0
    ids_prueba = {fila["id"] for fila in ganadores["prueba"]}
    assert primero["id"] in ids_prueba
    assert all(fila["leyenda"] == "PRUEBA — NO OFICIAL" for fila in ganadores["prueba"])

    fijar_hora(datetime(2026, 11, 15, 10, 0, 0))
    admin = entorno.c.post("/auth/login", json={"usuario": "admin", "clave": "admin123"})
    assert admin.status_code == 200, admin.text
    entorno.admin = {"Authorization": f"Bearer {admin.json()['token']}"}
    headers = entorno.login_terminal("jose", "prueba123")
    otro_dia = entorno.vender_ok(headers, [{"tipo": "QN", "sorteos": [lotedom], "numeros": "25", "monto": 10}])
    _simular(entorno, lotedom, 25, 54, 78, fecha="2026-11-15")
    assert _consultar(entorno, headers, otro_dia)["estado"] == "ganador"
    assert _consultar(entorno, headers, pendiente)["estado"] == "vendido"
    assert _consultar(entorno, headers, perdedor)["estado"] == "no_ganador"
    assert entorno.saldo(sucursal_id) == 5764


def test_premio_mayor_que_mi_caja_no_cobra_ni_toca_la_general(entorno, monkeypatch):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    b = entorno.banca(saldo=5764, nombre="BANCA CASTILLO (PRUEBA)", usuario="jose", clave="prueba123")
    headers = b["headers"]
    lotedom = entorno.sorteo_id("LOTEDOM")
    ticket = entorno.vender_ok(headers, [{"tipo": "QN", "sorteos": [lotedom], "numeros": "25", "monto": 10}])
    _simular(entorno, lotedom, 25, 54, 78)
    consulta = _consultar(entorno, headers, ticket)
    assert consulta["estado"] == "ganador"
    assert consulta["puede_pagar"] is True
    assert consulta["veredicto"] == "TICKET GANADOR — PENDIENTE DE PAGO — NO OFICIAL"
    assert float(consulta["premio_total"]) == 600
    assert "saldo" not in consulta and "saldo_restante" not in consulta
    pago = _pagar(entorno, headers, ticket, "pago-insuficiente")
    assert pago.status_code == 409
    assert "No se pagó" in pago.json()["detail"]
    assert entorno.saldo(b["sucursal"]["id"]) == 5764
    assert float(entorno.c.get("/terminal/sorteos", headers=headers).json()["mi_caja"]) == 10
    otra = _pagar(entorno, headers, ticket, "pago-insuficiente-2")
    assert otra.status_code == 409
    assert _consultar(entorno, headers, ticket)["estado"] == "ganador"
    assert entorno.saldo(b["sucursal"]["id"]) == 5764
