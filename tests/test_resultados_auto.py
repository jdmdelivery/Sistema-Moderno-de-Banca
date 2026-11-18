"""Recepción de RDLotto, liquidación solo al confirmar y caja de la cajera.

No llama a internet: el documento tiene la forma real de
GET /api/v1/results?date=, observada el 2026-11-14.
"""
from datetime import date, datetime

from apps.api import db as dbmod
from apps.api import resultados_auto, rdlotto
from apps.api.models import CorreccionPendiente, Resultado, Usuario


def _draw(game, session, hora, numeros, status="verified", fuentes=None):
    return {
        "game": game,
        "session": session,
        "date": "2026-11-14",
        "time": hora,
        "status": status,
        "numbers": numeros,
        "reportedBy": fuentes if fuentes is not None else ["enloteria", "conectate"],
        "url": f"https://rdlotto.com/x/{game}/2026-11-14",
    }


def _doc(*draws):
    return {"date": "2026-11-14", "draws": list(draws)}


def test_la_cobertura_no_mezcla_sorteos_parecidos():
    cobertura = rdlotto.cobertura()
    assert len(cobertura) == 40
    nombres = {fila["sorteo"] for fila in cobertura if fila["conectada"]}
    assert nombres == {
        "La Primera 12:00 PM", "La Suerte Dominicana 12:30 PM", "King Lottery 12:30 PM",
        "Quiniela Real 12:55 PM", "La Anguila 1:00 PM", "La Suerte Dominicana 6:00 PM",
        "La Anguila 6:00 PM", "King Lottery 7:30 PM", "Loteka 7:55 PM", "La Anguila 9:00 PM",
    }
    for fuera in ("Lotedom 12:00 PM", "Leidsa 8:55 PM", "La Primera 7:00 PM",
                  "Florida 2:30 PM", "Florida 10:45 PM", "New York 3:30 PM", "New York 11:30 PM",
                  "Haiti Bolet 9:30 AM", "Lotería Nacional 9:00 PM"):
        assert fuera not in nombres


def test_un_resultado_verificado_no_liquida_hasta_confirmarlo(entorno):
    b = entorno.banca()
    s = entorno.sorteo_id("La Primera 12")
    t = entorno.vender_ok(b["headers"], [
        {"tipo": "QN", "sorteos": [s], "numeros": "19", "monto": 10},
    ])
    doc = _doc(_draw("la-primera-quiniela", "dia", "12:00", ["19", "03", "45"]))
    resumen = rdlotto.sincronizar(dbmod.nueva_sesion(), date(2026, 11, 14), documento=doc)
    assert resumen["ok"] is True and resumen["guardados"] == 1
    otra = rdlotto.sincronizar(dbmod.nueva_sesion(), date(2026, 11, 14), documento=doc)
    assert otra["guardados"] == 0
    db = dbmod.nueva_sesion()
    fila = db.query(Resultado).filter_by(sorteo_id=s).one()
    assert fila.estado == "en_verificacion"
    assert fila.premio1 == 19 and fila.version == 1
    db.close()
    assert entorno.consultar(t)["veredicto"] == "RESULTADOS PENDIENTES"
    assert entorno.consultar(t)["puede_pagar"] is False
    liquidado = entorno.confirmar(fila.id)
    assert liquidado["estado"] == "liquidado"
    consulta = entorno.consultar(t)
    assert consulta["veredicto"] == "TICKET GANADOR — PENDIENTE DE PAGO"
    assert float(consulta["premio_total"]) == 600
    ganadores = entorno.c.get("/ganadores", headers=entorno.admin).json()
    assert ganadores["total_tickets"] == 1
    assert ganadores["premios_pendientes"] == "600.00"


