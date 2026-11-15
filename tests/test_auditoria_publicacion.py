"""Auditoría previa a publicar: base aislada, sin PostgreSQL de producción."""
import sqlite3
import threading
from datetime import datetime
from multiprocessing import get_context

from apps.api import db as dbmod
from apps.api import resultados_auto, servicios
from apps.api.comun import ErrorServicio
from apps.api.models import Jugada, ObservacionResultado, Sucursal, Ticket, Usuario


def _pasada_paralela(url):
    """Una pasada en otro proceso, contra la misma base de esta prueba."""
    from apps.api import db as dbmod
    from apps.api import resultados_auto, servicios

    dbmod.configurar(url)
    servicios.ahora_local = lambda: datetime(2026, 11, 14, 12, 0)
    return resultados_auto.ciclo(
        forzar=True,
        payload=[{"game_title": "La Primera Día", "date": "14-11", "score": ["19", "3", "45"]}],
    )


def test_el_alter_agrega_columnas_y_no_toca_filas_ni_saldos(tmp_path):
    ruta = tmp_path / "antes.db"
    con = sqlite3.connect(ruta)
    con.execute(
        "CREATE TABLE jugadas (id INTEGER PRIMARY KEY, ticket_id INTEGER, monto TEXT, premio TEXT)"
    )
    con.execute(
        "INSERT INTO jugadas (id, ticket_id, monto, premio) VALUES (2, 2, '600.00', '600.00')"
    )
    con.execute("CREATE TABLE sucursales (id INTEGER PRIMARY KEY, saldo_actual TEXT)")
    con.execute("INSERT INTO sucursales (id, saldo_actual) VALUES (1, '5764.00')")
    con.commit()
    for sql in (
        "ALTER TABLE jugadas ADD COLUMN pagada INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE jugadas ADD COLUMN pagado_en TIMESTAMP",
        "ALTER TABLE jugadas ADD COLUMN pagado_por_usuario_id INTEGER",
        "ALTER TABLE jugadas ADD COLUMN pago_operacion_id VARCHAR(40)",
    ):
        con.execute(sql)
    con.commit()
    fila = con.execute(
        "SELECT ticket_id, monto, premio, pagada, pagado_en, pagado_por_usuario_id, pago_operacion_id "
        "FROM jugadas WHERE id = 2"
    ).fetchone()
    saldo = con.execute("SELECT saldo_actual FROM sucursales WHERE id = 1").fetchone()[0]
    con.close()
    assert fila == (2, "600.00", "600.00", 0, None, None, None)
    assert saldo == "5764.00"


def test_init_db_no_cambia_un_saldo_ya_guardado(entorno, monkeypatch):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    b = entorno.banca(saldo=5764)
    antes = entorno.saldo(b["sucursal"]["id"])
    dbmod.init_db()
    assert entorno.saldo(b["sucursal"]["id"]) == antes == 5764


def test_el_premio_pendiente_no_sale_de_caja_hasta_el_pago(entorno, monkeypatch):
    monkeypatch.delenv("MODO_DESARROLLO", raising=False)
    b = entorno.banca(saldo=100000)
    loteria = entorno.sorteo_id("LOTEDOM")
    ticket = entorno.vender_ok(b["headers"], [
        {"tipo": "QN", "sorteos": [loteria], "numeros": "25", "monto": 10},
    ])
    despues_de_vender = entorno.saldo(b["sucursal"]["id"])
    entorno.liquidar(loteria, 25, 54, 78)
    consulta = entorno.consultar(ticket)
    assert consulta["estado"] == "ganador"
    assert consulta["premio_total"] == "600.00"
    assert consulta["puede_pagar"] is True
    assert entorno.saldo(b["sucursal"]["id"]) == despues_de_vender
    pago = entorno.c.post("/terminal/tickets/pagar", json={
        "id": ticket["id"], "serial": ticket["serial"], "operacion_id": "pago-real-1",
    }, headers=b["headers"])
    assert pago.status_code == 200, pago.text
    assert entorno.saldo(b["sucursal"]["id"]) == despues_de_vender - 600
    otra = entorno.c.post("/terminal/tickets/pagar", json={
        "id": ticket["id"], "serial": ticket["serial"], "operacion_id": "pago-real-2",
    }, headers=b["headers"])
    assert otra.status_code == 409
    assert entorno.saldo(b["sucursal"]["id"]) == despues_de_vender - 600


