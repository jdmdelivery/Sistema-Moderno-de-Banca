"""Widget de Conéctate, tres lecturas, diez minutos y premios sin pago automático."""
from datetime import datetime

from apps.api import conectate_widget, estabilizacion, resultados_auto
from apps.api import db as dbmod
from apps.api.models import (
    ColaPremio,
    CorreccionPendiente,
    ObservacionResultado,
    Resultado,
    Sorteo,
    TipoJugada,
    Usuario,
)


def _item(titulo, numeros, dia="14-11"):
    return {"game_title": titulo, "date": dia, "score": [str(n) for n in numeros]}


def _pasar(entorno, fijar_hora, nombre, numeros, momentos):
    marcas = []
    for momento in momentos:
        fijar_hora(momento)
        db = dbmod.nueva_sesion()
        sorteo = db.query(Sorteo).filter_by(nombre=nombre, activo=True).one()
        marcas.append(estabilizacion.observar(db, sorteo, momento.date(), numeros, momento))
        estabilizacion.procesar_cola(db)
        db.commit()
        db.close()
    return marcas


def test_el_titulo_exige_nombre_y_hora():
    sabado = datetime(2026, 11, 14).date()
    domingo = datetime(2026, 11, 15).date()
    assert conectate_widget.mapear_titulo("La Primera Día", sabado) == "La Primera 12:00 PM"
    assert conectate_widget.mapear_titulo("Primera Noche", sabado) == "La Primera 7:00 PM"
    assert conectate_widget.mapear_titulo("Anguila 10:00 AM", sabado) == "La Anguila 10:00 AM"
    assert conectate_widget.mapear_titulo("Anguila 9:00 PM", sabado) == "La Anguila 9:00 PM"
    assert conectate_widget.mapear_titulo("Quiniela Loteka Noche", sabado) == "Loteka 7:55 PM"
    assert conectate_widget.mapear_titulo("Quiniela Loteka Día", sabado) is None
    assert conectate_widget.mapear_titulo("New Jersey Día", sabado) is None
    assert conectate_widget.mapear_titulo("Haiti Bolet", sabado) is None
    assert conectate_widget.mapear_titulo("Haiti Bolet 9:30 AM", sabado) == "Haiti Bolet 9:30 AM"
    assert conectate_widget.mapear_titulo("Quiniela Leidsa", sabado) == "Leidsa 8:55 PM"
    assert conectate_widget.mapear_titulo("Quiniela Leidsa", domingo) == "Leidsa 3:55 PM"
    assert conectate_widget.mapear_titulo("Lotería Nacional", sabado) == "Lotería Nacional 9:00 PM"
    assert conectate_widget.mapear_titulo("Lotería Nacional", domingo) == "Lotería Nacional 6:00 PM"
    assert conectate_widget.mapear_titulo("Gana Más", sabado) == "Lotería Nacional 2:30 PM"
    assert len(conectate_widget.RECONOCIDOS) == 40


def test_no_hay_tripleta():
    db = dbmod.nueva_sesion()
    codigos = {fila.codigo for fila in db.query(TipoJugada).all()}
    db.close()
    assert codigos == {"QN", "PL", "SP", "TR"}


def test_tres_lecturas_iguales_y_diez_minutos_dejan_el_premio_pendiente(entorno, fijar_hora):
    b = entorno.banca(saldo=100000)
    s = entorno.sorteo_id("La Primera 12:00 PM")
    ticket = entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [s], "numeros": "19", "monto": 5}])
    caja = entorno.saldo(b["sucursal"]["id"])
    base = datetime(2026, 11, 14, 12, 5)
    marcas = _pasar(entorno, fijar_hora, "La Primera 12:00 PM", (19, 3, 45), [
        base, base.replace(minute=9), base.replace(minute=13),
    ])
    assert marcas == ["provisional", "provisional", "provisional"]
    marcas = _pasar(entorno, fijar_hora, "La Primera 12:00 PM", (19, 3, 45), [base.replace(minute=15)])
    assert marcas == ["confirmado"]
    consulta = entorno.consultar(ticket)
    assert consulta["estado"] == "ganador"
    assert consulta["premio_total"] == "300.00"
    assert consulta["puede_pagar"] is True
    assert entorno.saldo(b["sucursal"]["id"]) == caja
    db = dbmod.nueva_sesion()
    usuario = db.query(Usuario).filter_by(usuario="vend1").one()
    usuario.saldo_caja = 5000
    db.commit()
    db.close()
    pago = entorno.c.post(
        "/terminal/tickets/pagar",
        json={"id": ticket["id"], "serial": ticket["serial"], "operacion_id": "pago-widget-1"},
        headers=b["headers"],
    )
    assert pago.status_code == 200, pago.text
    assert entorno.saldo(b["sucursal"]["id"]) == caja - 300
    otra = entorno.c.post(
        "/terminal/tickets/pagar",
        json={"id": ticket["id"], "serial": ticket["serial"], "operacion_id": "pago-widget-2"},
        headers=b["headers"],
    )
    assert otra.status_code == 409
    assert entorno.saldo(b["sucursal"]["id"]) == caja - 300


