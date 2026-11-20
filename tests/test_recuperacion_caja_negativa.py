"""Auditoría final: recuperación automática de MI CAJA negativa por ventas + ajustes.

Casos A–G. Solo local (SQLite conftest). No toca Render ni PG de producción.
"""
import threading

from apps.api import db as dbmod
from apps.api import servicios
from apps.api.comun import ErrorServicio
from apps.api.models import AjusteCajaCajera, Usuario


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


def _balance_control(entorno, usuario):
    cc = entorno.c.get("/control-cajeros?desde=2026-11-14&hasta=2026-11-14", headers=entorno.admin)
    assert cc.status_code == 200, cc.text
    fila = next(c for c in cc.json()["cajeros"] if c["usuario"] == usuario)
    return fila


def _vender(entorno, headers, monto, numero="25"):
    sorteo = entorno.sorteo_id("LOTEDOM")
    return entorno.vender_ok(
        headers, [{"tipo": "QN", "sorteos": [sorteo], "numeros": numero, "monto": monto}],
    )


def _simular(entorno, sorteo_id, p1, p2=11, p3=22):
    r = entorno.c.post(
        "/resultados",
        json={
            "sorteo_id": sorteo_id, "fecha": "2026-11-14",
            "premio1": p1, "premio2": p2, "premio3": p3, "simulado": True,
        },
        headers=entorno.admin,
    )
    assert r.status_code == 201, r.text
    return r.json()


# ------------------------------------------------------------------ Caso A
def test_caso_a_recuperacion_por_ventas(entorno, monkeypatch):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    b = entorno.banca(saldo=50000, usuario="eli", clave="prueba123")
    general = entorno.saldo(b["sucursal"]["id"])
    _poner_mi_caja("eli", -1000)
    assert _mi_caja(entorno, b["headers"]) == -1000

    _vender(entorno, b["headers"], 500, "10")
    assert _mi_caja(entorno, b["headers"]) == -500
    fila = _balance_control(entorno, "eli")
    assert fila["estado"] == "deuda" and float(fila["balance_real"]) == -500

    _vender(entorno, b["headers"], 500, "11")
    assert _mi_caja(entorno, b["headers"]) == 0
    fila = _balance_control(entorno, "eli")
    assert fila["estado"] == "cuadrado" and fila["puede_ajustar"] is False

    _vender(entorno, b["headers"], 500, "12")
    assert _mi_caja(entorno, b["headers"]) == 500
    fila = _balance_control(entorno, "eli")
    assert fila["estado"] == "positivo" and float(fila["balance_real"]) == 500
    assert entorno.saldo(b["sucursal"]["id"]) == general
    # Sin ajustes automáticos.
    assert entorno.c.get("/control-cajeros/ajustes", headers=entorno.admin).json() == []


# ------------------------------------------------------------------ Caso B
def test_caso_b_premio_superior_al_balance(entorno, monkeypatch):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    b = entorno.banca(saldo=50000, usuario="eli", clave="prueba123")
    general = entorno.saldo(b["sucursal"]["id"])
    lot = entorno.sorteo_id("LOTEDOM")
    t = entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [lot], "numeros": "25", "monto": 50}])
    _poner_mi_caja("eli", 2000)
    _simular(entorno, lot, 25)
    pago = entorno.c.post("/terminal/tickets/pagar", json={
        "id": t["id"], "serial": t["serial"], "operacion_id": "caso-b-1",
    }, headers=b["headers"])
    assert pago.status_code == 200, pago.text
    assert float(pago.json()["mi_caja"]) == -1000
    assert pago.json()["estado"] == "pagado"
    dup = entorno.c.post("/terminal/tickets/pagar", json={
        "id": t["id"], "serial": t["serial"], "operacion_id": "caso-b-2",
    }, headers=b["headers"])
    assert dup.status_code == 409
    assert _mi_caja(entorno, b["headers"]) == -1000
    assert entorno.saldo(b["sucursal"]["id"]) == general
    fila = _balance_control(entorno, "eli")
    assert fila["estado"] == "deuda" and float(fila["balance_real"]) == -1000


# ------------------------------------------------------------------ Caso C
def test_caso_c_recuperacion_despues_de_pagar(entorno, monkeypatch):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    b = entorno.banca(saldo=50000, usuario="eli", clave="prueba123")
    _poner_mi_caja("eli", -1000)
    _vender(entorno, b["headers"], 300, "20")
    assert _mi_caja(entorno, b["headers"]) == -700
    _vender(entorno, b["headers"], 700, "21")
    assert _mi_caja(entorno, b["headers"]) == 0
    assert _balance_control(entorno, "eli")["puede_ajustar"] is False


