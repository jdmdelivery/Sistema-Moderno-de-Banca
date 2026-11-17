"""Cada aparato tiene su terminal. Puede cambiar de sucursal con otro cajero."""
from apps.api.models import Auditoria, Sesion, Terminal
from apps.api import db as dbmod


def _entrar(entorno, usuario, clave, dispositivo=None, modelo=None):
    cuerpo = {"usuario": usuario, "clave": clave}
    if dispositivo:
        cuerpo["dispositivo_id"] = dispositivo
        cuerpo["modelo"] = modelo or "Samsung SM-A515F"
        cuerpo["android"] = "31"
        cuerpo["version_app"] = "0.3.5"
    return entorno.c.post("/terminal/login", json=cuerpo)


def test_dos_telefonos_no_comparten_terminal_y_la_caja_no_cambia(entorno):
    b = entorno.banca(saldo=5764)
    antes = entorno.saldo(b["sucursal"]["id"])
    primero = _entrar(entorno, "vend1", "1234", "TEL-SAMSUNG-1", "Samsung SM-A515F")
    assert primero.status_code == 200, primero.text
    assert primero.json()["terminal"]["serial"] == "TEL-SAMSUNG-1"
    assert primero.json()["terminal"]["modelo"] == "Samsung SM-A515F"
    assert "saldo" not in primero.json()
    assert "saldo_actual" not in primero.json()["sucursal"]
    assert entorno.saldo(b["sucursal"]["id"]) == antes

    otra_vez = _entrar(entorno, "vend1", "1234", "TEL-SAMSUNG-1")
    assert otra_vez.json()["terminal"]["id"] == primero.json()["terminal"]["id"]

    segundo = _entrar(entorno, "vend1", "1234", "TEL-REDMI-2", "Xiaomi Redmi Note")
    assert segundo.status_code == 200, segundo.text
    assert segundo.json()["terminal"]["id"] != primero.json()["terminal"]["id"]
    assert segundo.json()["terminal"]["serial"] == "TEL-REDMI-2"
    assert entorno.saldo(b["sucursal"]["id"]) == antes

    # Mismo aparato, otra sucursal: se reasigna (ya no bloquea).
    otra = entorno.banca(saldo=1000, codigo="2200", nombre="OTRA", usuario="vend2")
    ajeno = _entrar(entorno, "vend2", "1234", "TEL-SAMSUNG-1")
    assert ajeno.status_code == 200, ajeno.text
    assert ajeno.json()["sucursal"]["id"] == otra["sucursal"]["id"]
    assert ajeno.json()["terminal"]["serial"] == "TEL-SAMSUNG-1"
    assert ajeno.json()["terminal"]["id"] == primero.json()["terminal"]["id"]
    assert entorno.saldo(otra["sucursal"]["id"]) == 1000
    assert entorno.saldo(b["sucursal"]["id"]) == antes

    db = dbmod.nueva_sesion()
    sunmi = db.get(Terminal, primero.json()["terminal"]["id"])
    sunmi.activa = False
    db.commit()
    db.close()
    bloqueada = _entrar(entorno, "vend2", "1234", "TEL-SAMSUNG-1")
    assert bloqueada.status_code == 403
    libre = _entrar(entorno, "vend1", "1234", "TEL-REDMI-2")
    assert libre.status_code == 200
    assert entorno.saldo(b["sucursal"]["id"]) == antes