def test_dos_cajeros_reales_descuentan_una_sola_vez(entorno, monkeypatch):
    monkeypatch.delenv("MODO_DESARROLLO", raising=False)
    b = entorno.banca(saldo=100000, usuario="caja1", clave="1234")
    otra = entorno.operador("caja2", "1234", b["sucursal"]["id"])
    loteria = entorno.sorteo_id("LOTEDOM")
    ticket = entorno.vender_ok(b["headers"], [
        {"tipo": "QN", "sorteos": [loteria], "numeros": "25", "monto": 10},
    ])
    entorno.liquidar(loteria, 25, 54, 78)
    antes = entorno.saldo(b["sucursal"]["id"])
    db = dbmod.nueva_sesion()
    cajeros = [fila.id for fila in db.query(Usuario).filter(Usuario.usuario.in_(("caja1", "caja2")))]
    db.close()
    assert len(cajeros) == 2 and otra["usuario"] == "caja2"
    resultados = []
    barrera = threading.Barrier(2)

    def intento(usuario_id):
        sesion = dbmod.nueva_sesion()
        try:
            barrera.wait(timeout=10)
            servicios.pagar_ticket(
                sesion, ticket["id"], ticket["serial"], b["sucursal"]["id"], None, usuario_id,
            )
            resultados.append("ok")
        except ErrorServicio as exc:
            resultados.append(exc.status)
        finally:
            sesion.close()

    hilos = [threading.Thread(target=intento, args=(cajeros[0],)),
             threading.Thread(target=intento, args=(cajeros[1],))]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join(timeout=30)
    assert resultados.count("ok") == 1 and resultados.count(409) == 1, resultados
    assert entorno.saldo(b["sucursal"]["id"]) == antes - 600


def test_un_premio_pagado_sigue_pagado_al_abrir_otra_sesion(entorno, monkeypatch):
    monkeypatch.delenv("MODO_DESARROLLO", raising=False)
    b = entorno.banca()
    loteria = entorno.sorteo_id("LOTEDOM")
    ticket = entorno.vender_ok(b["headers"], [
        {"tipo": "QN", "sorteos": [loteria], "numeros": "25", "monto": 10},
    ])
    entorno.liquidar(loteria, 25, 54, 78)
    pago = entorno.c.post("/terminal/tickets/pagar", json={
        "id": ticket["id"], "serial": ticket["serial"], "operacion_id": "pago-reinicio",
    }, headers=b["headers"])
    assert pago.status_code == 200, pago.text
    saldo = entorno.saldo(b["sucursal"]["id"])
    dbmod.engine().dispose()
    db = dbmod.nueva_sesion()
    guardado = db.get(Ticket, ticket["id"])
    jugada = db.query(Jugada).filter_by(ticket_id=ticket["id"]).one()
    assert guardado.estado == "pagado" and jugada.pagada is True
    db.close()
    consulta = entorno.consultar(ticket)
    assert consulta["puede_pagar"] is False
    assert consulta["premio_pendiente"] == "0.00"
    assert consulta["veredicto"] == "TICKET YA PAGADO"
    repetido = entorno.c.post("/terminal/tickets/pagar", json={
        "id": ticket["id"], "serial": ticket["serial"], "operacion_id": "pago-reinicio-2",
    }, headers=b["headers"])
    assert repetido.status_code == 409
    assert entorno.saldo(b["sucursal"]["id"]) == saldo