def test_un_resultado_provisional_no_se_puede_confirmar(entorno):
    b = entorno.banca()
    s = entorno.sorteo_id("La Anguila 9:00 PM")
    entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [s], "numeros": "86", "monto": 5}])
    doc = _doc(_draw("anguila-noche", "noche", "21:00", ["86", "38", "37"], status="live"))
    rdlotto.sincronizar(dbmod.nueva_sesion(), date(2026, 11, 14), documento=doc)
    db = dbmod.nueva_sesion()
    fila = db.query(Resultado).filter_by(sorteo_id=s).one()
    assert fila.estado == "recibido"
    db.close()
    r = entorno.c.post(f"/resultados/{fila.id}/confirmar", headers=entorno.admin)
    assert r.status_code == 409
    assert "provisional" in r.json()["detail"]


def test_no_guarda_un_sorteo_de_otra_hora_ni_inventa_si_falla(entorno, monkeypatch):
    doc = _doc(
        _draw("la-primera-quiniela", "noche", "19:00", ["53", "31", "65"]),
        _draw("quiniela-real", "dia", "12:55", ["67", "33", "84"]),
    )
    resumen = rdlotto.sincronizar(dbmod.nueva_sesion(), date(2026, 11, 14), documento=doc)
    assert resumen["guardados"] == 1
    db = dbmod.nueva_sesion()
    assert db.query(Resultado).count() == 1
    assert db.query(Resultado).one().sorteo.nombre == "Quiniela Real 12:55 PM"
    db.close()

    def falla(fecha):
        return None, "HTTP 503"

    monkeypatch.setattr(rdlotto, "descargar", falla)
    mal = rdlotto.sincronizar(dbmod.nueva_sesion(), date(2026, 11, 14))
    assert mal["ok"] is False
    db = dbmod.nueva_sesion()
    assert db.query(Resultado).count() == 1
    db.close()


def test_una_correccion_de_lo_ya_liquidado_no_mueve_el_premio(entorno):
    b = entorno.banca()
    s = entorno.sorteo_id("Real Tarde")
    t = entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [s], "numeros": "67", "monto": 10}])
    doc = _doc(_draw("quiniela-real", "dia", "12:55", ["67", "33", "84"]))
    rdlotto.sincronizar(dbmod.nueva_sesion(), date(2026, 11, 14), documento=doc)
    db = dbmod.nueva_sesion()
    fila = db.query(Resultado).one()
    db.close()
    entorno.confirmar(fila.id)
    assert float(entorno.consultar(t)["premio_total"]) == 600
    corregido = _doc(_draw("quiniela-real", "dia", "12:55", ["01", "02", "03"]))
    rdlotto.sincronizar(dbmod.nueva_sesion(), date(2026, 11, 14), documento=corregido)
    assert float(entorno.consultar(t)["premio_total"]) == 600
    db = dbmod.nueva_sesion()
    assert db.query(CorreccionPendiente).count() == 1
    assert db.query(Resultado).one().premio1 == 67
    db.close()


