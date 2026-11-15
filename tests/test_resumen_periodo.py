"""HOY, AYER y un rango leen el mismo resumen. No mueven dinero ni borran entregas."""
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
    assert hoy["real"]["neto"] == "10.00"
    assert hoy["desde"] == "14-11-2026"
    assert hoy["hasta"] == "14-11-2026"
    assert "BANCA CASTILLO" in hoy["texto"]
    assert "Sucursal: BANCA CASTILLO" in hoy["texto"]
    assert "Terminal:" in hoy["texto"]
    assert "Cajero: Operador vend1" in hoy["texto"]
    assert "DESDE: 14-11-2026" in hoy["texto"]
    assert "HASTA: 14-11-2026" in hoy["texto"]
    assert "IMPRESO:" in hoy["texto"]
    assert "VENTAS: RD$ 10.00" in hoy["texto"]
    assert entorno.saldo(b["sucursal"]["id"]) == antes

    ayer = _resumen(entorno, b["headers"], "2026-11-13", "2026-11-13")
    assert ayer["real"]["ventas"] == "0.00"
    assert ayer["real"]["neto"] == "0.00"
    assert "DESDE: 13-11-2026" in ayer["texto"]
    assert "HASTA: 13-11-2026" in ayer["texto"]
    assert "VENTAS: RD$ 0.00" in ayer["texto"]

    rango = _resumen(entorno, b["headers"], "2026-11-13", "2026-11-14")
    assert rango["real"]["ventas"] == "10.00"
    assert rango["real"]["neto"] == "10.00"
    assert "DESDE: 13-11-2026" in rango["texto"]
    assert "HASTA: 14-11-2026" in rango["texto"]

    entrega = entorno.c.post(
        "/terminal/entregas",
        json={"monto": 10, "operacion_id": "op-resumen"},
        headers=b["headers"],
    )
    assert entrega.status_code == 201, entrega.text
    despues = _resumen(entorno, b["headers"], "2026-11-14", "2026-11-14")
    assert despues["real"]["ventas"] == "10.00"
    assert despues["real"]["neto"] == "10.00"
    assert despues["texto"] == hoy["texto"] or "VENTAS: RD$ 10.00" in despues["texto"]
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
    assert "DESDE: 15-11-2026" in medianoche["texto"]
    assert "HASTA: 15-11-2026" in medianoche["texto"]
    conservado = _resumen(entorno, b["headers"], "2026-11-14", "2026-11-14")
    assert conservado["real"]["ventas"] == "10.00"
    assert "DESDE: 14-11-2026" in conservado["texto"]
    assert "HASTA: 14-11-2026" in conservado["texto"]
    assert entorno.saldo(b["sucursal"]["id"]) == antes


def test_el_rango_no_mezcla_la_prueba_con_lo_real(entorno, monkeypatch):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    b = entorno.banca(saldo=5764)
    _vender(entorno, b["headers"], 50)
    hoy = _resumen(entorno, b["headers"], "2026-11-14", "2026-11-14")
    assert hoy["real"]["ventas"] == "0.00"
    assert hoy["prueba"]["ventas"] == "50.00"
    assert "PRUEBA — NO OFICIAL" in hoy["texto"]
    ayer = _resumen(entorno, b["headers"], "2026-11-13", "2026-11-13")
    assert ayer["prueba"]["ventas"] == "0.00"
    assert entorno.saldo(b["sucursal"]["id"]) == 5764