def test_un_ticket_pagado_con_el_codigo_viejo_no_vuelve_a_pendiente(entorno, monkeypatch):
    monkeypatch.delenv("MODO_DESARROLLO", raising=False)
    b = entorno.banca(saldo=100000)
    loteria = entorno.sorteo_id("LOTEDOM")
    ticket = entorno.vender_ok(b["headers"], [
        {"tipo": "QN", "sorteos": [loteria], "numeros": "25", "monto": 10},
    ])
    entorno.liquidar(loteria, 25, 54, 78)
    db = dbmod.nueva_sesion()
    guardado = db.get(Ticket, ticket["id"])
    guardado.estado = "pagado"
    guardado.pagado_en = datetime(2026, 11, 14, 11, 0)
    guardado.pagado_en_sucursal_id = b["sucursal"]["id"]
    guardado.pagado_por_usuario_id = db.query(Usuario).filter_by(usuario="vend1").one().id
    jugada = db.query(Jugada).filter_by(ticket_id=ticket["id"]).one()
    jugada.pagada = False
    jugada.pagado_en = None
    db.commit()
    db.close()
    saldo = entorno.saldo(b["sucursal"]["id"])
    consulta = entorno.consultar(ticket)
    assert consulta["estado"] == "pagado"
    assert consulta["puede_pagar"] is False
    assert consulta["premio_pendiente"] == "0.00"
    assert consulta["veredicto"] == "TICKET YA PAGADO"
    pago = entorno.c.post("/terminal/tickets/pagar", json={
        "id": ticket["id"], "serial": ticket["serial"], "operacion_id": "viejo-otra-vez",
    }, headers=b["headers"])
    assert pago.status_code == 409
    assert entorno.saldo(b["sucursal"]["id"]) == saldo


def test_las_lecturas_firmadas_siguen_despues_de_cerrar_la_sesion(entorno, fijar_hora):
    firmado = {
        "firma": True,
        "anguila": {"siteGames": [{
            "title": "Anguila 11:00 AM", "game_id": "g11",
            "game": {"sessions": [{"date": "2026-11-14T04:00:00.000Z", "score": ["11", "22", "33"]}]},
        }]},
        "senuelo_anguila": {"siteGames": [{
            "title": "Anguila 11:00 AM", "game_id": "s11",
            "game": {"sessions": [{"date": "2026-11-14T04:00:00.000Z", "score": ["01", "02", "03"]}]},
        }]},
        "haiti": {"siteGames": []},
        "senuelo_haiti": {"siteGames": []},
    }
    base = datetime(2026, 11, 14, 10, 0)
    operador = {
        "La Anguila 11:00 AM": {
            "fecha": base.date(), "numeros": (11, 22, 33),
        },
    }
    for minuto in (0, 4):
        fijar_hora(base.replace(minute=minuto))
        resultados_auto.ciclo(forzar=True, payload=[], firmado=firmado, operador=operador)
        dbmod.engine().dispose()
    db = dbmod.nueva_sesion()
    sorteo_id = entorno.sorteo_id("La Anguila 11:00 AM")
    obs = db.query(ObservacionResultado).filter_by(sorteo_id=sorteo_id).one()
    assert obs.lecturas == 2 and (obs.premio1, obs.premio2, obs.premio3) == (11, 22, 33)
    db.close()
    fijar_hora(base.replace(minute=10))
    final = resultados_auto.ciclo(forzar=True, payload=[], firmado=firmado, operador=operador)
    assert final["confirmados"] == 1
    db = dbmod.nueva_sesion()
    fila = db.query(ObservacionResultado).filter_by(sorteo_id=sorteo_id).one()
    assert fila.lecturas == 3
    db.close()


def test_dos_procesos_no_confirman_dos_lecturas_en_la_misma_pasada(entorno):
    url = dbmod.engine().url.render_as_string(hide_password=False)
    ctx = get_context("spawn")
    with ctx.Pool(2) as pool:
        salidas = pool.map(_pasada_paralela, [url, url])
    db = dbmod.nueva_sesion()
    total = sum(fila.lecturas for fila in db.query(ObservacionResultado))
    db.close()
    omitidas = [salida for salida in salidas if salida.get("omitido")]
    assert total <= 1
    assert len(omitidas) >= 1 or total == 1


