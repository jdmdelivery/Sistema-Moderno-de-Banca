"""HOY, AYER, rango y mes leen el mismo resumen. No mueven dinero ni borran entregas."""
from datetime import datetime

from apps.api import db as dbmod
from apps.api import servicios
from apps.api.models import Entrega, Sesion


def _vender(entorno, headers, monto=10):
    sorteo = entorno.sorteo_id("La Primera 12")
    return entorno.vender_ok(headers, [
        {"tipo": "QN", "sorteos": [sorteo], "numeros": "25", "monto": monto},
    ])


def _resumen(entorno, headers, desde=None, hasta=None):
    ruta = "/terminal/reportes/dia"
    if desde:
        ruta += f"?desde={desde}&hasta={hasta or desde}"
    r = entorno.c.get(ruta, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def test_hoy_ayer_y_rango_imprimen_el_periodo_sin_alterar_saldos(entorno, monkeypatch):
    b = entorno.banca(saldo=5764)
    _vender(entorno, b["headers"], 10)
    antes = entorno.saldo(b["sucursal"]["id"])
    assert antes == 5774

    hoy = _resumen(entorno, b["headers"], "2026-11-14", "2026-11-14")
    assert hoy["real"]["ventas"] == "10.00"
    assert hoy["real"]["premios_pagados"] == "0.00"
    assert hoy["real"]["premios_pendientes"] == "0.00"
    assert hoy["real"]["pagado_en_otra"] == "0.00"
    assert hoy["real"]["quedo"] == "10.00"
    assert hoy["real"]["neto"] == "10.00"
    assert hoy["desde"] == "14-11-2026"
    assert hoy["hasta"] == "14-11-2026"
    assert "Cajera: Operador vend1" in hoy["texto"]
    assert "Período: 14/11/2026" in hoy["texto"]
    assert "Código:" in hoy["texto"]
    assert "Terminal:" in hoy["texto"]
    assert "Impreso:" in hoy["texto"]
    assert "Sucursal:" not in hoy["texto"]
    assert hoy["informe"]["oficial"]["ventas"] == "10.00"
    assert hoy["informe"]["oficial"]["balance"] == "10.00"
    assert hoy["informe"]["oficial"]["total"] == "10.00"
    assert "TICKET" not in hoy["texto"]
    assert entorno.saldo(b["sucursal"]["id"]) == antes

    ayer = _resumen(entorno, b["headers"], "2026-11-13", "2026-11-13")
    assert ayer["real"]["ventas"] == "0.00"
    assert ayer["real"]["quedo"] == "0.00"
    assert "Período: 13/11/2026" in ayer["texto"]
    assert ayer["informe"]["oficial"]["ventas"] == "0.00"
    assert ayer["informe"]["oficial"]["balance"] == "0.00"
    assert ayer["informe"]["oficial"]["total"] == "0.00"

    rango = _resumen(entorno, b["headers"], "2026-11-13", "2026-11-14")
    assert rango["real"]["ventas"] == "10.00"
    assert rango["real"]["quedo"] == "10.00"
    assert "Período: 13/11/2026 al 14/11/2026" in rango["texto"]
    assert rango["informe"]["periodo"] == "13/11/2026 al 14/11/2026"

    entrega = entorno.c.post(
        "/terminal/entregas",
        json={"monto": 10, "operacion_id": "op-resumen"},
        headers=b["headers"],
    )
    assert entrega.status_code == 201, entrega.text
    despues = _resumen(entorno, b["headers"], "2026-11-14", "2026-11-14")
    assert despues["real"]["ventas"] == "10.00"
    assert despues["real"]["quedo"] == "10.00"
    assert despues["informe"]["oficial"]["ventas"] == "10.00"
    assert despues["informe"]["oficial"]["total"] == "10.00"
    assert entorno.saldo(b["sucursal"]["id"]) == antes
    db = dbmod.nueva_sesion()
    assert db.query(Entrega).count() == 1
    db.close()

    invertido = entorno.c.get("/terminal/reportes/dia?desde=2026-11-14&hasta=2026-11-13", headers=b["headers"])
    assert invertido.status_code == 400
    propio = entorno.c.get("/terminal/reportes/dia?desde=2026-11-14&hasta=2026-11-14&alcance=sucursal", headers=b["headers"])
    assert propio.status_code == 403

    db = dbmod.nueva_sesion()
    for sesion in db.query(Sesion).all():
        sesion.expira_en = datetime(2026, 11, 16, 0, 0, 0)
    db.commit()
    db.close()
    monkeypatch.setattr(servicios, "ahora_local", lambda: datetime(2026, 11, 15, 0, 0, 0))
    medianoche = _resumen(entorno, b["headers"])
    assert medianoche["desde"] == "15-11-2026"
    assert medianoche["hasta"] == "15-11-2026"
    assert medianoche["real"]["ventas"] == "0.00"
    assert "Período: 15/11/2026" in medianoche["texto"]
    conservado = _resumen(entorno, b["headers"], "2026-11-14", "2026-11-14")
    assert conservado["real"]["ventas"] == "10.00"
    assert "Período: 14/11/2026" in conservado["texto"]
    assert entorno.saldo(b["sucursal"]["id"]) == antes


def test_el_rango_no_mezcla_la_prueba_con_lo_real(entorno, monkeypatch):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    b = entorno.banca(saldo=5764)
    _vender(entorno, b["headers"], 50)
    hoy = _resumen(entorno, b["headers"], "2026-11-14", "2026-11-14")
    assert hoy["real"]["ventas"] == "0.00"
    assert hoy["prueba"]["ventas"] == "50.00"
    assert "PRUEBA — NO OFICIAL" not in hoy["texto"]
    assert "RD$50.00" in hoy["texto"]
    assert hoy["texto"].count("Ventas") == 1
    ayer = _resumen(entorno, b["headers"], "2026-11-13", "2026-11-13")
    assert ayer["prueba"]["ventas"] == "0.00"
    assert entorno.saldo(b["sucursal"]["id"]) == 5764


def test_mes_completo_incluye_todos_los_dias_y_totales(entorno, monkeypatch):
    b = entorno.banca(saldo=5764)
    _vender(entorno, b["headers"], 10)
    s = entorno.sorteo_id("La Primera 12")
    ganador = entorno.vender_ok(b["headers"], [
        {"tipo": "QN", "sorteos": [s], "numeros": "19", "monto": 5},
    ])
    entorno.liquidar(s, 19, 3, 45)
    pago = entorno.c.post(
        "/terminal/tickets/pagar",
        json={"id": ganador["id"], "serial": ganador["serial"]},
        headers=b["headers"],
    )
    assert pago.status_code == 200, pago.text
    antes = entorno.saldo(b["sucursal"]["id"])

    r = entorno.c.get("/terminal/reportes/mes?anio=2026&mes=11", headers=b["headers"])
    assert r.status_code == 200, r.text
    datos = r.json()
    assert datos["dias_en_mes"] == 30
    assert len(datos["dias"]) == 30
    assert datos["dias"][0]["dia"] == 1
    assert datos["dias"][0]["ventas"] == "0.00"
    assert datos["dias"][13]["dia"] == 14
    assert datos["dias"][13]["ventas"] == "15.00"
    assert datos["dias"][13]["premios_pagados"] == "300.00"
    assert datos["dias"][13]["quedo"] == "-285.00"
    assert datos["totales"]["ventas"] == "15.00"
    assert datos["totales"]["premios_pagados"] == "300.00"
    assert datos["totales"]["quedo"] == "-285.00"
    assert datos["informe"]["periodo"] == "01/11/2026 al 30/11/2026"
    assert datos["informe"]["oficial"]["ventas"] == "15.00"
    assert datos["informe"]["oficial"]["premios_pagados"] == "300.00"
    assert datos["informe"]["oficial"]["comision"] == "0.00"
    assert datos["informe"]["oficial"]["balance"] == "-285.00"
    assert datos["informe"]["oficial"]["recargas"] == "0.00"
    assert datos["informe"]["oficial"]["total"] == "-285.00"
    assert "RESUMEN DE CAJA" in datos["texto"]
    assert "RESUMEN FINAL" not in datos["texto"]
    assert "PRUEBA — NO OFICIAL" not in datos["texto"]
    assert "-RD$285.00" in datos["texto"]
    assert "anio=2026" in datos["impresion"]["url"] and "mes=11" in datos["impresion"]["url"]
    assert entorno.saldo(b["sucursal"]["id"]) == antes

    febrero = entorno.c.get("/terminal/reportes/mes?anio=2024&mes=2", headers=b["headers"])
    assert febrero.status_code == 200, febrero.text
    assert febrero.json()["dias_en_mes"] == 29
    assert len(febrero.json()["dias"]) == 29
    assert febrero.json()["totales"]["ventas"] == "0.00"

    malo = entorno.c.get("/terminal/reportes/mes?anio=2026&mes=13", headers=b["headers"])
    assert malo.status_code == 400
    prohibido = entorno.c.get("/terminal/reportes/mes?anio=2026&mes=11&alcance=sucursal", headers=b["headers"])
    assert prohibido.status_code == 403
