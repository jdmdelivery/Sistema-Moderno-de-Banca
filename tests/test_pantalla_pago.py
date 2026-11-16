"""La consulta de pago muestra solo las jugadas que ganaron y cobra ese total una vez."""
import threading

from apps.api import db as dbmod
from apps.api import servicios
from apps.api.comun import ErrorServicio
from apps.api.models import TipoJugada


def _simular(entorno, sorteo_id, p1, p2, p3):
    r = entorno.c.post("/resultados", json={
        "sorteo_id": sorteo_id, "fecha": "2026-11-14",
        "premio1": p1, "premio2": p2, "premio3": p3, "simulado": True,
    }, headers=entorno.admin)
    assert r.status_code == 201, r.text


def _consultar(entorno, headers, ticket):
    r = entorno.c.post("/terminal/tickets/consultar", json={
        "id": ticket["id"], "serial": ticket["serial"],
    }, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _preparar(entorno):
    b = entorno.banca(saldo=5764, nombre="BANCA CASTILLO (PRUEBA)", usuario="0219", clave="prueba123")
    jose = next(f for f in entorno.c.get("/usuarios", headers=entorno.admin).json() if f["usuario"] == "0219")
    fondo = entorno.c.post("/fondos", json={
        "sucursal_id": b["sucursal"]["id"], "usuario_id": jose["id"], "monto": 20000,
        "tipo": "aporte_prueba", "operacion_id": "fondo-pantalla",
    }, headers=entorno.admin)
    assert fondo.status_code == 201, fondo.text
    return b


def test_tripleta_esta_activa_y_vende(entorno):
    db = dbmod.nueva_sesion()
    codigos = {fila.codigo for fila in db.query(TipoJugada).all()}
    db.close()
    assert codigos == {"QN", "PL", "SP", "TR"}
    b = entorno.banca()
    sorteo = entorno.sorteo_id("LOTEDOM")
    r = entorno.c.post("/terminal/venta", json={"jugadas": [
        {"tipo": "TR", "sorteos": [sorteo], "numeros": "01-02-03", "monto": 5},
    ]}, headers=b["headers"])
    assert r.status_code == 201, r.text
    assert r.json()["jugadas"][0]["tipo"] == "TR"
    assert r.json()["jugadas"][0]["numeros"] == "01-02-03"


def test_una_loteria_muestra_el_premio_y_oculta_la_perdedora(entorno, monkeypatch):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    b = _preparar(entorno)
    loteria = entorno.sorteo_id("LOTEDOM")
    ticket = entorno.vender_ok(b["headers"], [
        {"tipo": "QN", "sorteos": [loteria], "numeros": "25", "monto": 10},
        {"tipo": "QN", "sorteos": [loteria], "numeros": "99", "monto": 10},
    ])
    _simular(entorno, loteria, 25, 54, 78)
    consulta = _consultar(entorno, b["headers"], ticket)
    assert consulta["puede_pagar"] is True
    assert consulta["premio_pendiente"] == "600.00"
    assert "QUINIELA" in consulta["texto_pago"]
    assert "Lotería: Lotedom 12:00 PM" in consulta["texto_pago"]
    assert "Número ganador: 25-54-78" in consulta["texto_pago"]
    assert "Número: 25" in consulta["texto_pago"]
    assert "Premio: RD$600.00" in consulta["texto_pago"]
    assert "Monto jugado: $10.00" in consulta["texto_pago"]
    assert "Estado: GANADOR" in consulta["texto_pago"]
    # La perdedora 99 no se lista; Lotedom sí ganó con 25.
    assert "Jugada: 99" not in consulta["texto_pago"]
    assert "Número: 99" not in consulta["texto_pago"]
    assert "EMPRESA: BANCA CASTILLO (PRUEBA)" in consulta["texto_pago"]


def test_dos_loterias_y_pale_se_listan_aparte_y_se_cobran_juntos(entorno, monkeypatch):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    b = _preparar(entorno)
    lotedom = entorno.sorteo_id("LOTEDOM")
    primera = entorno.sorteo_id("La Primera 12")
    ticket = entorno.vender_ok(b["headers"], [
        {"tipo": "QN", "sorteos": [lotedom], "numeros": "25", "monto": 10},
        {"tipo": "PL", "sorteos": [primera], "numeros": "19-03", "monto": 5},
        {"tipo": "QN", "sorteos": [primera], "numeros": "77", "monto": 5},
    ])
    _simular(entorno, lotedom, 25, 54, 78)
    _simular(entorno, primera, 19, 3, 45)
    consulta = _consultar(entorno, b["headers"], ticket)
    assert consulta["premio_pendiente"] == "6600.00"
    assert "Lotería: Lotedom 12:00 PM" in consulta["texto_pago"]
    assert "Lotería: La Primera 12:00 PM" in consulta["texto_pago"]
    assert "PALÉ" in consulta["texto_pago"]
    assert "Jugada: 77" not in consulta["texto_pago"]
    assert "Número: 77" not in consulta["texto_pago"]
    antes = float(_consultar(entorno, b["headers"], ticket) and entorno.c.get(
        "/terminal/sorteos", headers=b["headers"]).json()["mi_caja"])
    pago = entorno.c.post("/terminal/tickets/pagar", json={
        "id": ticket["id"], "serial": ticket["serial"], "operacion_id": "pago-dos",
    }, headers=b["headers"])
    assert pago.status_code == 200, pago.text
    cuerpo = pago.json()
    assert cuerpo["estado"] == "pagado"
    assert cuerpo["puede_pagar"] is False
    assert float(cuerpo["mi_caja"]) == antes - 6600
    assert "PREMIO PAGADO: RD$6600.00" in cuerpo["comprobante"]
    copia = _consultar(entorno, b["headers"], ticket)
    assert copia["comprobante"] == cuerpo["comprobante"]
    assert copia["puede_pagar"] is False
    otra = entorno.c.post("/terminal/tickets/pagar", json={
        "id": ticket["id"], "serial": ticket["serial"], "operacion_id": "pago-dos-copia",
    }, headers=b["headers"])
    assert otra.status_code == 409
    assert float(entorno.c.get("/terminal/sorteos", headers=b["headers"]).json()["mi_caja"]) == antes - 6600


def test_tres_loterias_cobra_las_listas_y_deja_la_pendiente(entorno, monkeypatch):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    b = _preparar(entorno)
    lotedom = entorno.sorteo_id("LOTEDOM")
    primera = entorno.sorteo_id("La Primera 12")
    florida = entorno.sorteo_id("Florida Día")
    ticket = entorno.vender_ok(b["headers"], [
        {"tipo": "QN", "sorteos": [lotedom, primera, florida], "numeros": "25", "monto": 10},
    ])
    _simular(entorno, lotedom, 25, 1, 2)
    _simular(entorno, primera, 25, 3, 4)
    consulta = _consultar(entorno, b["headers"], ticket)
    assert consulta["estado"] == "ganador"
    assert consulta["puede_pagar"] is True
    assert consulta["premio_pendiente"] == "1200.00"
    assert "SORTEOS PENDIENTES" in consulta["texto_pago"]
    assert "Florida 2:30 PM" in consulta["texto_pago"]
    assert "Esos sorteos no se pagan todavía" in consulta["texto_pago"]
    assert "No se usan resultados de otros días" in consulta["texto_pago"]
    caja = entorno.c.get("/terminal/sorteos", headers=b["headers"]).json()
    antes = float(caja["mi_caja"])
    assert float(caja["premios_por_pagar"]) == 1200.00
    parcial = entorno.c.post("/terminal/tickets/pagar", json={
        "id": ticket["id"], "serial": ticket["serial"], "operacion_id": "pago-parcial",
    }, headers=b["headers"])
    assert parcial.status_code == 200, parcial.text
    assert parcial.json()["estado"] == "parcial"
    assert float(parcial.json()["mi_caja"]) == antes - 1200
    assert float(parcial.json()["premios_por_pagar"]) == 0.00
    anulacion = entorno.c.post("/terminal/tickets/anular", json={
        "id": ticket["id"], "serial": ticket["serial"], "motivo": "despues del pago",
    }, headers=b["headers"])
    assert anulacion.status_code == 409
    assert parcial.json()["premio_pendiente"] == "0.00"
    assert parcial.json()["premio_pagado"] == "1200.00"
    assert parcial.json()["puede_pagar"] is False
    assert "PAGO PARCIAL" in parcial.json()["comprobante"]
    espera = _consultar(entorno, b["headers"], ticket)
    assert espera["puede_pagar"] is False
    assert espera["premio_pendiente"] == "0.00"
    assert "PREMIO PAGADO — QUEDAN SORTEOS PENDIENTES" in espera["texto_pago"]
    assert "PENDIENTE DE SORTEO" in espera["texto_pago"]
    assert "Florida" in espera["texto_pago"]
    assert "SE COBRARÁ" not in espera["texto_pago"]
    repetido = entorno.c.post("/terminal/tickets/pagar", json={
        "id": ticket["id"], "serial": ticket["serial"], "operacion_id": "pago-parcial",
    }, headers=b["headers"])
    assert repetido.status_code == 200, repetido.text
    assert float(repetido.json()["mi_caja"]) == antes - 1200
    bloqueado = entorno.c.post("/terminal/tickets/pagar", json={
        "id": ticket["id"], "serial": ticket["serial"], "operacion_id": "pago-sin-resultado",
    }, headers=b["headers"])
    assert bloqueado.status_code == 409
    assert float(entorno.c.get("/terminal/sorteos", headers=b["headers"]).json()["mi_caja"]) == antes - 1200
    _simular(entorno, florida, 25, 8, 9)
    resto = _consultar(entorno, b["headers"], ticket)
    assert resto["puede_pagar"] is True
    assert resto["premio_pendiente"] == "600.00"
    assert resto["premio_pagado"] == "1200.00"
    assert "Estado: PAGADO" in resto["texto_pago"]
    assert "Estado: GANADOR" in resto["texto_pago"]
    assert "TOTAL NUEVO POR PAGAR: RD$600.00" in resto["texto_pago"]
    final = entorno.c.post("/terminal/tickets/pagar", json={
        "id": ticket["id"], "serial": ticket["serial"], "operacion_id": "pago-resto",
    }, headers=b["headers"])
    assert final.status_code == 200, final.text
    assert final.json()["estado"] == "pagado"
    assert final.json()["puede_pagar"] is False
    assert final.json()["premio_pendiente"] == "0.00"
    assert float(final.json()["mi_caja"]) == antes - 1800
    assert "Florida 2:30 PM" in final.json()["comprobante"]
    cerrado = _consultar(entorno, b["headers"], ticket)
    assert cerrado["puede_pagar"] is False
    assert cerrado["veredicto"] == "ESTE TICKET YA SE PAGÓ"
    assert "ESTE TICKET YA SE PAGÓ" in cerrado["texto_pago"]
    assert "TOTAL PREMIOS PAGADOS: RD$1800.00" in cerrado["texto_pago"]
    assert "SE COBRARÁ" not in cerrado["texto_pago"]
    assert "Estado: PAGADO" in cerrado["texto_pago"]
    assert cerrado.get("comprobante")
    # Reimprimir no vuelve a cobrar.
    caja_final = float(entorno.c.get("/terminal/sorteos", headers=b["headers"]).json()["mi_caja"])
    assert caja_final == antes - 1800
    otra = entorno.c.post("/terminal/tickets/pagar", json={
        "id": ticket["id"], "serial": ticket["serial"], "operacion_id": "pago-ya-cerrado",
    }, headers=b["headers"])
    assert otra.status_code == 409
    assert float(entorno.c.get("/terminal/sorteos", headers=b["headers"]).json()["mi_caja"]) == caja_final


def test_super_pale_usa_el_primer_premio_de_cada_loteria(entorno, monkeypatch):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    b = _preparar(entorno)
    ny = entorno.sorteo_id("NY Tarde")
    nacional = entorno.sorteo_id("Nacional Tarde")
    ticket = entorno.vender_ok(b["headers"], [
        {"tipo": "SP", "sorteos": [ny, nacional], "numeros": "12-38", "monto": 5},
    ])
    _simular(entorno, ny, 12, 1, 2)
    _simular(entorno, nacional, 38, 11, 22)
    consulta = _consultar(entorno, b["headers"], ticket)
    assert consulta["premio_pendiente"] == "12500.00"
    assert "SÚPER PALÉ" in consulta["texto_pago"]
    assert "New York 3:30 PM" in consulta["texto_pago"]
    assert "Lotería Nacional 2:30 PM" in consulta["texto_pago"]
    assert "Número ganador: 12-01-02 · 38-11-22" in consulta["texto_pago"]


def test_sin_premio_anulado_y_ajeno_no_cobran(entorno, monkeypatch):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    b = _preparar(entorno)
    loteria = entorno.sorteo_id("LOTEDOM")
    perdedor = entorno.vender_ok(b["headers"], [
        {"tipo": "QN", "sorteos": [loteria], "numeros": "99", "monto": 10},
    ])
    anulado = entorno.vender_ok(b["headers"], [
        {"tipo": "QN", "sorteos": [loteria], "numeros": "25", "monto": 10},
    ])
    baja = entorno.c.post("/terminal/tickets/anular", json={
        "id": anulado["id"], "serial": anulado["serial"], "motivo": "prueba",
    }, headers=b["headers"])
    assert baja.status_code == 200, baja.text
    _simular(entorno, loteria, 25, 54, 78)
    sin_premio = _consultar(entorno, b["headers"], perdedor)
    assert sin_premio["puede_pagar"] is False
    assert sin_premio["texto_pago"].startswith("PRUEBA — NO OFICIAL\nEMPRESA:")
    assert "TICKET FINALIZADO — SIN PREMIOS" in sin_premio["texto_pago"]
    assert "CONFIRMAR PAGO" not in sin_premio["texto_pago"]
    assert "SE COBRARÁ" not in sin_premio["texto_pago"]
    assert "25-54-78" not in sin_premio["texto_pago"]
    pago = entorno.c.post("/terminal/tickets/pagar", json={
        "id": perdedor["id"], "serial": perdedor["serial"],
    }, headers=b["headers"])
    assert pago.status_code == 409
    anulado_vista = _consultar(entorno, b["headers"], anulado)
    assert "TICKET ANULADO" in anulado_vista["texto_pago"]
    assert anulado_vista["puede_pagar"] is False
    otra = entorno.banca(saldo=5000, codigo="2200", nombre="OTRA BANCA", usuario="ana", clave="prueba123")
    ajena = _consultar(entorno, otra["headers"], perdedor)
    assert "BANCA CASTILLO (PRUEBA)" in ajena["texto_pago"]
    assert ajena["puede_pagar"] is False


def test_dos_cajeros_no_cobran_el_mismo_premio(entorno, monkeypatch):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    b = _preparar(entorno)
    loteria = entorno.sorteo_id("LOTEDOM")
    ticket = entorno.vender_ok(b["headers"], [
        {"tipo": "QN", "sorteos": [loteria], "numeros": "25", "monto": 10},
    ])
    _simular(entorno, loteria, 25, 54, 78)
    jose = next(f for f in entorno.c.get("/usuarios", headers=entorno.admin).json() if f["usuario"] == "0219")
    resultados = []
    barrera = threading.Barrier(2)

    def intento():
        db = dbmod.nueva_sesion()
        try:
            barrera.wait(timeout=10)
            servicios.pagar_ticket(
                db, ticket["id"], ticket["serial"], b["sucursal"]["id"], None, jose["id"],
            )
            resultados.append("ok")
        except ErrorServicio as exc:
            resultados.append(exc.status)
        finally:
            db.close()

    hilos = [threading.Thread(target=intento), threading.Thread(target=intento)]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join(timeout=30)
    assert resultados.count("ok") == 1, resultados
    assert resultados.count(409) == 1, resultados
    caja = entorno.c.get("/terminal/sorteos", headers=b["headers"]).json()
    assert caja["mi_caja"] == "19410.00"
    assert caja["diferencia"] == "0.00"