def test_modo_desarrollo_no_mueve_la_caja_real_ni_premia_un_ticket_real(entorno, monkeypatch):
    monkeypatch.delenv("MODO_DESARROLLO", raising=False)
    b = entorno.banca(saldo=5000)
    loteria = entorno.sorteo_id("LOTEDOM")
    real = entorno.vender_ok(b["headers"], [
        {"tipo": "QN", "sorteos": [loteria], "numeros": "25", "monto": 10},
    ])
    assert real["es_prueba"] is False
    saldo_real = entorno.saldo(b["sucursal"]["id"])
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    prueba = entorno.vender_ok(b["headers"], [
        {"tipo": "QN", "sorteos": [loteria], "numeros": "25", "monto": 10},
    ])
    assert prueba["es_prueba"] is True
    assert entorno.saldo(b["sucursal"]["id"]) == saldo_real
    simulado = entorno.c.post("/resultados", json={
        "sorteo_id": loteria, "fecha": "2026-11-14",
        "premio1": 25, "premio2": 54, "premio3": 78, "simulado": True,
    }, headers=entorno.admin)
    assert simulado.status_code == 201, simulado.text
    assert entorno.consultar(real)["estado"] == "vendido"
    assert entorno.consultar(prueba)["estado"] == "ganador"
    assert entorno.saldo(b["sucursal"]["id"]) == saldo_real
    monkeypatch.delenv("MODO_DESARROLLO", raising=False)
    bloqueado = entorno.c.post("/resultados", json={
        "sorteo_id": loteria, "fecha": "2026-11-14",
        "premio1": 1, "premio2": 2, "premio3": 3, "simulado": True,
    }, headers=entorno.admin)
    assert bloqueado.status_code == 403


def test_la_sunmi_0310_sigue_recibiendo_sus_campos(entorno, monkeypatch):
    monkeypatch.delenv("MODO_DESARROLLO", raising=False)
    b = entorno.banca()
    loteria = entorno.sorteo_id("LOTEDOM")
    ticket = entorno.vender_ok(b["headers"], [
        {"tipo": "QN", "sorteos": [loteria], "numeros": "25", "monto": 10},
        {"tipo": "QN", "sorteos": [loteria], "numeros": "99", "monto": 5},
    ])
    entorno.liquidar(loteria, 25, 54, 78)
    consulta = entorno.c.post("/terminal/tickets/consultar", json={
        "id": ticket["id"], "serial": ticket["serial"],
    }, headers=b["headers"]).json()
    for campo in ("puede_pagar", "premio_total", "veredicto", "jugadas", "estado", "mensaje"):
        assert campo in consulta
    assert consulta["puede_pagar"] is True
    assert consulta["premio_total"] == "600.00"
    assert consulta["veredicto"].startswith("TICKET GANADOR")
    assert len(consulta["jugadas"]) == 2
    caja = entorno.c.get("/terminal/sorteos", headers=b["headers"]).json()
    assert caja["mi_caja"] == "15.00"
    assert caja["recaudacion_ciclo"] == "15.00"
    pago = entorno.c.post("/terminal/tickets/pagar", json={
        "id": ticket["id"], "serial": ticket["serial"], "operacion_id": "pago-sunmi",
    }, headers=b["headers"])
    assert pago.status_code == 200, pago.text
    assert "comprobante" in pago.json()
    assert "PREMIO PAGADO" in pago.json()["comprobante"]
    despues = entorno.c.get("/terminal/sorteos", headers=b["headers"]).json()
    assert despues["mi_caja"] == "-585.00"
    assert despues["recaudacion_ciclo"] == "-585.00"


def test_un_pago_parcial_quedaria_inconsistente_si_se_revierte_el_codigo(entorno, monkeypatch):
    monkeypatch.delenv("MODO_DESARROLLO", raising=False)
    b = entorno.banca(saldo=100000)
    primera = entorno.sorteo_id("La Primera 12")
    florida = entorno.sorteo_id("Florida Día")
    ticket = entorno.vender_ok(b["headers"], [
        {"tipo": "QN", "sorteos": [primera], "numeros": "25", "monto": 10},
        {"tipo": "QN", "sorteos": [florida], "numeros": "25", "monto": 10},
    ])
    entorno.liquidar(primera, 25, 1, 2)
    antes = entorno.saldo(b["sucursal"]["id"])
    pago = entorno.c.post("/terminal/tickets/pagar", json={
        "id": ticket["id"], "serial": ticket["serial"], "operacion_id": "parcial",
    }, headers=b["headers"])
    assert pago.status_code == 200, pago.text
    assert entorno.saldo(b["sucursal"]["id"]) == antes - 600
    entorno.liquidar(florida, 25, 3, 4)
    consulta = entorno.consultar(ticket)
    assert consulta["estado"] == "parcial"
    assert consulta["premio_total"] == "1200.00"
    assert consulta["premio_pendiente"] == "600.00"
    assert consulta["importe_a_cobrar"] == "600.00"
