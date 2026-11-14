"""Motor de ganadores: liquidación QN/PL/SP con ejemplos calculados a mano.

Tabla semilla: QN 1.º ×60, 2.º ×10, 3.º ×5 · PL 1-2 ×1200, 1-3 ×400,
2-3 ×200 · SP ×2500.
"""


def _qn(entorno, headers, sorteo, numero, monto):
    return entorno.vender_ok(headers, [{"tipo": "QN", "sorteos": [sorteo], "numeros": numero, "monto": monto}])


def test_qn_primero_segundo_tercero(entorno):
    b = entorno.banca()
    s = entorno.sorteo_id("La Primera 12")
    t1 = _qn(entorno, b["headers"], s, "19", 10)
    t2 = _qn(entorno, b["headers"], s, "03", 10)
    t3 = _qn(entorno, b["headers"], s, "45", 10)
    t4 = _qn(entorno, b["headers"], s, "77", 10)
    entorno.liquidar(s, 19, 3, 45)
    c1, c2, c3, c4 = (entorno.consultar(t) for t in (t1, t2, t3, t4))
    assert c1["estado"] == "ganador" and float(c1["premio_total"]) == 600.00   # 10 × 60
    assert c2["estado"] == "ganador" and float(c2["premio_total"]) == 100.00   # 10 × 10
    assert c3["estado"] == "ganador" and float(c3["premio_total"]) == 50.00    # 10 × 5
    assert c4["estado"] == "no_ganador" and float(c4["premio_total"]) == 0.00
    assert c1["jugadas"][0]["detalle_eval"] == "1ro"
    assert c2["jugadas"][0]["detalle_eval"] == "2do"
    assert c3["jugadas"][0]["detalle_eval"] == "3ro"


def test_pl_combinaciones(entorno):
    b = entorno.banca()
    s = entorno.sorteo_id("La Primera 12")
    t12 = entorno.vender_ok(b["headers"], [{"tipo": "PL", "sorteos": [s], "numeros": "19-03", "monto": 5}])
    t13 = entorno.vender_ok(b["headers"], [{"tipo": "PL", "sorteos": [s], "numeros": "45-19", "monto": 5}])  # orden invertido
    t23 = entorno.vender_ok(b["headers"], [{"tipo": "PL", "sorteos": [s], "numeros": "03-45", "monto": 5}])
    tparcial = entorno.vender_ok(b["headers"], [{"tipo": "PL", "sorteos": [s], "numeros": "19-88", "monto": 5}])
    entorno.liquidar(s, 19, 3, 45)
    assert float(entorno.consultar(t12)["premio_total"]) == 6000.00  # 5 × 1200 (1-2)
    assert float(entorno.consultar(t13)["premio_total"]) == 2000.00  # 5 × 400 (1-3)
    assert float(entorno.consultar(t23)["premio_total"]) == 1000.00  # 5 × 200 (2-3)
    parcial = entorno.consultar(tparcial)
    assert parcial["estado"] == "no_ganador" and float(parcial["premio_total"]) == 0.00
    assert entorno.consultar(t13)["jugadas"][0]["numeros"] == "19-45"  # pareja normalizada


def test_sp_solo_liquida_con_ambos_resultados(entorno):
    b = entorno.banca()
    s_real = entorno.sorteo_id("Real Tarde")
    s_primera = entorno.sorteo_id("La Primera 12")
    t = entorno.vender_ok(b["headers"], [
        {"tipo": "SP", "sorteos": [s_real, s_primera], "numeros": "26-58", "monto": 5},
    ])
    # Solo Real Tarde confirma (su 1.º es 26): el SP queda EN ESPERA
    entorno.liquidar(s_real, 26, 1, 2)
    c = entorno.consultar(t)
    assert c["estado"] == "vendido" and c["jugadas"][0]["evaluada"] is False
    # Confirma La Primera con 58 en 1.º: ahora sí liquida y gana 5 × 2500
    entorno.liquidar(s_primera, 58, 9, 8)
    c = entorno.consultar(t)
    assert c["estado"] == "ganador" and float(c["premio_total"]) == 12500.00
    assert c["jugadas"][0]["detalle_eval"] == "sp"


def test_sp_pierde_si_un_primero_no_coincide(entorno):
    b = entorno.banca()
    s_real = entorno.sorteo_id("Real Tarde")
    s_primera = entorno.sorteo_id("La Primera 12")
    t = entorno.vender_ok(b["headers"], [
        {"tipo": "SP", "sorteos": [s_real, s_primera], "numeros": "26-58", "monto": 5},
    ])
    entorno.liquidar(s_real, 26, 1, 2)
    entorno.liquidar(s_primera, 10, 9, 8)  # el 58 no salió en 1.º
    c = entorno.consultar(t)
    assert c["estado"] == "no_ganador" and float(c["premio_total"]) == 0.00


