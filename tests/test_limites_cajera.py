"""Límites por cajera. El tope general más bajo sigue bloqueando."""
from datetime import datetime


def _id(entorno, usuario):
    for fila in entorno.c.get("/usuarios", headers=entorno.admin).json():
        if fila["usuario"] == usuario:
            return fila["id"]
    raise AssertionError(usuario)


def _limite(entorno, usuario_id, sorteo, tipo, numeros, monto):
    r = entorno.c.post("/limites-cajera", json={
        "usuario_id": usuario_id, "sorteo_id": sorteo, "tipo": tipo,
        "numeros": numeros, "monto_max_acumulado": monto,
    }, headers=entorno.admin)
    assert r.status_code == 201, r.text
    return r.json()


def test_quiniela_por_numero_pale_por_combinacion_y_otra_cajera(entorno, fijar_hora):
    b = entorno.banca(saldo=100000, usuario="jose", clave="prueba123")
    entorno.operador("ana", "prueba123", b["sucursal"]["id"])
    ana = entorno.login_terminal("ana", "prueba123")
    jose = _id(entorno, "jose")
    ana_id = _id(entorno, "ana")
    primera = entorno.sorteo_id("La Primera 12")
    real = entorno.sorteo_id("Real Tarde")
    assert entorno.c.post("/limites-cajera", json={
        "usuario_id": jose, "sorteo_id": primera, "tipo": "QN", "numeros": "*", "monto_max_acumulado": 500,
    }, headers=b["headers"]).status_code in (401, 403)

    todos = _limite(entorno, jose, 0, "QN", "*", 500)
    assert todos["sorteo"] == "Todas las loterías"
    assert todos["numero"] == "Todos los números"
    _limite(entorno, jose, 0, "PL", "*", 50)
    entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [primera], "numeros": "25", "monto": 500}])
    entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [primera], "numeros": "26", "monto": 500}])
    exceso = entorno.vender(b["headers"], [{"tipo": "QN", "sorteos": [primera], "numeros": "25", "monto": 10}])
    assert exceso.status_code == 409 and "cajera" in exceso.json()["detail"]
    entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [real], "numeros": "25", "monto": 500}])
    entorno.vender_ok(ana, [{"tipo": "QN", "sorteos": [primera], "numeros": "25", "monto": 500}])
    entorno.vender_ok(b["headers"], [{"tipo": "PL", "sorteos": [primera], "numeros": "12-34", "monto": 30}])
    entorno.vender_ok(b["headers"], [{"tipo": "PL", "sorteos": [primera], "numeros": "12-35", "monto": 30}])
    pale = entorno.vender(b["headers"], [{"tipo": "PL", "sorteos": [primera], "numeros": "34-12", "monto": 30}])
    assert pale.status_code == 409 and "12-34" in pale.json()["detail"]

    entorno.c.post("/limites", json={
        "sorteo_id": primera, "tipo": "QN", "numeros": "07", "monto_max_acumulado": 100,
    }, headers=entorno.admin)
    _limite(entorno, ana_id, primera, "QN", "07", 500)
    general = entorno.vender(ana, [{"tipo": "QN", "sorteos": [primera], "numeros": "07", "monto": 150}])
    assert general.status_code == 409 and general.json()["detail"].startswith("Límite alcanzado")

    _limite(entorno, jose, primera, "QN", "08", 100)
    propio = entorno.vender(b["headers"], [{"tipo": "QN", "sorteos": [primera], "numeros": "08", "monto": 150}])
    assert propio.status_code == 409 and "cajera" in propio.json()["detail"]
    entorno.vender_ok(ana, [{"tipo": "QN", "sorteos": [primera], "numeros": "08", "monto": 150}])

    lista = entorno.c.get(f"/limites-cajera?usuario_id={jose}", headers=entorno.admin).json()
    assert all(fila["usuario_id"] == jose for fila in lista)
    pale_id = next(fila["id"] for fila in lista if fila["tipo"] == "PL")
    editado = entorno.c.post("/limites-cajera", json={
        "id": pale_id, "usuario_id": jose, "sorteo_id": 0, "tipo": "PL",
        "numeros": "*", "monto_max_acumulado": 40,
    }, headers=entorno.admin)
    assert editado.status_code == 201 and editado.json()["monto_max_acumulado"] == "40.00"
    assert entorno.c.delete(f"/limites-cajera/{pale_id}", headers=entorno.admin).status_code == 200
    assert all(fila["id"] != pale_id for fila in entorno.c.get("/limites-cajera", headers=entorno.admin).json())

    fijar_hora(datetime(2026, 11, 15, 10, 0, 0))
    jose_otro_dia = entorno.login_terminal("jose", "prueba123")
    entorno.vender_ok(jose_otro_dia, [{"tipo": "QN", "sorteos": [primera], "numeros": "25", "monto": 500}])
