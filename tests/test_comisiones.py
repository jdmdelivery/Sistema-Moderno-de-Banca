"""Comisión manual, quincena y comprobante de premio. No mueve las cajas."""
from datetime import date

from apps.api.db import nueva_sesion
from apps.api.models import ComisionCajera
from apps.api.servicios import periodo_quincena


def _id(entorno, usuario):
    for fila in entorno.c.get("/usuarios", headers=entorno.admin).json():
        if fila["usuario"] == usuario:
            return fila["id"]
    raise AssertionError(usuario)


def _poner(entorno, usuario_id, porcentaje):
    r = entorno.c.post("/comisiones", json={"usuario_id": usuario_id, "porcentaje": porcentaje},
                       headers=entorno.admin)
    assert r.status_code == 201, r.text
    return r.json()


def _dia(entorno, headers, desde="2026-11-14", hasta="2026-11-14"):
    r = entorno.c.get(f"/terminal/reportes/dia?desde={desde}&hasta={hasta}", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def test_quincenas_de_28_29_30_y_31_dias():
    assert periodo_quincena(2026, 11, 1) == (date(2026, 11, 1), date(2026, 11, 15))
    assert periodo_quincena(2026, 2, 2) == (date(2026, 2, 16), date(2026, 2, 28))
    assert periodo_quincena(2024, 2, 2) == (date(2024, 2, 16), date(2024, 2, 29))
    assert periodo_quincena(2026, 4, 2) == (date(2026, 4, 16), date(2026, 4, 30))
    assert periodo_quincena(2026, 1, 2) == (date(2026, 1, 16), date(2026, 1, 31))


def test_porcentajes_distintos_cambio_anulados_y_entrega(entorno, fijar_hora):
    b = entorno.banca(saldo=5764, nombre="BANCA CASTILLO", usuario="jose", clave="prueba123")
    otra = entorno.banca(saldo=500, codigo="2200", nombre="BANCA PEGUERO", usuario="ana", clave="prueba123")
    jose = _id(entorno, "jose")
    ana = _id(entorno, "ana")
    sorteo = entorno.sorteo_id("La Primera 12")
    assert _poner(entorno, jose, 10)["porcentaje_anterior"] is None
    _poner(entorno, ana, 12)
    invalido = entorno.c.post("/comisiones", json={"usuario_id": jose, "porcentaje": 101}, headers=entorno.admin)
    assert invalido.status_code == 400
    assert entorno.c.post("/comisiones", json={"usuario_id": jose, "porcentaje": -1},
                          headers=entorno.admin).status_code == 400
    assert entorno.c.post("/comisiones", json={"usuario_id": jose, "porcentaje": 10},
                          headers=b["headers"]).status_code == 401
    assert entorno.c.get("/comisiones", headers=b["headers"]).status_code == 401

    entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [sorteo], "numeros": "11", "monto": 100}])
    anulado = entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [sorteo], "numeros": "12", "monto": 40}])
    entorno.c.post("/terminal/tickets/anular",
                   json={"id": anulado["id"], "serial": anulado["serial"], "motivo": "error"},
                   headers=b["headers"])
    fijar_hora(__import__("datetime").datetime(2026, 11, 14, 15, 0, 0))
    cambio = _poner(entorno, jose, 15)
    assert cambio["porcentaje_anterior"] == "10"
    assert cambio["creado_en"].startswith("2026-11-14 15:00")
    tarde = entorno.sorteo_id("LOTEDOM")
    entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [tarde], "numeros": "13", "monto": 50}])
    entorno.vender_ok(otra["headers"], [{"tipo": "QN", "sorteos": [tarde], "numeros": "21", "monto": 80}])

    resumen = _dia(entorno, b["headers"])
    assert resumen["real"]["ventas"] == "150.00"
    assert resumen["comision"]["real"]["comision"] == "17.50"
    assert resumen["comision"]["real"]["tickets_anulados"] == 1
    assert "10% SOBRE RD$100.00 = RD$10.00" in resumen["texto"]
    assert "15% SOBRE RD$50.00 = RD$7.50" in resumen["texto"]
    assert "COMISIÓN A COBRAR: RD$17.50" in resumen["texto"]
    assert "80.00" not in resumen["comision"]["real"]["ventas_validas"]
    ajeno = _dia(entorno, otra["headers"])
    assert ajeno["real"]["ventas"] == "80.00"
    assert ajeno["comision"]["real"]["comision"] == "9.60"

    entrega = entorno.c.post("/terminal/entregas",
                             json={"monto": 150, "operacion_id": "entrega-comision"},
                             headers=b["headers"])
    assert entrega.status_code == 201, entrega.text
    despues = _dia(entorno, b["headers"])
    assert despues["real"]["ventas"] == "150.00"
    assert despues["comision"]["real"]["comision"] == "17.50"
    assert entorno.saldo(b["sucursal"]["id"]) == 5764 + 150

    historial = entorno.c.get(f"/comisiones?usuario_id={jose}", headers=entorno.admin).json()
    assert len(historial) == 2
    assert historial[0]["administrador"]
    consolidado = entorno.c.get(
        f"/comisiones/resumen?desde=2026-11-14&hasta=2026-11-14&sucursal_id={b['sucursal']['id']}",
        headers=entorno.admin,
    ).json()
    assert [fila["usuario"] for fila in consolidado["cajeras"]] == ["jose"]
    liquidar = entorno.c.post("/comisiones/liquidaciones", json={
        "usuario_id": jose, "desde": "2026-11-14", "hasta": "2026-11-14",
        "operacion_id": "liq-jose-1",
    }, headers=entorno.admin)
    assert liquidar.status_code == 201, liquidar.text
    assert liquidar.json()["estado"] == "pendiente"
    assert liquidar.json()["importe"] == "17.50"
    repetida = entorno.c.post("/comisiones/liquidaciones", json={
        "usuario_id": jose, "desde": "2026-11-14", "hasta": "2026-11-14",
        "operacion_id": "liq-jose-2",
    }, headers=entorno.admin)
    assert repetida.json()["id"] == liquidar.json()["id"]
    caja_antes = entorno.c.get("/terminal/sorteos", headers=b["headers"]).json()["mi_caja"]
    general_antes = entorno.saldo(b["sucursal"]["id"])
    pagada = entorno.c.post(f"/comisiones/liquidaciones/{liquidar.json()['id']}/pagar", headers=entorno.admin)
    assert pagada.status_code == 200, pagada.text
    assert pagada.json()["estado"] == "pagada"
    assert pagada.json()["responsable"]
    assert entorno.c.post(
        f"/comisiones/liquidaciones/{liquidar.json()['id']}/pagar", headers=entorno.admin,
    ).status_code == 409
    assert entorno.c.get("/terminal/sorteos", headers=b["headers"]).json()["mi_caja"] == caja_antes
    assert entorno.saldo(b["sucursal"]["id"]) == general_antes
    _poner(entorno, jose, 20)
    assert entorno.c.get("/comisiones/liquidaciones", headers=entorno.admin).json()[0]["importe"] == "17.50"

    db = nueva_sesion()
    assert db.query(ComisionCajera).filter_by(usuario_id=jose).count() == 3
    db.close()