def test_ticket_mixto_acumula_premio_parcial(entorno):
    b = entorno.banca()
    s_real = entorno.sorteo_id("Real Tarde")
    s_primera = entorno.sorteo_id("La Primera 12")
    t = entorno.vender_ok(b["headers"], [
        {"tipo": "QN", "sorteos": [s_primera], "numeros": "19", "monto": 10},
        {"tipo": "SP", "sorteos": [s_real, s_primera], "numeros": "26-58", "monto": 5},
    ])
    entorno.liquidar(s_primera, 19, 58, 0)  # QN gana 600; el SP sigue esperando a Real
    c = entorno.consultar(t)
    assert c["estado"] == "vendido" and float(c["premio_total"]) == 600.00
    entorno.liquidar(s_real, 26, 4, 5)  # SP: 1.º Real=26 y 1.º Primera=19 → no gana (58 era 2.º)
    c = entorno.consultar(t)
    assert c["estado"] == "ganador" and float(c["premio_total"]) == 600.00


def test_tabla_vigente_al_vender_es_la_que_manda(entorno):
    b = entorno.banca()
    s = entorno.sorteo_id("La Primera 12")
    t = _qn(entorno, b["headers"], s, "19", 10)  # vendido con QN 1.º = ×60
    # El consorcio sube el factor a ×100 DESPUÉS de la venta
    r = entorno.c.post("/tabla-pagos", json={
        "tipo": "QN", "clave": "1ro", "factor": 100, "vigente_desde": "2026-11-14 10:30",
    }, headers=entorno.admin)
    assert r.status_code == 201, r.text
    entorno.liquidar(s, 19, 3, 45)
    # El ticket vendido se liquida con la tabla de SU venta: 10 × 60 = 600
    assert float(entorno.consultar(t)["premio_total"]) == 600.00


def test_resultado_queda_propuesto_hasta_confirmar(entorno):
    b = entorno.banca()
    s = entorno.sorteo_id("La Primera 12")
    t = _qn(entorno, b["headers"], s, "19", 10)
    r = entorno.guardar_resultado(s, 19, 3, 45)
    assert r["estado"] == "propuesto"
    c = entorno.consultar(t)
    assert c["estado"] == "vendido" and c["jugadas"][0]["evaluada"] is False  # nada liquidado aún
    entorno.confirmar(r["id"])
    assert entorno.consultar(t)["estado"] == "ganador"


def test_reliquidacion_prohibida_y_reversion(entorno):
    b = entorno.banca()
    s = entorno.sorteo_id("La Primera 12")
    t = _qn(entorno, b["headers"], s, "19", 10)
    r = entorno.guardar_resultado(s, 19, 3, 45)
    entorno.confirmar(r["id"])
    assert entorno.consultar(t)["estado"] == "ganador"
    # Confirmar dos veces: prohibido
    resp = entorno.c.post(f"/resultados/{r['id']}/confirmar", headers=entorno.admin)
    assert resp.status_code == 409
    # Corregir sin revertir: prohibido
    resp = entorno.c.post("/resultados", json={
        "sorteo_id": s, "fecha": "2026-11-14", "premio1": 20, "premio2": 3, "premio3": 45,
    }, headers=entorno.admin)
    assert resp.status_code == 409
    # Revertir → el ticket vuelve a vendido y sin premio; luego se corrige y reliquida
    resp = entorno.c.post(f"/resultados/{r['id']}/revertir", headers=entorno.admin)
    assert resp.status_code == 200 and resp.json()["estado"] == "propuesto"
    c = entorno.consultar(t)
    assert c["estado"] == "vendido" and float(c["premio_total"]) == 0.00
    entorno.guardar_resultado(s, 20, 3, 45)  # corrección: el 19 ya no es 1.º
    filas = entorno.c.get(f"/resultados?fecha=2026-11-14&sorteo_id={s}", headers=entorno.admin).json()
    entorno.confirmar(filas[0]["id"])
    assert entorno.consultar(t)["estado"] == "no_ganador"


def test_resultado_premios_repetidos_rechazado(entorno):
    s = entorno.sorteo_id("La Primera 12")
    r = entorno.c.post("/resultados", json={
        "sorteo_id": s, "fecha": "2026-11-14", "premio1": 19, "premio2": 19, "premio3": 45,
    }, headers=entorno.admin)
    assert r.status_code == 400
