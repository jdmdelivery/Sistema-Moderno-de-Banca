"""La semilla de desarrollo crea una banca de prueba y no toca una base con sucursales."""


def test_sin_modo_desarrollo_no_crea_banca(entorno):
    from apps.api.db import nueva_sesion
    from apps.api.seed import sembrar_sucursal_prueba

    db = nueva_sesion()
    sembrar_sucursal_prueba(db)
    db.close()
    assert entorno.c.get("/sucursales", headers=entorno.admin).json() == []


def test_modo_desarrollo_siembra_banca_castillo_de_prueba(entorno, monkeypatch):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    from apps.api.db import nueva_sesion
    from apps.api.seed import sembrar_sucursal_prueba

    db = nueva_sesion()
    sembrar_sucursal_prueba(db)
    sembrar_sucursal_prueba(db)
    db.close()

    sucursales = entorno.c.get("/sucursales", headers=entorno.admin).json()
    assert len(sucursales) == 1
    assert sucursales[0]["nombre"] == "BANCA CASTILLO (PRUEBA)"
    assert sucursales[0]["codigo"] == "1301"
    assert float(sucursales[0]["saldo_actual"]) == 5764

    login = entorno.c.post("/terminal/login", json={"usuario": "jose", "clave": "prueba123"})
    assert login.status_code == 200, login.text
    cuerpo = login.json()
    assert cuerpo["modo_desarrollo"] is True
    assert cuerpo["leyenda"] == "MODO DESARROLLO — DATOS DE PRUEBA"
    assert cuerpo["operador"]["nombre"] == "JOSE (PRUEBA)"

    salud = entorno.c.get("/health").json()
    assert salud["datos"] == "prueba"
    assert salud["leyenda"] == "MODO DESARROLLO — DATOS DE PRUEBA"