def test_la_prueba_se_liquida_sola_sin_tocar_la_caja_real(entorno, monkeypatch):
    b = entorno.banca(saldo=5764)
    s = entorno.sorteo_id("La Primera 12")
    real = entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [s], "numeros": "19", "monto": 10}])
    assert real["es_prueba"] is False
    assert entorno.saldo(b["sucursal"]["id"]) == 5774
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    prueba = entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [s], "numeros": "19", "monto": 10}])
    assert prueba["es_prueba"] is True
    doc = _doc(_draw("la-primera-quiniela", "dia", "12:00", ["19", "03", "45"]))
    resumen = rdlotto.sincronizar(dbmod.nueva_sesion(), date(2026, 11, 14), documento=doc)
    assert resumen["pruebas_liquidadas"] == 1
    assert resumen["no_oficial"] is True
    db = dbmod.nueva_sesion()
    fila = db.query(Resultado).one()
    assert fila.estado == "en_verificacion"
    usuario = db.query(Usuario).filter_by(usuario="vend1").one()
    usuario.saldo_caja_prueba = 8000
    db.commit()
    db.close()
    assert entorno.consultar(real)["estado"] == "vendido"
    consulta = entorno.consultar(prueba)
    assert consulta["veredicto"] == "TICKET GANADOR — PENDIENTE DE PAGO — NO OFICIAL"
    assert float(consulta["premio_total"]) == 600
    assert consulta["puede_pagar"] is True
    ganadores = entorno.c.get("/ganadores", headers=entorno.admin).json()
    assert ganadores["total_tickets"] == 0
    assert ganadores["prueba"][0]["leyenda"] == "PRUEBA — NO OFICIAL"
    monkeypatch.delenv("MODO_DESARROLLO")
    bloqueado = entorno.c.post(
        "/terminal/tickets/pagar",
        json={"id": prueba["id"], "serial": prueba["serial"], "operacion_id": "prueba-1"},
        headers=b["headers"],
    )
    assert bloqueado.status_code == 409
    assert entorno.saldo(b["sucursal"]["id"]) == 5774
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    pago = entorno.c.post(
        "/terminal/tickets/pagar",
        json={"id": prueba["id"], "serial": prueba["serial"], "operacion_id": "prueba-1"},
        headers=b["headers"],
    )
    assert pago.status_code == 200, pago.text
    assert pago.json()["mi_caja"] == "7400.00"
    assert pago.json()["veredicto"] == "ESTE TICKET YA SE PAGÓ"
    assert entorno.saldo(b["sucursal"]["id"]) == 5774
    repetido = entorno.c.post(
        "/terminal/tickets/pagar",
        json={"id": prueba["id"], "serial": prueba["serial"], "operacion_id": "prueba-1"},
        headers=b["headers"],
    )
    assert repetido.status_code == 200
    assert entorno.saldo(b["sucursal"]["id"]) == 5774


def test_el_pago_descuenta_la_caja_de_quien_paga_una_sola_vez(entorno):
    """Solo la cajera vendedora puede pagar por terminal; la caja baja una sola vez."""
    vendedora = entorno.banca()
    ajena = entorno.banca(saldo=5000, codigo="2200", nombre="BANCA PEGUERO", usuario="vend2")
    s = entorno.sorteo_id("La Primera 12")
    t = entorno.vender_ok(vendedora["headers"], [{"tipo": "QN", "sorteos": [s], "numeros": "19", "monto": 10}])
    entorno.liquidar(s, 19, 3, 45)
    db = dbmod.nueva_sesion()
    for nombre in ("vend1", "vend2"):
        usuario = db.query(Usuario).filter_by(usuario=nombre).one()
        usuario.saldo_caja = 8000
    db.commit()
    db.close()
    bloqueado = entorno.c.post(
        "/terminal/tickets/pagar",
        json={"id": t["id"], "serial": t["serial"], "operacion_id": "pago-ajeno"},
        headers=ajena["headers"],
    )
    assert bloqueado.status_code == 403
    r = entorno.c.post(
        "/terminal/tickets/pagar",
        json={"id": t["id"], "serial": t["serial"], "operacion_id": "pago-1"},
        headers=vendedora["headers"],
    )
    assert r.status_code == 200, r.text
    assert r.json()["mi_caja"] == "7400.00"
    repetido = entorno.c.post(
        "/terminal/tickets/pagar",
        json={"id": t["id"], "serial": t["serial"], "operacion_id": "pago-1"},
        headers=vendedora["headers"],
    )
    assert repetido.status_code == 200
    db = dbmod.nueva_sesion()
    assert str(db.query(Usuario).filter_by(usuario="vend1").one().saldo_caja) == "7400.00"
    assert str(db.query(Usuario).filter_by(usuario="vend2").one().saldo_caja) == "8000.00"
    db.close()
    # Caja de sucursal vendedora: saldo inicial + venta 10 − premio 600.
    assert entorno.saldo(vendedora["sucursal"]["id"]) == 99410.00


def test_el_ciclo_no_consulta_rdlotto(entorno, monkeypatch):
    def prohibido(fecha):
        raise AssertionError("RDLotto no debe consultarse")

    monkeypatch.setattr(rdlotto, "descargar", prohibido)
    resumen = resultados_auto.ciclo(forzar=False, payload=[])
    assert resumen["ok"] is True
    assert resumen["rdlotto"] is False
    assert resumen["confirmados"] == 0
