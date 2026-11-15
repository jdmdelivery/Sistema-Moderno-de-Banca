"""Cada aparato tiene su terminal. El login viejo, sin serial, sigue igual."""
from apps.api.models import Terminal
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
    assert float(primero.json()["saldo"]) == antes

    otra_vez = _entrar(entorno, "vend1", "1234", "TEL-SAMSUNG-1")
    assert otra_vez.json()["terminal"]["id"] == primero.json()["terminal"]["id"]

    segundo = _entrar(entorno, "vend1", "1234", "TEL-REDMI-2", "Xiaomi Redmi Note")
    assert segundo.status_code == 200, segundo.text
    assert segundo.json()["terminal"]["id"] != primero.json()["terminal"]["id"]
    assert segundo.json()["terminal"]["serial"] == "TEL-REDMI-2"
    assert entorno.saldo(b["sucursal"]["id"]) == antes

    otra = entorno.banca(saldo=1000, codigo="2200", nombre="OTRA", usuario="vend2")
    ajeno = _entrar(entorno, "vend2", "1234", "TEL-SAMSUNG-1")
    assert ajeno.status_code == 403
    assert entorno.saldo(otra["sucursal"]["id"]) == 1000

    db = dbmod.nueva_sesion()
    sunmi = db.get(Terminal, primero.json()["terminal"]["id"])
    sunmi.activa = False
    db.commit()
    db.close()
    bloqueada = _entrar(entorno, "vend1", "1234", "TEL-SAMSUNG-1")
    assert bloqueada.status_code == 403
    libre = _entrar(entorno, "vend1", "1234", "TEL-REDMI-2")
    assert libre.status_code == 200
    assert entorno.saldo(b["sucursal"]["id"]) == antes
