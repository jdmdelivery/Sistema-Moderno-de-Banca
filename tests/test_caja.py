"""Modelo de CAJA (corrección urgente de Jose, 2026-11-14).

Antes la venta exigía saldo prepago y lo descontaba: una banca con $0 no
podía vender. Eso es incorrecto para una banca de lotería. Ahora:
- Se vende con la caja en $0; cada venta SUMA el efectivo cobrado.
- El premio pagado SALE de la caja de la sucursal que paga; el pendiente
  no descuenta hasta pagarse.
- Sin efectivo suficiente, el pago se bloquea con advertencia, el premio
  queda pendiente y el intento queda en auditoría.
- Cada sucursal tiene su caja independiente y la venta no se duplica.
"""


def test_caja_en_cero_vende_108_y_al_pagar_50_quedan_58(entorno):
    # El ejemplo literal de Jose: caja $0 → ventas $108 → premio $50 → $58
    b = entorno.banca(saldo=0)
    suc = b["sucursal"]["id"]
    assert entorno.saldo(suc) == 0.00
    s = entorno.sorteo_id("La Primera 12")
    t = entorno.vender_ok(b["headers"], [
        {"tipo": "QN", "sorteos": [s], "numeros": "07", "monto": 75},
        {"tipo": "QN", "sorteos": [s], "numeros": "03", "monto": 5},
        {"tipo": "PL", "sorteos": [s], "numeros": "26-58", "monto": 28},
    ])
    assert float(t["total"]) == 108.00
    assert entorno.saldo(suc) == 108.00  # la venta SUMÓ el efectivo a la caja
    entorno.liquidar(s, 19, 3, 45)  # la QN «03» de $5 gana 2.º: 5 × 10 = $50
    datos = entorno.consultar(t)
    assert datos["estado"] == "ganador" and float(datos["premio_total"]) == 50.00
    assert entorno.saldo(suc) == 108.00  # el premio PENDIENTE no descuenta
    r = entorno.c.post("/terminal/tickets/pagar",
                       json={"id": t["id"], "serial": t["serial"]}, headers=b["headers"])
    assert r.status_code == 200, r.text
    assert entorno.saldo(suc) == 58.00  # 108 − 50: el premio salió de la caja
    movs = entorno.c.get(f"/sucursales/{suc}/movimientos", headers=entorno.admin).json()
    venta = [m for m in movs if m["tipo"] == "venta"]
    pago = [m for m in movs if m["tipo"] == "pago_premio"]
    assert len(venta) == 1 and float(venta[0]["saldo_resultante"]) == 108.00
    assert len(pago) == 1 and float(pago[0]["monto"]) == 50.00
    assert float(pago[0]["saldo_resultante"]) == 58.00


def test_pago_sin_efectivo_se_bloquea_y_queda_en_auditoria(entorno):
    b = entorno.banca(saldo=0)
    suc = b["sucursal"]["id"]
    s = entorno.sorteo_id("La Primera 12")
    t = entorno.vender_ok(b["headers"], [
        {"tipo": "QN", "sorteos": [s], "numeros": "19", "monto": 10},
    ])
    entorno.liquidar(s, 19, 3, 45)  # premio: 10 × 60 = $600; la caja solo tiene $10
    r = entorno.c.post("/terminal/tickets/pagar",
                       json={"id": t["id"], "serial": t["serial"]}, headers=b["headers"])
    assert r.status_code == 409
    detalle = r.json()["detail"]
    assert "Advertencia" in detalle and "queda pendiente" in detalle
    assert entorno.consultar(t)["estado"] == "ganador"  # NO se pagó
    assert entorno.saldo(suc) == 10.00  # la caja no se tocó
    filas = entorno.c.get("/auditoria?entidad=ticket", headers=entorno.admin).json()
    bloqueos = [f for f in filas if f["accion"] == "pago_bloqueado"
                and f["entidad_id"] == str(t["id"])]
    assert len(bloqueos) == 1  # el intento quedó registrado
    # El consorcio entrega efectivo y ahora sí se puede pagar
    entorno.recargar(suc, 1000)
    r = entorno.c.post("/terminal/tickets/pagar",
                       json={"id": t["id"], "serial": t["serial"]}, headers=b["headers"])
    assert r.status_code == 200, r.text
    assert entorno.saldo(suc) == 410.00  # 10 + 1000 − 600


def test_venta_reenviada_con_la_misma_operacion_no_se_duplica(entorno):
    b = entorno.banca(saldo=0)
    suc = b["sucursal"]["id"]
    s = entorno.sorteo_id("La Primera 12")
    cuerpo = {"jugadas": [{"tipo": "QN", "sorteos": [s], "numeros": "07", "monto": 25}],
              "operacion_id": "op-de-prueba-0001"}
    r1 = entorno.c.post("/terminal/venta", json=cuerpo, headers=b["headers"])
    assert r1.status_code == 201, r1.text
    r2 = entorno.c.post("/terminal/venta", json=cuerpo, headers=b["headers"])
    assert r2.status_code == 201, r2.text
    assert r2.json()["id"] == r1.json()["id"]  # el MISMO ticket, no otro
    assert entorno.saldo(suc) == 25.00  # la caja subió una sola vez
    rep = entorno.c.get("/reportes/resumen?desde=2026-11-14&hasta=2026-11-14&vista=final",
                        headers=entorno.admin).json()
    assert rep["total_tickets"] == 1
    movs = entorno.c.get(f"/sucursales/{suc}/movimientos", headers=entorno.admin).json()
    assert len([m for m in movs if m["tipo"] == "venta"]) == 1


def test_cada_sucursal_tiene_su_caja_independiente(entorno):
    b1 = entorno.banca(saldo=0, codigo="1301", usuario="vend1")
    b2 = entorno.banca(saldo=0, codigo="2200", nombre="BANCA PEGUERO", usuario="vend2")
    s = entorno.sorteo_id("La Primera 12")
    entorno.vender_ok(b1["headers"], [{"tipo": "QN", "sorteos": [s], "numeros": "07", "monto": 40}])
    entorno.vender_ok(b2["headers"], [{"tipo": "QN", "sorteos": [s], "numeros": "08", "monto": 15}])
    assert entorno.saldo(b1["sucursal"]["id"]) == 40.00
    assert entorno.saldo(b2["sucursal"]["id"]) == 15.00


def test_cuadre_refleja_los_movimientos_y_la_caja_baja_al_entregar(entorno):
    b = entorno.banca(saldo=0)
    suc = b["sucursal"]["id"]
    s = entorno.sorteo_id("La Primera 12")
    entorno.vender_ok(b["headers"], [
        {"tipo": "QN", "sorteos": [s], "numeros": "07", "monto": 80},
        {"tipo": "PL", "sorteos": [s], "numeros": "26-58", "monto": 28},
    ])
    assert entorno.saldo(suc) == 108.00
    r = entorno.c.post("/terminal/caja/cuadre", json={}, headers=b["headers"])
    assert r.status_code == 201, r.text
    c = r.json()
    assert float(c["ventas_total"]) == 108.00
    assert float(c["premios_pagados_total"]) == 0.00
    assert float(c["total_a_entregar"]) == 108.00
    assert entorno.saldo(suc) == 0.00  # entregó el efectivo: la caja quedó en cero
