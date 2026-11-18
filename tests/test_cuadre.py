"""Caja, cuadre y reportes (alcances 7 y 8).

Escenario calculado a mano (todo el 2026-11-14, hora fija 10:00):
- Ventas de la terminal 1: ticket A $100 (QN $100) + ticket B $50 (QN $50) = $150
- El ticket A gana: QN 19 con $100 → 100 × 60 = $6,000; se paga en la misma terminal
- Caja: recibir $200, gasto $50 (con concepto)
- Cuadre = 150 − 6,000 − 50 + 200 = −5,700 (negativo: la banca pagó un premio
  grande con su caja; el número se registra tal cual, sin «ajustes»)
"""


def _escenario(entorno):
    b = entorno.banca(saldo=100000)
    s = entorno.sorteo_id("La Primera 12")
    ta = entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [s], "numeros": "19", "monto": 100}])
    tb = entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [s], "numeros": "77", "monto": 50}])
    entorno.liquidar(s, 19, 3, 45)
    r = entorno.c.post("/terminal/tickets/pagar",
                       json={"id": ta["id"], "serial": ta["serial"]}, headers=b["headers"])
    assert r.status_code == 200, r.text
    return b, ta, tb


def test_gasto_sin_concepto_rechazado(entorno):
    b = entorno.banca()
    r = entorno.c.post("/terminal/caja/gasto",
                       json={"monto": 50, "concepto": None}, headers=b["headers"])
    assert r.status_code == 400 and "concepto" in r.json()["detail"]


def test_cuadre_formula_completa(entorno):
    b, ta, tb = _escenario(entorno)
    r = entorno.c.post("/terminal/caja/recibir",
                       json={"monto": 200, "concepto": "Fondo inicial"}, headers=b["headers"])
    assert r.status_code == 201, r.text
    r = entorno.c.post("/terminal/caja/gasto",
                       json={"monto": 50, "concepto": "Papel de impresora"}, headers=b["headers"])
    assert r.status_code == 201, r.text
    r = entorno.c.post("/terminal/caja/cuadre",
                       json={"efectivo_contado": -5720}, headers=b["headers"])
    assert r.status_code == 201, r.text
    c = r.json()
    assert float(c["ventas_total"]) == 150.00
    assert float(c["premios_pagados_total"]) == 6000.00
    assert float(c["gastos_total"]) == 50.00
    assert float(c["efectivo_recibido_total"]) == 200.00
    assert float(c["total_a_entregar"]) == -5700.00
    assert float(c["diferencia"]) == -20.00  # contó 20 menos: queda registrado
    # El listado de transacciones incluye la entrega
    txs = entorno.c.get("/terminal/caja/transacciones", headers=b["headers"]).json()
    tipos = {t["tipo"] for t in txs}
    assert {"recibir_efectivo", "gasto", "entrega_cuadre"} <= tipos


def test_segundo_cuadre_mismo_dia_rechazado(entorno):
    b, ta, tb = _escenario(entorno)
    r = entorno.c.post("/terminal/caja/cuadre", json={}, headers=b["headers"])
    assert r.status_code == 201
    r = entorno.c.post("/terminal/caja/cuadre", json={}, headers=b["headers"])
    assert r.status_code == 409


def test_resumen_final_y_por_loteria(entorno):
    b, ta, tb = _escenario(entorno)
    r = entorno.c.get("/reportes/resumen?desde=2026-11-14&hasta=2026-11-14&vista=final",
                      headers=entorno.admin).json()
    assert float(r["ventas"]) == 150.00 and r["total_tickets"] == 2
    assert float(r["premios_pagados"]) == 6000.00
    assert float(r["neto"]) == -5850.00
    assert float(r["comision_total"]) == 15.00  # 10% de $150
    r = entorno.c.get("/reportes/resumen?desde=2026-11-14&hasta=2026-11-14&vista=por_loteria",
                      headers=entorno.admin).json()
    fila = [f for f in r["filas"] if f["sorteo"] == "La Primera 12:00 PM"][0]
    assert float(fila["ventas"]) == 150.00 and float(fila["premios"]) == 6000.00 and fila["jugadas"] == 2


def test_pendientes_y_pagado_en_otra_sucursal(entorno):
    b1 = entorno.banca(saldo=100000, codigo="1301", usuario="vend1")
    s = entorno.sorteo_id("La Primera 12")
    t = entorno.vender_ok(b1["headers"], [{"tipo": "QN", "sorteos": [s], "numeros": "19", "monto": 10}])
    entorno.liquidar(s, 19, 3, 45)
    # Antes de pagarse: pendiente de la sucursal vendedora por $600
    rep = entorno.c.get(
        f"/reportes/pendientes?desde=2026-11-14&hasta=2026-11-14&sucursal_id={b1['sucursal']['id']}",
        headers=entorno.admin).json()
    assert float(rep["monto_pendiente"]) == 600.00 and len(rep["pendientes"]) == 1
    # Terminal de otra sucursal no puede pagar (dueño = cajera vendedora).
    b2 = entorno.banca(saldo=1000, codigo="2200", nombre="BANCA PEGUERO", usuario="vend2")
    bloqueado = entorno.c.post("/terminal/tickets/pagar",
                              json={"id": t["id"], "serial": t["serial"]}, headers=b2["headers"])
    assert bloqueado.status_code == 403
    # Panel admin sí registra el pago en otra sucursal.
    r = entorno.c.post(
        "/panel/tickets/pagar",
        json={"id": t["id"], "serial": t["serial"], "sucursal_id": b2["sucursal"]["id"]},
        headers=entorno.admin,
    )
    assert r.status_code == 200, r.text
    rep = entorno.c.get(
        f"/reportes/pendientes?desde=2026-11-14&hasta=2026-11-14&sucursal_id={b1['sucursal']['id']}",
        headers=entorno.admin).json()
    assert float(rep["monto_pendiente"]) == 0.00
    assert float(rep["pagado_en_otra_monto"]) == 600.00 and len(rep["pagados_en_otra"]) == 1
    assert float(rep["total_pagado"]) == 600.00


def test_pendientes_formato_texto_impreso(entorno):
    b1 = entorno.banca(saldo=100000)
    s = entorno.sorteo_id("La Primera 12")
    t = entorno.vender_ok(b1["headers"], [{"tipo": "QN", "sorteos": [s], "numeros": "19", "monto": 10}])
    entorno.liquidar(s, 19, 3, 45)
    r = entorno.c.get(
        f"/reportes/pendientes?desde=2026-11-14&hasta=2026-11-14&sucursal_id={b1['sucursal']['id']}&formato=texto",
        headers=entorno.admin)
    assert r.status_code == 200
    texto = r.text
    assert "BANCA CASTILLO" in texto
    assert "DEL DIA => 14-11-2026 A 14-11-2026" in texto
    assert "Sucursal=> 1301" in texto
    assert "Ticket Pendiente Pago" in texto
    assert f"{t['id']} | $600.00 | 2026-11-14" in texto
    assert "Monto Pendiente: $600.00" in texto
    assert "Total: $600.00" in texto
