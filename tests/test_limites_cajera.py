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


def test_limites_tambien_acumulan_en_modo_desarrollo(entorno, monkeypatch):
    """Con MODO_DESARROLLO las ventas son es_prueba; el tope debe acumularlas igual."""
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    from apps.api import comun
    monkeypatch.setattr(comun, "modo_desarrollo", lambda: True)
    from apps.api import servicios
    monkeypatch.setattr(servicios, "modo_desarrollo", lambda: True)

    b = entorno.banca(saldo=100000, usuario="jose", clave="prueba123")
    jose = _id(entorno, "jose")
    primera = entorno.sorteo_id("La Primera 12")
    _limite(entorno, jose, primera, "QN", "33", 50)
    entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [primera], "numeros": "33", "monto": 40}])
    exceso = entorno.vender(b["headers"], [{"tipo": "QN", "sorteos": [primera], "numeros": "33", "monto": 20}])
    assert exceso.status_code == 409 and "cajera" in exceso.json()["detail"]


def _limite_sp(entorno, usuario_id, s1, s2, numeros, monto):
    r = entorno.c.post("/limites-cajera", json={
        "usuario_id": usuario_id, "sorteo_id": s1, "sorteo2_id": s2,
        "tipo": "SP", "numeros": numeros, "monto_max_acumulado": monto,
    }, headers=entorno.admin)
    assert r.status_code == 201, r.text
    return r.json()


def test_limites_sp_tr_orden_acumulado_y_aislamiento(entorno, fijar_hora):
    b = entorno.banca(saldo=100000, usuario="jose", clave="prueba123")
    entorno.operador("ana", "prueba123", b["sucursal"]["id"])
    ana = entorno.login_terminal("ana", "prueba123")
    jose = _id(entorno, "jose")
    ana_id = _id(entorno, "ana")
    primera = entorno.sorteo_id("La Primera 12")
    real = entorno.sorteo_id("Real Tarde")

    # SP individual: tope por combinación + par de loterías (orden indiferente).
    _limite_sp(entorno, jose, primera, real, "07-19", 40)
    entorno.vender_ok(b["headers"], [{
        "tipo": "SP", "sorteos": [primera, real], "numeros": "07-19", "monto": 30,
    }])
    # Invertir loterías y números no evade el acumulado.
    exceso_sp = entorno.vender(b["headers"], [{
        "tipo": "SP", "sorteos": [real, primera], "numeros": "19-07", "monto": 20,
    }])
    assert exceso_sp.status_code == 409 and "cajera" in exceso_sp.json()["detail"]
    # Otra cajera no comparte el tope de jose.
    entorno.vender_ok(ana, [{
        "tipo": "SP", "sorteos": [primera, real], "numeros": "07-19", "monto": 40,
    }])

    # SP general (*): cada combinación tiene su propio máximo.
    _limite_sp(entorno, jose, 0, 0, "*", 25)
    entorno.vender_ok(b["headers"], [{
        "tipo": "SP", "sorteos": [primera, real], "numeros": "11-22", "monto": 25,
    }])
    gen_sp = entorno.vender(b["headers"], [{
        "tipo": "SP", "sorteos": [primera, real], "numeros": "11-22", "monto": 5,
    }])
    assert gen_sp.status_code == 409

    # TR: orden libre y repeticiones equivalen a la misma clave.
    _limite(entorno, jose, primera, "TR", "12-25-38", 30)
    entorno.vender_ok(b["headers"], [{
        "tipo": "TR", "sorteos": [primera], "numeros": "12-25-38", "monto": 20,
    }])
    ord_tr = entorno.vender(b["headers"], [{
        "tipo": "TR", "sorteos": [primera], "numeros": "38-12-25", "monto": 15,
    }])
    assert ord_tr.status_code == 409 and "12-25-38" in ord_tr.json()["detail"]

    _limite(entorno, jose, primera, "TR", "12-12-38", 20)
    entorno.vender_ok(b["headers"], [{
        "tipo": "TR", "sorteos": [primera], "numeros": "12-12-38", "monto": 20,
    }])
    rep_tr = entorno.vender(b["headers"], [{
        "tipo": "TR", "sorteos": [primera], "numeros": "38-12-12", "monto": 5,
    }])
    assert rep_tr.status_code == 409

    # TR general + aislamiento de cajera / varias ventas.
    _limite(entorno, jose, 0, "TR", "*", 15)
    entorno.vender_ok(b["headers"], [{
        "tipo": "TR", "sorteos": [real], "numeros": "01-02-03", "monto": 10,
    }])
    entorno.vender_ok(b["headers"], [{
        "tipo": "TR", "sorteos": [real], "numeros": "01-02-03", "monto": 5,
    }])
    split_tr = entorno.vender(b["headers"], [{
        "tipo": "TR", "sorteos": [real], "numeros": "03-01-02", "monto": 5,
    }])
    assert split_tr.status_code == 409, split_tr.text
    entorno.vender_ok(ana, [{
        "tipo": "TR", "sorteos": [real], "numeros": "01-02-03", "monto": 15,
    }])

    # Límite general (LimiteVenta) más restrictivo que el de cajera.
    entorno.c.post("/limites", json={
        "sorteo_id": primera, "tipo": "TR", "numeros": "44-55-66", "monto_max_acumulado": 10,
    }, headers=entorno.admin)
    _limite(entorno, ana_id, primera, "TR", "44-55-66", 100)
    gen_tr = entorno.vender(ana, [{
        "tipo": "TR", "sorteos": [primera], "numeros": "66-44-55", "monto": 15,
    }])
    assert gen_tr.status_code == 409 and gen_tr.json()["detail"].startswith("Límite alcanzado")