def test_un_cambio_de_numeros_reinicia_la_espera(entorno, fijar_hora):
    base = datetime(2026, 11, 14, 12, 5)
    marcas = _pasar(entorno, fijar_hora, "La Primera 12:00 PM", (19, 3, 45), [base, base.replace(minute=9)])
    assert marcas == ["provisional", "provisional"]
    marcas = _pasar(entorno, fijar_hora, "La Primera 12:00 PM", (1, 2, 3), [base.replace(minute=15)])
    assert marcas == ["provisional"]
    db = dbmod.nueva_sesion()
    obs = db.query(ObservacionResultado).one()
    assert obs.lecturas == 1
    assert db.query(Resultado).one().estado == "propuesto"
    db.close()


def test_el_manual_bloqueado_no_se_reemplaza(entorno, fijar_hora):
    s = entorno.sorteo_id("La Primera 12:00 PM")
    entorno.guardar_resultado(s, 11, 22, 33)
    fijar_hora(datetime(2026, 11, 14, 12, 20))
    db = dbmod.nueva_sesion()
    sorteo = db.get(Sorteo, s)
    marca = estabilizacion.observar(db, sorteo, sorteo and datetime(2026, 11, 14).date(), (19, 3, 45), datetime(2026, 11, 14, 12, 20))
    db.commit()
    fila = db.query(Resultado).one()
    assert marca == "bloqueado"
    assert (fila.premio1, fila.premio2, fila.premio3) == (11, 22, 33)
    assert fila.fuente == "manual"
    db.close()


def test_un_confirmado_que_cambia_queda_en_alerta_y_no_toca_lo_pagado(entorno, fijar_hora):
    b = entorno.banca(saldo=100000)
    s = entorno.sorteo_id("La Primera 12:00 PM")
    ticket = entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [s], "numeros": "19", "monto": 5}])
    base = datetime(2026, 11, 14, 12, 5)
    _pasar(entorno, fijar_hora, "La Primera 12:00 PM", (19, 3, 45), [
        base, base.replace(minute=9), base.replace(minute=15),
    ])
    db = dbmod.nueva_sesion()
    usuario = db.query(Usuario).filter_by(usuario="vend1").one()
    usuario.saldo_caja = 5000
    db.commit()
    db.close()
    pago = entorno.c.post(
        "/terminal/tickets/pagar",
        json={"id": ticket["id"], "serial": ticket["serial"], "operacion_id": "pago-alerta"},
        headers=b["headers"],
    )
    assert pago.status_code == 200, pago.text
    caja = entorno.saldo(b["sucursal"]["id"])
    fijar_hora(datetime(2026, 11, 14, 12, 30))
    db = dbmod.nueva_sesion()
    sorteo = db.get(Sorteo, s)
    marca = estabilizacion.observar(
        db, sorteo, datetime(2026, 11, 14).date(), (1, 2, 3), datetime(2026, 11, 14, 12, 30),
    )
    db.commit()
    assert marca == "alerta"
    assert db.query(CorreccionPendiente).count() == 1
    assert db.query(Resultado).one().premio1 == 19
    db.close()
    assert entorno.consultar(ticket)["estado"] == "pagado"
    assert entorno.consultar(ticket)["premio_total"] == "300.00"
    assert entorno.saldo(b["sucursal"]["id"]) == caja


def test_pale_y_super_pale_y_la_cola_no_duplica(entorno, fijar_hora):
    b = entorno.banca(saldo=100000)
    primera = entorno.sorteo_id("La Primera 12:00 PM")
    real = entorno.sorteo_id("Quiniela Real 12:55 PM")
    pale = entorno.vender_ok(b["headers"], [{"tipo": "PL", "sorteos": [primera], "numeros": "03-19", "monto": 5}])
    superpale = entorno.vender_ok(
        b["headers"], [{"tipo": "SP", "sorteos": [primera, real], "numeros": "19-07", "monto": 5}],
    )
    base = datetime(2026, 11, 14, 13, 0)
    _pasar(entorno, fijar_hora, "La Primera 12:00 PM", (19, 3, 45), [base, base.replace(minute=4), base.replace(minute=10)])
    assert entorno.consultar(pale)["premio_total"] == "6000.00"
    assert entorno.consultar(superpale)["estado"] == "vendido"
    _pasar(entorno, fijar_hora, "Quiniela Real 12:55 PM", (7, 8, 9), [base, base.replace(minute=4), base.replace(minute=10)])
    assert entorno.consultar(superpale)["estado"] == "ganador"
    assert entorno.consultar(superpale)["premio_total"] == "12500.00"
    db = dbmod.nueva_sesion()
    assert db.query(ColaPremio).count() == 2
    otra = estabilizacion.procesar_cola(db)
    db.commit()
    db.close()
    assert otra == 0
    assert entorno.consultar(pale)["premio_total"] == "6000.00"
    assert entorno.saldo(b["sucursal"]["id"]) == 100010


