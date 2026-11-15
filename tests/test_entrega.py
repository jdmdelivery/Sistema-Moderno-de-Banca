"""La entrega sale del cajón de la cajera. No borra el historial ni la caja de la banca."""
from apps.api.models import Resultado, Ticket


def _jugar(entorno, headers, numero, monto):
    sorteo = entorno.sorteo_id("La Primera 12")
    return entorno.vender_ok(headers, [
        {"tipo": "QN", "sorteos": [sorteo], "numeros": numero, "monto": monto},
    ])


def _estado(entorno, headers):
    r = entorno.c.get("/terminal/entregas/estado", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _entregar(entorno, headers, monto, operacion):
    return entorno.c.post(
        "/terminal/entregas",
        json={"monto": monto, "operacion_id": operacion},
        headers=headers,
    )


def test_entrega_parcial_total_y_ciclo_nuevo_conservan_el_historial(entorno):
    b = entorno.banca(saldo=5764)
    assert _entregar(entorno, b["headers"], 5764, "op-banca").status_code == 409
    assert entorno.saldo(b["sucursal"]["id"]) == 5764
    assert _estado(entorno, b["headers"])["mi_caja"] == "0.00"

    jose = _jugar(entorno, b["headers"], "25", 5000)
    entorno.operador("vend2", "1234", b["sucursal"]["id"])
    otra = entorno.login_terminal("vend2", "1234")
    _jugar(entorno, otra, "26", 100)
    assert entorno.saldo(b["sucursal"]["id"]) == 10864
    assert _estado(entorno, b["headers"])["mi_caja"] == "5000.00"
    assert _estado(entorno, b["headers"])["recaudacion_ciclo"] == "5000.00"
    assert _estado(entorno, b["headers"])["fondo_inicial"] is None
    assert _estado(entorno, otra)["mi_caja"] == "100.00"

    falta = entorno.c.get("/terminal/entregas/operacion/op-parcial", headers=b["headers"])
    assert falta.status_code == 404
    parcial = _entregar(entorno, b["headers"], 3000, "op-parcial")
    assert parcial.status_code == 201, parcial.text
    cuerpo = parcial.json()
    assert cuerpo["saldo_anterior"] == "5000.00"
    assert cuerpo["monto"] == "3000.00"
    assert cuerpo["saldo_restante"] == "2000.00"
    assert cuerpo["estado"] == "CONFIRMADA"
    assert "COMPROBANTE DE ENTREGA" in cuerpo["texto"]
    assert "PRUEBA — NO OFICIAL" not in cuerpo["texto"]
    assert entorno.saldo(b["sucursal"]["id"]) == 10864
    assert _estado(entorno, b["headers"])["efectivo_pendiente"] == "2000.00"
    assert _estado(entorno, otra)["mi_caja"] == "100.00"

    repetida = _entregar(entorno, b["headers"], 3000, "op-parcial")
    assert repetida.status_code == 201
    assert repetida.json()["id"] == cuerpo["id"]
    assert _estado(entorno, b["headers"])["mi_caja"] == "2000.00"
    encontrada = entorno.c.get("/terminal/entregas/operacion/op-parcial", headers=b["headers"])
    assert encontrada.status_code == 200
    assert encontrada.json()["id"] == cuerpo["id"]

    total = _entregar(entorno, b["headers"], 2000, "op-total")
    assert total.status_code == 201, total.text
    assert total.json()["saldo_restante"] == "0.00"
    cero = _estado(entorno, b["headers"])
    assert cero["mi_caja"] == "0.00"
    assert cero["efectivo_pendiente"] == "0.00"
    assert cero["entrega_pendiente"] == "0.00"
    assert cero["recaudacion_ciclo"] == "0.00"
    assert _estado(entorno, otra)["mi_caja"] == "100.00"

    panel = entorno.c.get("/entregas", headers=entorno.admin)
    assert panel.status_code == 200, panel.text
    reales = panel.json()["reales"]
    assert [fila["numero"] for fila in reales] == [total.json()["numero"], cuerpo["numero"]]
    assert panel.json()["prueba"] == []
    copia = entorno.c.get(f"/terminal/entregas/{cuerpo['id']}", headers=b["headers"])
    assert copia.status_code == 200
    assert copia.json()["texto"] == cuerpo["texto"]
    assert len(entorno.c.get("/entregas", headers=entorno.admin).json()["reales"]) == 2

    recibida = entorno.c.post(f"/entregas/{cuerpo['id']}/recibir", headers=entorno.admin)
    assert recibida.status_code == 200, recibida.text
    assert recibida.json()["recepcion"] == "RECIBIDA"
    assert _estado(entorno, b["headers"])["mi_caja"] == "0.00"
    assert entorno.saldo(b["sucursal"]["id"]) == 10864

    nueva = _jugar(entorno, b["headers"], "27", 10)
    despues = _estado(entorno, b["headers"])
    assert despues["mi_caja"] == "10.00"
    assert despues["efectivo_pendiente"] == "10.00"
    assert despues["recaudacion_ciclo"] == "10.00"
    resumen = entorno.c.get("/terminal/reportes/dia", headers=b["headers"])
    assert resumen.status_code == 200, resumen.text
    assert resumen.json()["real"]["ventas"] == "5010.00"
    from apps.api import db as dbmod
    db = dbmod.nueva_sesion()
    assert db.get(Ticket, jose["id"]).estado == "vendido"
    assert db.get(Ticket, nueva["id"]).estado == "vendido"
    assert db.query(Resultado).count() == 0
    db.close()

    otra_banca = entorno.sucursal(codigo="2200", nombre="OTRA BANCA")
    supervisor = entorno.c.post(
        "/usuarios",
        json={"nombre": "Supervisor ajeno", "usuario": "sup2", "rol": "supervisor",
              "sucursal_id": otra_banca["id"], "clave": "1234"},
        headers=entorno.admin,
    )
    assert supervisor.status_code == 201, supervisor.text
    sesion = entorno.c.post("/auth/login", json={"usuario": "sup2", "clave": "1234"})
    assert sesion.status_code == 200, sesion.text
    ajenos = {"Authorization": f"Bearer {sesion.json()['token']}"}
    assert entorno.c.get("/entregas", headers=ajenos).json()["reales"] == []
    prohibido = entorno.c.get(f"/entregas?sucursal_id={b['sucursal']['id']}", headers=ajenos)
    assert prohibido.status_code == 403


def test_la_entrega_de_prueba_no_toca_la_caja_real(entorno, monkeypatch):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    b = entorno.banca(saldo=5764)
    _jugar(entorno, b["headers"], "25", 50)
    assert entorno.saldo(b["sucursal"]["id"]) == 5764
    assert _estado(entorno, b["headers"])["mi_caja"] == "50.00"
    entrega = _entregar(entorno, b["headers"], 50, "op-prueba")
    assert entrega.status_code == 201, entrega.text
    assert "PRUEBA — NO OFICIAL" in entrega.json()["texto"]
    assert _estado(entorno, b["headers"])["mi_caja"] == "0.00"
    assert _estado(entorno, b["headers"])["recaudacion_ciclo"] == "0.00"
    assert entorno.saldo(b["sucursal"]["id"]) == 5764
    panel = entorno.c.get("/entregas", headers=entorno.admin).json()
    assert panel["reales"] == []
    assert panel["prueba"][0]["monto"] == "50.00"
    assert panel["prueba"][0]["leyenda"] == "PRUEBA — NO OFICIAL"
