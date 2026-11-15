"""La terminal consulta resultados. No los confirma ni liquida premios."""
from datetime import datetime

from apps.api import db as dbmod
from apps.api import servicios
from apps.api.models import Resultado, Sesion, Sorteo, Ticket
from apps.api.rdlotto import SIN_CONEXION


def _guardar(nombre, fecha, numeros, estado):
    db = dbmod.nueva_sesion()
    sorteo = db.query(Sorteo).filter_by(nombre=nombre).one()
    db.add(Resultado(
        sorteo_id=sorteo.id,
        fecha=fecha,
        premio1=numeros[0],
        premio2=numeros[1],
        premio3=numeros[2],
        estado=estado,
        fuente="rdlotto",
    ))
    db.commit()
    db.close()


def _fila(datos, nombre):
    return next(fila for fila in datos["sorteos"] if fila["nombre"] == nombre)


def test_el_dia_cambia_a_medianoche_y_el_resultado_nuevo_reemplaza_al_anterior(entorno, monkeypatch):
    b = entorno.banca(saldo=5764)
    s = entorno.sorteo_id("La Primera 12")
    vendido = entorno.vender_ok(b["headers"], [
        {"tipo": "QN", "sorteos": [s], "numeros": "19", "monto": 10},
    ])
    antes = entorno.saldo(b["sucursal"]["id"])
    _guardar("La Primera 12", datetime(2026, 11, 14).date(), (19, 3, 45), "en_verificacion")

    hoy = entorno.c.get("/terminal/resultados", headers=b["headers"])
    assert hoy.status_code == 200, hoy.text
    primera = _fila(hoy.json(), "La Primera 12")
    assert primera["vigente"] is True
    assert primera["confirmado"] is False
    assert primera["premio1"] == "19"
    assert primera["premio2"] == "03"
    assert primera["premio3"] == "45"
    assert primera["estado"] == "en_verificacion"
    florida = _fila(hoy.json(), "Florida Día")
    lottedom = _fila(hoy.json(), "LOTEDOM")
    nacional = _fila(hoy.json(), "Nacional Tarde")
    for fuera in (florida, lottedom, nacional):
        assert fuera["pendiente"] is True
        assert fuera["premio1"] is None
        assert fuera["vigente"] is False
    assert {nombre for nombre, _motivo in SIN_CONEXION} <= {fila["nombre"] for fila in hoy.json()["sorteos"]}
    assert entorno.saldo(b["sucursal"]["id"]) == antes

    db = dbmod.nueva_sesion()
    for sesion in db.query(Sesion).all():
        sesion.expira_en = datetime(2026, 11, 16, 0, 0, 0)
    db.commit()
    db.close()
    monkeypatch.setattr(servicios, "ahora_local", lambda: datetime(2026, 11, 15, 0, 0, 0))
    gris = entorno.c.get("/terminal/resultados", headers=b["headers"]).json()
    assert gris["hoy"] == "2026-11-15"
    assert gris["zona"] == "America/Santo_Domingo"
    anterior = _fila(gris, "La Primera 12")
    assert anterior["fecha"] == "2026-11-14"
    assert anterior["vigente"] is False
    assert anterior["premio1"] == "19"
    assert anterior["premio3"] == "45"

    _guardar("La Primera 12", datetime(2026, 11, 15).date(), (7, 11, 22), "en_verificacion")
    nuevo = _fila(entorno.c.get("/terminal/resultados", headers=b["headers"]).json(), "La Primera 12")
    assert nuevo["fecha"] == "2026-11-15"
    assert nuevo["vigente"] is True
    assert nuevo["premio1"] == "07"
    assert nuevo["premio2"] == "11"
    assert nuevo["premio3"] == "22"
    assert nuevo["confirmado"] is False

    db = dbmod.nueva_sesion()
    ticket = db.get(Ticket, vendido["id"])
    assert ticket.estado == "vendido"
    assert float(ticket.premio_total) == 0
    db.close()
    assert entorno.saldo(b["sucursal"]["id"]) == antes


def test_un_error_de_fuente_no_tapa_el_ultimo_resultado_util(entorno):
    b = entorno.banca()
    _guardar("Real Tarde", datetime(2026, 11, 13).date(), (10, 20, 30), "liquidado")
    _guardar("Real Tarde", datetime(2026, 11, 14).date(), (1, 2, 3), "error_fuente")
    fila = _fila(entorno.c.get("/terminal/resultados", headers=b["headers"]).json(), "Real Tarde")
    assert fila["fecha"] == "2026-11-13"
    assert fila["vigente"] is False
    assert fila["confirmado"] is True
    assert fila["premio1"] == "10"
    assert fila["premio2"] == "20"
    assert fila["premio3"] == "30"