def test_el_ciclo_usa_el_widget_y_no_confirma_si_falla(entorno, monkeypatch):
    def caido(timeout=20):
        return None, "HTTP 403"

    monkeypatch.setattr(conectate_widget, "descargar", caido)
    mal = resultados_auto.ciclo()
    assert mal["ok"] is False
    assert mal["rdlotto"] is False
    db = dbmod.nueva_sesion()
    assert db.query(Resultado).count() == 0
    db.close()
    bien = resultados_auto.ciclo(forzar=True, payload=[
        _item("La Primera Día", (19, 3, 45)),
        _item("Primera Noche", (1, 2, 3)),
        _item("Quiniela Loteka Día", (8, 9, 10)),
    ])
    assert bien["ok"] is True and bien["confirmados"] == 0 and bien["rdlotto"] is False
    db = dbmod.nueva_sesion()
    nombres = {fila.sorteo.nombre: (fila.premio1, fila.premio2, fila.premio3) for fila in db.query(Resultado)}
    db.close()
    assert nombres["La Primera 12:00 PM"] == (19, 3, 45)
    assert nombres["La Primera 7:00 PM"] == (1, 2, 3)
    assert "Loteka 7:55 PM" not in nombres


def test_la_prueba_del_widget_no_guarda(entorno, monkeypatch):
    monkeypatch.setattr(
        conectate_widget, "descargar",
        lambda timeout=20: ([{"game_title": "La Primera Día", "date": "14-11", "score": [1, 2, 3]}], None),
    )
    r = entorno.c.get("/fuente-resultados/probar", headers=entorno.admin)
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True
    assert r.json()["titulos"] == ["La Primera Día"]
    from apps.api.models import Resultado
    db = dbmod.nueva_sesion()
    assert db.query(Resultado).count() == 0
    db.close()


def test_la_seccion_movil_lista_los_cuarenta(entorno):
    panel = entorno.c.get("/movil/admin?seccion=resultados", headers=entorno.admin)
    assert panel.status_code == 200, panel.text
    texto = "\n".join(panel.json()["lineas"])
    assert texto.startswith("Reloj DETENIDO")
    assert "Reloj DETENIDO" in texto
    assert "La Primera 12:00 PM" in texto
    assert "Haiti Bolet 9:30 AM" in texto
    assert texto.count("·") >= 40


def test_el_reloj_se_lee_desde_postgresql(entorno, fijar_hora):
    from apps.api.models import Importacion

    base = datetime(2026, 11, 14, 12, 0)
    fijar_hora(base)
    db = dbmod.nueva_sesion()
    assert resultados_auto.estado_reloj(db, base)["reloj"] == "DETENIDO"
    db.add(Importacion(
        fuente="conectate", url="https://api.conectate.com.do/conectate/api/widget",
        fecha_objetivo=base.date(), ok=True, detalle="ok", creado_en=base,
    ))
    db.commit()
    assert resultados_auto.estado_reloj(db, base)["reloj"] == "ACTIVO"
    assert resultados_auto.estado_reloj(db, base.replace(minute=10))["reloj"] == "RETRASADO"
    assert resultados_auto.estado_reloj(db, base.replace(minute=30))["reloj"] == "DETENIDO"
    db.add(Importacion(
        fuente="conectate", url="https://api.conectate.com.do/conectate/api/widget",
        fecha_objetivo=base.date(), ok=False, detalle="HTTP 403", creado_en=base.replace(minute=31),
    ))
    db.commit()
    marca = resultados_auto.estado_reloj(db, base.replace(minute=32))
    assert marca["reloj"] == "ERROR"
    assert "403" in marca["ultimo_error"]
    db.close()


def test_dos_procesos_no_registran_dos_lecturas(entorno):
    payload = [_item("La Primera Día", (19, 3, 45))]
    primero = resultados_auto.ciclo(payload=payload)
    segundo = resultados_auto.ciclo(payload=[_item("La Primera Día", (19, 3, 45))])
    assert primero["ok"] is True and primero.get("omitido") is None
    assert segundo["omitido"] == "otra consulta ya corrió en este intervalo"
    db = dbmod.nueva_sesion()
    from apps.api.models import ObservacionResultado
    assert db.query(ObservacionResultado).one().lecturas == 1
    db.close()