def test_cambio_sucursal_castillo_peguero_y_separacion_tickets(entorno):
    castillo = entorno.banca(saldo=5000, codigo="1301", nombre="BANCA CASTILLO", usuario="cast1")
    peguero = entorno.banca(saldo=3000, codigo="1401", nombre="BANCA PEGUERO", usuario="pegu1")
    serial = "SUNMI-CAMBIO-1"
    sorteo = entorno.sorteo_id("LOTEDOM")

    r1 = _entrar(entorno, "cast1", "1234", serial)
    assert r1.status_code == 200, r1.text
    h1 = {"Authorization": f"Bearer {r1.json()['token']}"}
    t1 = entorno.vender_ok(h1, [{"tipo": "QN", "sorteos": [sorteo], "numeros": "11", "monto": 10}])
    assert t1["banca_codigo"] == "1301"

    r2 = _entrar(entorno, "pegu1", "1234", serial)
    assert r2.status_code == 200, r2.text
    assert r2.json()["sucursal"]["id"] == peguero["sucursal"]["id"]
    assert r2.json()["terminal"]["id"] == r1.json()["terminal"]["id"]
    vieja = entorno.c.get("/terminal/sorteos", headers=h1)
    assert vieja.status_code == 401

    h2 = {"Authorization": f"Bearer {r2.json()['token']}"}
    t2 = entorno.vender_ok(h2, [{"tipo": "QN", "sorteos": [sorteo], "numeros": "22", "monto": 15}])
    assert t2["id"] != t1["id"]
    assert t2["banca_codigo"] == "1401"

    assert abs(entorno.saldo(castillo["sucursal"]["id"]) - 5010) < 0.01
    assert abs(entorno.saldo(peguero["sucursal"]["id"]) - 3015) < 0.01

    r3 = _entrar(entorno, "cast1", "1234", serial)
    assert r3.status_code == 200, r3.text
    assert r3.json()["sucursal"]["id"] == castillo["sucursal"]["id"]

    db = dbmod.nueva_sesion()
    try:
        aud = (
            db.query(Auditoria)
            .filter_by(entidad="terminal", accion="reasignacion_sucursal")
            .count()
        )
        assert aud >= 2
    finally:
        db.close()


def test_login_dispositivo_revocado_bloquea_cualquier_sucursal(entorno):
    entorno.banca(usuario="rev1", clave="1234")
    entorno.banca(saldo=1000, codigo="2201", nombre="OTRA2", usuario="rev2")
    r = _entrar(entorno, "rev1", "1234", "SUNMI-REV-1")
    assert r.status_code == 200, r.text
    tid = r.json()["terminal"]["id"]
    db = dbmod.nueva_sesion()
    try:
        t = db.get(Terminal, tid)
        t.activa = False
        db.commit()
    finally:
        db.close()
    assert _entrar(entorno, "rev1", "1234", "SUNMI-REV-1").status_code == 403
    assert _entrar(entorno, "rev2", "1234", "SUNMI-REV-1").status_code == 403


def test_login_incorrecto_y_usuario_bloqueado(entorno):
    entorno.banca(usuario="blk1", clave="1234")
    mal = _entrar(entorno, "blk1", "clave-mala", "SUNMI-BLK-1")
    assert mal.status_code == 401
    ok = _entrar(entorno, "blk1", "1234", "SUNMI-BLK-1")
    assert ok.status_code == 200
    uid = next(
        u["id"] for u in entorno.c.get("/usuarios", headers=entorno.admin).json()
        if u["usuario"] == "blk1"
    )
    bloqueo = entorno.c.post(f"/usuarios/{uid}/bloquear", headers=entorno.admin)
    assert bloqueo.status_code == 200, bloqueo.text
    assert _entrar(entorno, "blk1", "1234", "SUNMI-BLK-1").status_code == 401


def test_nuevo_dispositivo_crea_terminal_sin_tocar_otras(entorno):
    b = entorno.banca(usuario="new1", clave="1234")
    r = _entrar(entorno, "new1", "1234", "SUNMI-NUEVA-99")
    assert r.status_code == 200, r.text
    assert r.json()["terminal"]["serial"] == "SUNMI-NUEVA-99"
    assert r.json()["sucursal"]["id"] == b["sucursal"]["id"]


def test_login_cierra_sesion_previa_del_mismo_aparato(entorno):
    b = entorno.banca(usuario="ses1", clave="1234")
    entorno.operador("ses2", "1234", b["sucursal"]["id"])
    a = _entrar(entorno, "ses1", "1234", "SUNMI-SES-1")
    assert a.status_code == 200, a.text
    token_a = a.json()["token"]
    b2 = _entrar(entorno, "ses2", "1234", "SUNMI-SES-1")
    assert b2.status_code == 200, b2.text
    vieja = entorno.c.get("/terminal/sorteos", headers={"Authorization": f"Bearer {token_a}"})
    assert vieja.status_code == 401
    db = dbmod.nueva_sesion()
    try:
        activas = db.query(Sesion).filter_by(terminal_id=a.json()["terminal"]["id"]).count()
        assert activas == 1
    finally:
        db.close()
