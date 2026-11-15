"""Pago de premios: pago único atómico, en cualquier sucursal (alcance 6)."""
import threading

from apps.api import db as dbmod
from apps.api import servicios
from apps.api.comun import ErrorServicio


def _ticket_ganador(entorno, monto=10, numero="19"):
    b = entorno.banca()
    s = entorno.sorteo_id("La Primera 12")
    t = entorno.vender_ok(b["headers"], [
        {"tipo": "QN", "sorteos": [s], "numeros": numero, "monto": monto},
    ])
    entorno.liquidar(s, 19, 3, 45)
    return b, t  # premio: 10 × 60 = 600


def test_pagar_en_otra_sucursal(entorno):
    b1, t = _ticket_ganador(entorno)
    # La sucursal pagadora necesita el efectivo en su caja (premio $600)
    b2 = entorno.banca(saldo=1000, codigo="2200", nombre="BANCA PEGUERO", usuario="vend2")
    r = entorno.c.post("/terminal/tickets/pagar",
                       json={"id": t["id"], "serial": t["serial"]}, headers=b2["headers"])
    assert r.status_code == 200, r.text
    datos = r.json()
    assert datos["estado"] == "pagado"
    assert datos["pago"]["sucursal"] == "BANCA PEGUERO"
    assert float(datos["pago"]["monto"]) == 600.00
    c = entorno.consultar(t)
    assert c["estado"] == "pagado" and "Ya pagado en la sucursal BANCA PEGUERO" in c["mensaje"]


def test_segundo_pago_rechazado_con_datos_del_primero(entorno):
    b1, t = _ticket_ganador(entorno)
    r = entorno.c.post("/panel/tickets/pagar",
                       json={"id": t["id"], "serial": t["serial"], "sucursal_id": b1["sucursal"]["id"]},
                       headers=entorno.admin)
    assert r.status_code == 200, r.text
    r2 = entorno.c.post("/terminal/tickets/pagar",
                        json={"id": t["id"], "serial": t["serial"]}, headers=b1["headers"])
    assert r2.status_code == 409
    detalle = r2.json()["detail"]
    assert "Ya pagado en la sucursal BANCA CASTILLO" in detalle


def test_pago_concurrente_real(entorno):
    # Dos sesiones de BD pagan a la vez el mismo ticket llamando al servicio:
    # la guarda es la actualización condicional ganador->pagado (una sola
    # operación). Exactamente un intento debe lograrlo.
    b1, t = _ticket_ganador(entorno)
    admin = entorno.c.get("/usuarios", headers=entorno.admin).json()
    admin_id = [u for u in admin if u["usuario"] == "admin"][0]["id"]
    resultados = []
    barrera = threading.Barrier(2)

    def intento(sucursal_id):
        db = dbmod.nueva_sesion()
        try:
            barrera.wait(timeout=10)
            servicios.pagar_ticket(db, t["id"], t["serial"], sucursal_id, None, admin_id)
            resultados.append("ok")
        except ErrorServicio as e:
            resultados.append(e.status)
        finally:
            db.close()

    hilos = [
        threading.Thread(target=intento, args=(b1["sucursal"]["id"],)),
        threading.Thread(target=intento, args=(b1["sucursal"]["id"],)),
    ]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(timeout=30)
    assert resultados.count("ok") == 1, resultados
    assert resultados.count(409) == 1, resultados
    assert entorno.consultar(t)["estado"] == "pagado"


def test_pagar_no_ganador(entorno):
    b = entorno.banca()
    s = entorno.sorteo_id("La Primera 12")
    t = entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [s], "numeros": "77", "monto": 10}])
    entorno.liquidar(s, 19, 3, 45)
    r = entorno.c.post("/terminal/tickets/pagar",
                       json={"id": t["id"], "serial": t["serial"]}, headers=b["headers"])
    assert r.status_code == 409 and "no ganó" in r.json()["detail"]


def test_pagar_sin_liquidar(entorno):
    b = entorno.banca()
    s = entorno.sorteo_id("La Primera 12")
    t = entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [s], "numeros": "19", "monto": 10}])
    r = entorno.c.post("/terminal/tickets/pagar",
                       json={"id": t["id"], "serial": t["serial"]}, headers=b["headers"])
    assert r.status_code == 409 and "faltan resultados" in r.json()["detail"]


def test_consultar_y_pagar_con_serial_incorrecto(entorno):
    b, t = _ticket_ganador(entorno)
    r = entorno.c.post("/panel/tickets/consultar",
                       json={"id": t["id"], "serial": "XXXXXXXXXX"}, headers=entorno.admin)
    assert r.status_code == 404
    r = entorno.c.post("/terminal/tickets/pagar",
                       json={"id": t["id"], "serial": "XXXXXXXXXX"}, headers=b["headers"])
    assert r.status_code == 404
    r = entorno.c.post("/panel/tickets/consultar",
                       json={"id": 999999, "serial": t["serial"]}, headers=entorno.admin)
    assert r.status_code == 404