# ------------------------------------------------------------------ Caso D
def test_caso_d_ajuste_despues_de_recuperar_parcial(entorno, monkeypatch):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    b = entorno.banca(saldo=50000, usuario="eli", clave="prueba123")
    general = entorno.saldo(b["sucursal"]["id"])
    _poner_mi_caja("eli", -1000)
    _vender(entorno, b["headers"], 600, "30")
    assert _mi_caja(entorno, b["headers"]) == -400
    eli = _cajera(entorno, "eli")
    # No permitir ajustar la deuda original 1000.
    exceso = entorno.c.post("/control-cajeros/ajuste", json={
        "usuario_id": eli["id"], "monto": 1000, "motivo": "Deuda vieja",
        "operacion_id": "caso-d-exceso", "balance_visto": -400,
    }, headers=entorno.admin)
    assert exceso.status_code == 400
    ok = entorno.c.post("/control-cajeros/ajuste", json={
        "usuario_id": eli["id"], "monto": 400, "motivo": "Ajuste deuda vigente",
        "operacion_id": "caso-d-ok", "balance_visto": -400,
    }, headers=entorno.admin)
    assert ok.status_code == 201, ok.text
    assert float(ok.json()["balance_posterior"]) == 0
    assert _mi_caja(entorno, b["headers"]) == 0
    assert entorno.saldo(b["sucursal"]["id"]) == general
    assert _balance_control(entorno, "eli")["puede_ajustar"] is False


# ------------------------------------------------------------------ Caso E
def test_caso_e_venta_durante_ajuste_rechaza(entorno, monkeypatch):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    b = entorno.banca(saldo=50000, usuario="eli", clave="prueba123")
    _poner_mi_caja("eli", -1000)
    eli = _cajera(entorno, "eli")
    # Admin "abre" con deuda vista -1000; cajera vende 700 → -300.
    _vender(entorno, b["headers"], 700, "40")
    assert _mi_caja(entorno, b["headers"]) == -300
    r = entorno.c.post("/control-cajeros/ajuste", json={
        "usuario_id": eli["id"], "monto": 1000, "motivo": "Ajuste desfasado",
        "operacion_id": "caso-e-1", "balance_visto": -1000,
    }, headers=entorno.admin)
    assert r.status_code == 409
    assert "balance cambió" in r.json()["detail"].lower() or "cambió" in r.json()["detail"].lower()
    assert _mi_caja(entorno, b["headers"]) == -300
    # Ajuste correcto con deuda vigente.
    ok = entorno.c.post("/control-cajeros/ajuste", json={
        "usuario_id": eli["id"], "monto": 300, "motivo": "Ajuste deuda actual",
        "operacion_id": "caso-e-2", "balance_visto": -300,
    }, headers=entorno.admin)
    assert ok.status_code == 201, ok.text
    assert float(ok.json()["balance_posterior"]) == 0


# ------------------------------------------------------------------ Caso F
def test_caso_f_recuperacion_completa_sin_ajuste(entorno, monkeypatch):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    b = entorno.banca(saldo=50000, usuario="eli", clave="prueba123")
    _poner_mi_caja("eli", -500)
    assert _balance_control(entorno, "eli")["puede_ajustar"] is True
    _vender(entorno, b["headers"], 500, "50")
    fila = _balance_control(entorno, "eli")
    assert float(fila["balance_real"]) == 0
    assert fila["estado"] == "cuadrado"
    assert fila["puede_ajustar"] is False
    assert entorno.c.get("/control-cajeros/ajustes", headers=entorno.admin).json() == []
    db = dbmod.nueva_sesion()
    try:
        assert db.query(AjusteCajaCajera).count() == 0
    finally:
        db.close()


