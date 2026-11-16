"""Tripleta (TR): ×500, orden libre con multiset, misma fecha/lotería/horario."""
from decimal import Decimal

from apps.api.db import nueva_sesion
from apps.api.models import Consorcio
from apps.api.servicios import _parse_numeros, clave_numero, numeros_jugada


def _tr(entorno, headers, sorteo, numeros, monto):
    return entorno.vender_ok(
        headers,
        [{"tipo": "TR", "sorteos": [sorteo], "numeros": numeros, "monto": monto}],
    )


def _minimo_uno(db_session=None):
    db = db_session or nueva_sesion()
    propio = db_session is None
    consorcio = db.query(Consorcio).first()
    consorcio.monto_min_jugada = Decimal("1")
    db.commit()
    if propio:
        db.close()


def test_parse_y_clave_tripleta():
    assert _parse_numeros("TR", "122538") == (12, 25, 38)
    assert _parse_numeros("TR", "12-25-38") == (12, 25, 38)
    assert _parse_numeros("TR", "001299") == (0, 12, 99)
    assert numeros_jugada(38, 12, 25) == "38-12-25"
    assert clave_numero(38, 12, 25) == "12-25-38"
    assert clave_numero(12, 12, 38) == "12-12-38"


def test_tr_gana_orden_original_y_permutaciones(entorno):
    b = entorno.banca()
    s = entorno.sorteo_id("La Primera 12")
    t1 = _tr(entorno, b["headers"], s, "12-25-38", 5)
    t2 = _tr(entorno, b["headers"], s, "38-12-25", 5)
    t3 = _tr(entorno, b["headers"], s, "25-38-12", 5)
    t4 = _tr(entorno, b["headers"], s, "122538", 5)
    assert t1["jugadas"][0]["numeros"] == "12-25-38"
    assert t2["jugadas"][0]["numeros"] == "38-12-25"
    entorno.liquidar(s, 12, 25, 38)
    for t in (t1, t2, t3, t4):
        c = entorno.consultar(t)
        assert c["estado"] == "ganador"
        assert float(c["premio_total"]) == 2500.00  # 5 × 500
        assert c["jugadas"][0]["detalle_eval"] == "tr"


def test_tr_pierde_si_falta_un_numero(entorno):
    b = entorno.banca()
    s = entorno.sorteo_id("La Primera 12")
    t = _tr(entorno, b["headers"], s, "12-25-40", 5)
    entorno.liquidar(s, 12, 25, 38)
    c = entorno.consultar(t)
    assert c["estado"] == "no_ganador" and float(c["premio_total"]) == 0.00


def test_tr_ceros_iniciales(entorno):
    b = entorno.banca()
    s = entorno.sorteo_id("La Primera 12")
    t = _tr(entorno, b["headers"], s, "000712", 5)
    assert t["jugadas"][0]["numeros"] == "00-07-12"
    entorno.liquidar(s, 0, 7, 12)
    c = entorno.consultar(t)
    assert c["estado"] == "ganador" and float(c["premio_total"]) == 2500.00


def test_tr_entrada_longitud_invalida(entorno):
    b = entorno.banca()
    s = entorno.sorteo_id("La Primera 12")
    for nums in ("12253", "1225389", "12-25", "12-25-38-01"):
        r = entorno.vender(b["headers"], [{"tipo": "TR", "sorteos": [s], "numeros": nums, "monto": 5}])
        assert r.status_code == 400, nums


def test_tr_premio_1_y_50(entorno):
    _minimo_uno()
    b = entorno.banca()
    s = entorno.sorteo_id("La Primera 12")
    t1 = _tr(entorno, b["headers"], s, "19-03-45", 1)
    t50 = _tr(entorno, b["headers"], s, "19-03-45", 50)
    entorno.liquidar(s, 19, 3, 45)
    assert float(entorno.consultar(t1)["premio_total"]) == 500.00
    assert float(entorno.consultar(t50)["premio_total"]) == 25000.00


def test_tr_pendiente_hasta_confirmar(entorno):
    b = entorno.banca()
    s = entorno.sorteo_id("La Primera 12")
    t = _tr(entorno, b["headers"], s, "12-25-38", 5)
    r = entorno.guardar_resultado(s, 12, 25, 38)
    assert r["estado"] == "propuesto"
    c = entorno.consultar(t)
    assert c["estado"] == "vendido" and c["jugadas"][0]["evaluada"] is False
    entorno.confirmar(r["id"])
    assert entorno.consultar(t)["estado"] == "ganador"


def test_tr_otra_fecha_no_premia(entorno):
    b = entorno.banca()
    s = entorno.sorteo_id("La Primera 12")
    t = _tr(entorno, b["headers"], s, "12-25-38", 5)
    entorno.liquidar(s, 12, 25, 38, fecha="2026-11-13")
    c = entorno.consultar(t)
    assert c["estado"] == "vendido" and float(c["premio_total"]) == 0.00


def test_tr_otra_loteria_no_premia(entorno):
    b = entorno.banca()
    s1 = entorno.sorteo_id("La Primera 12")
    s2 = entorno.sorteo_id("Real Tarde")
    t = _tr(entorno, b["headers"], s1, "12-25-38", 5)
    entorno.liquidar(s2, 12, 25, 38)
    c = entorno.consultar(t)
    assert c["estado"] == "vendido" and float(c["premio_total"]) == 0.00


