"""Reporte «Ventas por usuario»: el consorcio ve TODAS las ventas de
cada cajera (cada ticket guarda el usuario que lo vendió)."""


def _ventas(entorno, extra=""):
    r = entorno.c.get(
        f"/reportes/ventas?desde=2026-11-14&hasta=2026-11-14{extra}",
        headers=entorno.admin)
    assert r.status_code == 200, r.text
    return r.json()


def test_ventas_filtradas_por_usuario_y_totales(entorno):
    b1 = entorno.banca(saldo=0, codigo="1301", usuario="vend1")
    b2 = entorno.banca(saldo=0, codigo="2200", nombre="BANCA PEGUERO", usuario="vend2")
    s = entorno.sorteo_id("La Primera 12")
    entorno.vender_ok(b1["headers"], [{"tipo": "QN", "sorteos": [s], "numeros": "07", "monto": 40}])
    t10 = entorno.vender_ok(b1["headers"], [{"tipo": "QN", "sorteos": [s], "numeros": "08", "monto": 10}])
    entorno.vender_ok(b2["headers"], [{"tipo": "QN", "sorteos": [s], "numeros": "09", "monto": 25}])

    usuarios = entorno.c.get("/usuarios", headers=entorno.admin).json()
    vend2 = [u for u in usuarios if u["usuario"] == "vend2"][0]

    # Solo las de vend2
    r = _ventas(entorno, f"&usuario_id={vend2['id']}")
    assert r["total_tickets"] == 1
    assert float(r["total_vendido"]) == 25.00
    assert r["tickets"][0]["operador_usuario"] == "vend2"
    assert r["tickets"][0]["operador"] == "Operador vend2"
    assert r["tickets"][0]["banca"] == "BANCA PEGUERO"

    # Sin filtro: las de todos, más recientes primero
    r = _ventas(entorno)
    assert r["total_tickets"] == 3
    assert float(r["total_vendido"]) == 75.00
    assert r["tickets"][0]["id"] > r["tickets"][-1]["id"]

    # Un ticket anulado sale de la lista pero NO suma en el total vendido
    resp = entorno.c.post("/terminal/tickets/anular",
                          json={"id": t10["id"], "serial": t10["serial"]}, headers=b1["headers"])
    assert resp.status_code == 200, resp.text
    r = _ventas(entorno)
    assert r["total_tickets"] == 3
    assert float(r["total_vendido"]) == 65.00
    anulado = [t for t in r["tickets"] if t["id"] == t10["id"]][0]
    assert anulado["estado"] == "anulado"
