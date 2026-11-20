"""Pago de premios con MI CAJA insuficiente → deuda contable (local).

No toca Render ni PostgreSQL de producción. No genera ajuste automático.
"""
import threading

from apps.api import db as dbmod
from apps.api import servicios
from apps.api.comun import ErrorServicio
from apps.api.models import Usuario


def _cajera(entorno, usuario):
    for fila in entorno.c.get("/usuarios", headers=entorno.admin).json():
        if fila["usuario"] == usuario:
            return fila
    raise AssertionError(usuario)


def _poner_mi_caja(usuario_login, monto):
    db = dbmod.nueva_sesion()
    try:
        u = db.query(Usuario).filter_by(usuario=usuario_login).first()
        assert u is not None
        u.saldo_caja_prueba = monto
        db.commit()
    finally:
        db.close()


def _mi_caja(entorno, headers):
    return float(entorno.c.get("/terminal/sorteos", headers=headers).json()["mi_caja"])


def _simular(entorno, sorteo_id, p1, p2, p3, fecha="2026-11-14"):
    r = entorno.c.post(
        "/resultados",
        json={
            "sorteo_id": sorteo_id, "fecha": fecha,
            "premio1": p1, "premio2": p2, "premio3": p3, "simulado": True,
        },
        headers=entorno.admin,
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_flujo_completo_deuda_y_ajustes(entorno, monkeypatch):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    b = entorno.banca(saldo=50000, usuario="eli", clave="prueba123")
    headers = b["headers"]
    lotedom = entorno.sorteo_id("LOTEDOM")
    ticket = entorno.vender_ok(
        headers, [{"tipo": "QN", "sorteos": [lotedom], "numeros": "25", "monto": 50}],
    )
    _poner_mi_caja("eli", 2000)
    _simular(entorno, lotedom, 25, 11, 22)
    general = entorno.saldo(b["sucursal"]["id"])

    cons = entorno.c.post(
        "/terminal/tickets/consultar",
        json={"id": ticket["id"], "serial": ticket["serial"]},
        headers=headers,
    ).json()
    assert cons["puede_pagar"] is True
    assert float(cons["premio_pendiente"]) == 3000
    assert float(cons["mi_caja"]) == 2000
    assert cons["premio_excede_mi_caja"] is True
    assert float(cons["mi_caja_despues_si_paga"]) == -1000

    pago = entorno.c.post(
        "/terminal/tickets/pagar",
        json={"id": ticket["id"], "serial": ticket["serial"], "operacion_id": "pago-neg-1"},
        headers=headers,
    )
    assert pago.status_code == 200, pago.text
    assert float(pago.json()["mi_caja"]) == -1000
    assert pago.json()["deuda_contable"] is True
    assert _mi_caja(entorno, headers) == -1000
    assert entorno.saldo(b["sucursal"]["id"]) == general

    cc = entorno.c.get("/control-cajeros?desde=2026-11-14&hasta=2026-11-14", headers=entorno.admin)
    assert cc.status_code == 200
    eli = next(c for c in cc.json()["cajeros"] if c["usuario"] == "eli")
    assert eli["estado"] == "deuda"
    assert float(eli["balance_real"]) == -1000
    assert eli["puede_ajustar"] is True
    assert entorno.c.get("/control-cajeros/ajustes", headers=entorno.admin).json() == []

    eli_id = _cajera(entorno, "eli")["id"]
    parcial = entorno.c.post("/control-cajeros/ajuste", json={
        "usuario_id": eli_id, "monto": 400, "motivo": "Ajuste parcial banca negativa",
        "operacion_id": "aj-neg-parcial", "balance_visto": -1000,
    }, headers=entorno.admin)
    assert parcial.status_code == 201, parcial.text
    assert float(parcial.json()["balance_posterior"]) == -600
    assert _mi_caja(entorno, headers) == -600
    assert entorno.saldo(b["sucursal"]["id"]) == general

    completo = entorno.c.post("/control-cajeros/ajuste", json={
        "usuario_id": eli_id, "monto": 600, "motivo": "Ajuste de banca negativa.",
        "operacion_id": "aj-neg-completo", "balance_visto": -600,
    }, headers=entorno.admin)
    assert completo.status_code == 201, completo.text
    assert float(completo.json()["balance_posterior"]) == 0
    assert _mi_caja(entorno, headers) == 0
    assert entorno.saldo(b["sucursal"]["id"]) == general

    exceso = entorno.c.post("/control-cajeros/ajuste", json={
        "usuario_id": eli_id, "monto": 1, "motivo": "No aplica",
        "operacion_id": "aj-neg-exceso", "balance_visto": 0,
    }, headers=entorno.admin)
    assert exceso.status_code == 400


def test_confirmacion_servidor_opcional_bloquea_si_se_exige(entorno, monkeypatch):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    b = entorno.banca(saldo=10000, usuario="eli", clave="prueba123")
    lotedom = entorno.sorteo_id("LOTEDOM")
    ticket = entorno.vender_ok(
        b["headers"], [{"tipo": "QN", "sorteos": [lotedom], "numeros": "25", "monto": 10}],
    )
    _simular(entorno, lotedom, 25, 1, 2)
    eli = _cajera(entorno, "eli")
    db = dbmod.nueva_sesion()
    try:
        try:
            servicios.pagar_ticket(
                db, ticket["id"], ticket["serial"], b["sucursal"]["id"], None, eli["id"],
                operacion_id="pago-exige-1",
                confirmar_caja_negativa=False,
                exigir_confirmacion_deuda=True,
            )
            raise AssertionError("debía exigir confirmación")
        except ErrorServicio as e:
            assert e.status == 409
            assert "confirmar_caja_negativa" in e.mensaje
        db.rollback()
        ok = servicios.pagar_ticket(
            db, ticket["id"], ticket["serial"], b["sucursal"]["id"], None, eli["id"],
            operacion_id="pago-exige-2",
            confirmar_caja_negativa=True,
            exigir_confirmacion_deuda=True,
        )
        assert float(ok["mi_caja"]) == -590
    finally:
        db.close()


def test_pago_duplicado_y_concurrente_con_deuda(entorno, monkeypatch):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    b = entorno.banca(saldo=20000, usuario="eli", clave="prueba123")
    lotedom = entorno.sorteo_id("LOTEDOM")
    ticket = entorno.vender_ok(
        b["headers"], [{"tipo": "QN", "sorteos": [lotedom], "numeros": "25", "monto": 10}],
    )
    _poner_mi_caja("eli", 2000)
    _simular(entorno, lotedom, 25, 1, 2)
    eli = _cajera(entorno, "eli")
    general = entorno.saldo(b["sucursal"]["id"])

    r1 = entorno.c.post("/terminal/tickets/pagar", json={
        "id": ticket["id"], "serial": ticket["serial"], "operacion_id": "dup-a",
    }, headers=b["headers"])
    assert r1.status_code == 200
    assert abs(_mi_caja(entorno, b["headers"]) - 1400) < 0.01  # 2000 - 600
    r2 = entorno.c.post("/terminal/tickets/pagar", json={
        "id": ticket["id"], "serial": ticket["serial"], "operacion_id": "dup-b",
    }, headers=b["headers"])
    assert r2.status_code == 409
    assert abs(_mi_caja(entorno, b["headers"]) - 1400) < 0.01
    assert entorno.saldo(b["sucursal"]["id"]) == general

    # Concurrente: mismo ticket, dos sesiones (exactamente un cobro).
    otra_lot = entorno.sorteo_id("La Primera 12")
    t2 = entorno.vender_ok(
        b["headers"], [{"tipo": "QN", "sorteos": [otra_lot], "numeros": "33", "monto": 15}],
    )
    _simular(entorno, otra_lot, 33, 8, 9)
    _poner_mi_caja("eli", 200)
    resultados = []
    barrera = threading.Barrier(2)

    def intento(op):
        db = dbmod.nueva_sesion()
        try:
            barrera.wait(timeout=10)
            servicios.pagar_ticket(
                db, t2["id"], t2["serial"], b["sucursal"]["id"], None, eli["id"],
                operacion_id=op,
            )
            resultados.append("ok")
        except ErrorServicio as e:
            resultados.append(e.status)
        finally:
            db.close()

    hilos = [
        threading.Thread(target=intento, args=("conc-1",)),
        threading.Thread(target=intento, args=("conc-2",)),
    ]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(timeout=15)
    assert resultados.count("ok") == 1, resultados
    assert 409 in resultados, resultados
    assert entorno.saldo(b["sucursal"]["id"]) == general


def test_ticket_anulado_y_otra_cajera(entorno, monkeypatch):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    b = entorno.banca(saldo=10000, usuario="eli", clave="prueba123")
    entorno.operador("ana", "prueba123", b["sucursal"]["id"])
    ana = entorno.login_terminal("ana", "prueba123")
    lotedom = entorno.sorteo_id("LOTEDOM")
    ticket = entorno.vender_ok(
        b["headers"], [{"tipo": "QN", "sorteos": [lotedom], "numeros": "25", "monto": 10}],
    )
    _simular(entorno, lotedom, 25, 1, 2)
    r = entorno.c.post("/terminal/tickets/pagar", json={
        "id": ticket["id"], "serial": ticket["serial"], "operacion_id": "ajena",
    }, headers=ana)
    assert r.status_code == 403
    an = entorno.c.post("/panel/tickets/anular", json={
        "id": ticket["id"], "serial": ticket["serial"], "motivo": "Cliente desistió",
    }, headers=entorno.admin)
    assert an.status_code == 200, an.text
    pago = entorno.c.post("/terminal/tickets/pagar", json={
        "id": ticket["id"], "serial": ticket["serial"], "operacion_id": "post-anul",
    }, headers=b["headers"])
    assert pago.status_code == 409
    assert "anulado" in pago.json()["detail"].lower()