# ------------------------------------------------------------------ Caso G (muestra)
def test_caso_g_seguridad_basica(entorno, monkeypatch):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    b = entorno.banca(saldo=50000, usuario="eli", clave="prueba123")
    entorno.operador("ana", "prueba123", b["sucursal"]["id"])
    ana = entorno.login_terminal("ana", "prueba123")
    lot = entorno.sorteo_id("LOTEDOM")
    t = entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [lot], "numeros": "25", "monto": 10}])
    _simular(entorno, lot, 25)
    # Otra cajera.
    assert entorno.c.post("/terminal/tickets/pagar", json={
        "id": t["id"], "serial": t["serial"], "operacion_id": "g-ajena",
    }, headers=ana).status_code == 403
    # Pago ok + duplicado.
    assert entorno.c.post("/terminal/tickets/pagar", json={
        "id": t["id"], "serial": t["serial"], "operacion_id": "g-pago",
    }, headers=b["headers"]).status_code == 200
    assert entorno.c.post("/terminal/tickets/pagar", json={
        "id": t["id"], "serial": t["serial"], "operacion_id": "g-pago2",
    }, headers=b["headers"]).status_code == 409
    # Anulado.
    t2 = entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [lot], "numeros": "25", "monto": 10}])
    entorno.c.post("/panel/tickets/anular", json={
        "id": t2["id"], "serial": t2["serial"], "motivo": "Cliente desistió",
    }, headers=entorno.admin)
    assert entorno.c.post("/terminal/tickets/pagar", json={
        "id": t2["id"], "serial": t2["serial"], "operacion_id": "g-anul",
    }, headers=b["headers"]).status_code == 409
    # Idempotencia ajuste.
    _poner_mi_caja("eli", -100)
    eli = _cajera(entorno, "eli")
    a1 = entorno.c.post("/control-cajeros/ajuste", json={
        "usuario_id": eli["id"], "monto": 100, "motivo": "Ajuste idem",
        "operacion_id": "g-aj-idem", "balance_visto": -100,
    }, headers=entorno.admin)
    a2 = entorno.c.post("/control-cajeros/ajuste", json={
        "usuario_id": eli["id"], "monto": 100, "motivo": "Ajuste idem",
        "operacion_id": "g-aj-idem", "balance_visto": -100,
    }, headers=entorno.admin)
    assert a1.status_code == 201 and a2.status_code == 201
    assert a1.json()["id"] == a2.json()["id"]
    assert _mi_caja(entorno, b["headers"]) == 0


def test_caso_g_anulacion_revierte_recuperacion(entorno, monkeypatch):
    """Anular una venta que recuperó deuda revierte MI CAJA una sola vez."""
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    b = entorno.banca(saldo=50000, usuario="eli", clave="prueba123")
    general = entorno.saldo(b["sucursal"]["id"])
    _poner_mi_caja("eli", -500)
    t = _vender(entorno, b["headers"], 500, "60")
    assert _mi_caja(entorno, b["headers"]) == 0
    an = entorno.c.post("/panel/tickets/anular", json={
        "id": t["id"], "serial": t["serial"], "motivo": "Error de venta",
    }, headers=entorno.admin)
    assert an.status_code == 200, an.text
    assert _mi_caja(entorno, b["headers"]) == -500
    # Segunda anulación no aplica.
    an2 = entorno.c.post("/panel/tickets/anular", json={
        "id": t["id"], "serial": t["serial"], "motivo": "Otra vez",
    }, headers=entorno.admin)
    assert an2.status_code == 409
    assert _mi_caja(entorno, b["headers"]) == -500
    assert entorno.saldo(b["sucursal"]["id"]) == general
    assert _balance_control(entorno, "eli")["estado"] == "deuda"


def test_caso_g_dos_admins_ajuste_concurrente(entorno, monkeypatch):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    b = entorno.banca(saldo=50000, usuario="eli", clave="prueba123")
    _poner_mi_caja("eli", -800)
    eli = _cajera(entorno, "eli")
    admin = next(u for u in entorno.c.get("/usuarios", headers=entorno.admin).json() if u["usuario"] == "admin")
    resultados = []
    barrera = threading.Barrier(2)

    def intento(op, monto):
        db = dbmod.nueva_sesion()
        try:
            barrera.wait(timeout=10)
            servicios.aplicar_ajuste_banca_negativa(
                db, db.get(Usuario, admin["id"]), eli["id"], monto,
                "Ajuste concurrente", op, -800,
            )
            resultados.append("ok")
        except ErrorServicio as e:
            resultados.append(e.status)
        except Exception as e:
            resultados.append(type(e).__name__)
        finally:
            db.close()

    h1 = threading.Thread(target=intento, args=("g-conc-a", 800))
    h2 = threading.Thread(target=intento, args=("g-conc-b", 800))
    h1.start(); h2.start()
    h1.join(15); h2.join(15)
    assert _mi_caja(entorno, b["headers"]) == 0
    # PostgreSQL serializa con FOR UPDATE (un solo ok). SQLite no bloquea filas:
    # se exige al menos un ok y balance final 0 (sin quedar positivo).
    dialect = dbmod.engine().dialect.name
    if dialect == "sqlite":
        assert resultados.count("ok") >= 1, resultados
        assert float(_mi_caja(entorno, b["headers"])) <= 0.009
    else:
        assert resultados.count("ok") == 1, resultados
