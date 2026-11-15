"""Palé repetido: una sola apuesta. La liquidación usa la tabla actual.

Los factores siguen siendo 1-2, 1-3 y 2-3. Una pareja con los dos números
iguales no ocupa dos premios distintos, así que no gana y no crea un factor nuevo.
"""


def test_pale_23_23_se_guarda_una_vez_y_liquida_en_cero(entorno):
    b = entorno.banca(saldo=1000)
    s = entorno.sorteo_id("La Primera 12")
    t = entorno.vender_ok(b["headers"], [{"tipo": "PL", "sorteos": [s], "numeros": "2323", "monto": 10}])
    assert len(t["jugadas"]) == 1
    assert t["jugadas"][0]["numeros"] == "23-23"
    assert float(t["jugadas"][0]["monto"]) == 10.00
    assert float(t["total"]) == 10.00
    entorno.liquidar(s, 23, 1, 2)
    c = entorno.consultar(t)
    assert c["estado"] == "no_ganador"
    assert float(c["premio_total"]) == 0.00
    assert c["jugadas"][0]["detalle_eval"] is None


def test_pale_00_00_conserva_ceros_y_12_34_paga_la_tabla_existente(entorno):
    b = entorno.banca(saldo=1000)
    s = entorno.sorteo_id("Nacional Noche")
    ceros = entorno.vender_ok(b["headers"], [{"tipo": "PL", "sorteos": [s], "numeros": "0000", "monto": 5}])
    assert ceros["jugadas"][0]["numeros"] == "00-00"
    normal = entorno.vender_ok(b["headers"], [{"tipo": "PL", "sorteos": [s], "numeros": "3412", "monto": 5}])
    assert normal["jugadas"][0]["numeros"] == "12-34"
    entorno.liquidar(s, 12, 34, 0)
    assert entorno.consultar(ceros)["estado"] == "no_ganador"
    ganado = entorno.consultar(normal)
    assert ganado["estado"] == "ganador"
    assert float(ganado["premio_total"]) == 6000.00  # 5 × 1200, posición 1-2
    assert ganado["jugadas"][0]["detalle_eval"] == "1-2"


def test_limite_de_pale_repetido_y_aplicar_a_todos(entorno):
    b = entorno.banca(saldo=100000)
    s = entorno.sorteo_id("La Primera 12")
    catalogo = entorno.c.get("/sorteos", headers=entorno.admin).json()
    vista = entorno.c.post("/limites/aplicar-todas", json={
        "tipo": "PL", "numeros": "23-23", "monto_max_acumulado": 1000, "aplicar": False,
    }, headers=entorno.admin)
    assert vista.status_code == 200, vista.text
    assert vista.json()["clave"] == "23-23"
    assert vista.json()["sorteos"] == len(catalogo)
    hecho = entorno.c.post("/limites/aplicar-todas", json={
        "tipo": "PL", "numeros": "2323", "monto_max_acumulado": 10, "aplicar": True,
    }, headers=entorno.admin)
    assert hecho.status_code == 200, hecho.text
    assert hecho.json()["creados"] == len(catalogo)
    entorno.vender_ok(b["headers"], [{"tipo": "PL", "sorteos": [s], "numeros": "23-23", "monto": 10}])
    exceso = entorno.vender(b["headers"], [{"tipo": "PL", "sorteos": [s], "numeros": "23-23", "monto": 5}])
    assert exceso.status_code == 409
    assert "23-23" in exceso.json()["detail"]


def test_super_pale_igual_solo_cobra_si_los_dos_primeros_coinciden(entorno):
    b = entorno.banca(saldo=1000)
    real = entorno.sorteo_id("Real Tarde")
    primera = entorno.sorteo_id("La Primera 12")
    igual = entorno.vender_ok(b["headers"], [
        {"tipo": "SP", "sorteos": [real, primera], "numeros": "23-23", "monto": 5},
    ])
    distinto = entorno.vender_ok(b["headers"], [
        {"tipo": "SP", "sorteos": [real, primera], "numeros": "23-58", "monto": 5},
    ])
    assert igual["jugadas"][0]["numeros"] == "23-23"
    assert float(igual["total"]) == 5.00
    entorno.liquidar(real, 23, 1, 2)
    entorno.liquidar(primera, 23, 9, 8)
    assert float(entorno.consultar(igual)["premio_total"]) == 12500.00  # 5 × 2500, factor sp ya existente
    assert float(entorno.consultar(distinto)["premio_total"]) == 0.00