def test_ticket_mixto_qn_pl_sp_tr(entorno):
    b = entorno.banca()
    s_real = entorno.sorteo_id("Real Tarde")
    s_primera = entorno.sorteo_id("La Primera 12")
    t = entorno.vender_ok(b["headers"], [
        {"tipo": "QN", "sorteos": [s_primera], "numeros": "19", "monto": 10},
        {"tipo": "PL", "sorteos": [s_primera], "numeros": "19-03", "monto": 5},
        {"tipo": "SP", "sorteos": [s_real, s_primera], "numeros": "26-19", "monto": 5},
        {"tipo": "TR", "sorteos": [s_primera], "numeros": "19-03-45", "monto": 5},
    ])
    entorno.liquidar(s_primera, 19, 3, 45)
    c = entorno.consultar(t)
    # QN 600 + PL 6000 + TR 2500; SP espera Real
    assert float(c["premio_total"]) == 9100.00
    assert c["estado"] == "ganador"
    assert any(j["tipo"] == "TR" for j in c["jugadas"])
    entorno.liquidar(s_real, 26, 1, 2)
    c = entorno.consultar(t)
    assert float(c["premio_total"]) == 21600.00  # + SP 12500


def test_tr_multiset_resultados_oficiales_con_repetidos(entorno):
    """TR gana solo si el multiset coincide; 12-12-38 ≠ 12-38-38."""
    b = entorno.banca()
    s = entorno.sorteo_id("La Primera 12")
    gana = _tr(entorno, b["headers"], s, "12-12-38", 5)
    pierde = _tr(entorno, b["headers"], s, "12-38-38", 5)
    permuta = _tr(entorno, b["headers"], s, "38-12-12", 5)
    entorno.liquidar(s, 12, 12, 38)
    assert entorno.consultar(gana)["estado"] == "ganador"
    assert float(entorno.consultar(gana)["premio_total"]) == 2500.00
    assert entorno.consultar(permuta)["estado"] == "ganador"
    assert entorno.consultar(pierde)["estado"] == "no_ganador"


def test_tr_ceros_y_triple_repetido(entorno):
    b = entorno.banca()
    s = entorno.sorteo_id("La Primera 12")
    t00 = _tr(entorno, b["headers"], s, "00-00-25", 5)
    entorno.liquidar(s, 0, 0, 25)
    assert entorno.consultar(t00)["estado"] == "ganador"
    assert float(entorno.consultar(t00)["premio_total"]) == 2500.00

    s2 = entorno.sorteo_id("Real Tarde")
    t25 = _tr(entorno, b["headers"], s2, "25-25-25", 5)
    qn = entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [s2], "numeros": "25", "monto": 10}])
    entorno.liquidar(s2, 25, 25, 25)
    assert entorno.consultar(t25)["estado"] == "ganador"
    assert float(entorno.consultar(t25)["premio_total"]) == 2500.00
    # QN sin cambio: cobra la primera posición que coincida (1ro ×60).
    c_qn = entorno.consultar(qn)
    assert c_qn["estado"] == "ganador"
    assert float(c_qn["premio_total"]) == 600.00
    assert c_qn["jugadas"][0]["detalle_eval"] == "1ro"


def test_tr_pago_parcial_y_doble_cobro(entorno):
    b = entorno.banca()
    s1 = entorno.sorteo_id("La Primera 12")
    s2 = entorno.sorteo_id("Real Tarde")
    t = entorno.vender_ok(b["headers"], [
        {"tipo": "TR", "sorteos": [s1], "numeros": "12-25-38", "monto": 5},
        {"tipo": "QN", "sorteos": [s2], "numeros": "26", "monto": 10},
    ])
    entorno.liquidar(s1, 12, 25, 38)
    c = entorno.consultar(t)
    assert c["estado"] == "ganador" and float(c["premio_total"]) == 2500.00
    r = entorno.c.post(
        "/terminal/tickets/pagar",
        json={"id": t["id"], "serial": t["serial"], "operacion_id": "pago-tr-1"},
        headers=b["headers"],
    )
    assert r.status_code == 200, r.text
    pago = r.json()
    assert pago["premio_pagado"] == "2500.00"
    assert pago["estado"] == "parcial"
    r2 = entorno.c.post(
        "/terminal/tickets/pagar",
        json={"id": t["id"], "serial": t["serial"], "operacion_id": "pago-tr-1"},
        headers=b["headers"],
    )
    assert r2.status_code == 200
    assert r2.json()["premio_pagado"] == "2500.00"
    entorno.liquidar(s2, 26, 1, 2)
    r3 = entorno.c.post(
        "/terminal/tickets/pagar",
        json={"id": t["id"], "serial": t["serial"], "operacion_id": "pago-tr-2"},
        headers=b["headers"],
    )
    assert r3.status_code == 200, r3.text
    assert r3.json()["premio_pagado"] == "3100.00"
    r4 = entorno.c.post(
        "/terminal/tickets/pagar",
        json={"id": t["id"], "serial": t["serial"], "operacion_id": "pago-tr-3"},
        headers=b["headers"],
    )
    assert r4.status_code in (400, 409)