def test_premio_imprime_comprobante_solo_si_el_servidor_confirma(entorno, monkeypatch):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    b = entorno.banca(saldo=5764, nombre="BANCA CASTILLO (PRUEBA)", usuario="jose", clave="prueba123")
    jose = _id(entorno, "jose")
    sorteo = entorno.sorteo_id("LOTEDOM")
    ticket = entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [sorteo], "numeros": "25", "monto": 10}])
    entorno.c.post("/resultados", json={
        "sorteo_id": sorteo, "fecha": "2026-11-14",
        "premio1": 25, "premio2": 54, "premio3": 78, "simulado": True,
    }, headers=entorno.admin)
    corto = entorno.c.post("/terminal/tickets/pagar", json={
        "id": ticket["id"], "serial": ticket["serial"], "operacion_id": "pago-sin-fondo",
    }, headers=b["headers"])
    assert corto.status_code == 409
    assert "comprobante" not in corto.json()
    assert entorno.consultar(ticket)["estado"] == "ganador"
    fondo = entorno.c.post("/fondos", json={
        "sucursal_id": b["sucursal"]["id"], "usuario_id": jose, "monto": 1000,
        "tipo": "aporte_prueba", "operacion_id": "fondo-para-premio",
    }, headers=entorno.admin)
    assert fondo.status_code == 201, fondo.text
    dia = _dia(entorno, b["headers"])
    assert dia["prueba"]["ventas"] == "10.00"
    assert dia["comision"]["prueba"]["ventas_validas"] == "10.00"
    pago = entorno.c.post("/terminal/tickets/pagar", json={
        "id": ticket["id"], "serial": ticket["serial"], "operacion_id": "pago-con-fondo",
    }, headers=b["headers"])
    assert pago.status_code == 200, pago.text
    cuerpo = pago.json()
    assert cuerpo["estado"] == "pagado"
    texto = cuerpo["comprobante"]
    assert "BANCA CASTILLO (PRUEBA)" in texto
    assert "COMPROBANTE DE PREMIO PAGADO" in texto
    assert "PRUEBA — NO OFICIAL" in texto
    assert f"Ticket: {ticket['id']}" in texto
    assert f"Serial: {ticket['serial']}" in texto
    assert "Lotería: LOTEDOM" in texto
    assert "Jugada: QUINIELA 25" in texto
    assert "Monto jugado: RD$10.00" in texto
    assert "PREMIO PAGADO: RD$600.00" in texto
    assert "ESTADO: PAGADO" in texto
    assert "COPIA" not in texto
    assert "pago-con-fondo" in texto
    otro = entorno.c.post("/terminal/login", json={
        "usuario": "jose", "clave": "prueba123", "dispositivo_id": "TEL-PAGO-2",
    })
    assert otro.status_code == 200
    repetido = entorno.c.post("/terminal/tickets/pagar", json={
        "id": ticket["id"], "serial": ticket["serial"], "operacion_id": "pago-segundo-telefono",
    }, headers={"Authorization": f"Bearer {otro.json()['token']}"})
    assert repetido.status_code == 409
    copia = entorno.c.post("/terminal/tickets/reimprimir",
                           json={"id": ticket["id"], "serial": ticket["serial"]},
                           headers=b["headers"])
    assert copia.status_code == 200, copia.text
    assert copia.json()["estado"] == "pagado"
    assert "COPIA" not in copia.json()["comprobante"]
    assert entorno.c.get("/terminal/sorteos", headers=b["headers"]).json()["mi_caja"] == "410.00"
    assert entorno.saldo(b["sucursal"]["id"]) == 5764
