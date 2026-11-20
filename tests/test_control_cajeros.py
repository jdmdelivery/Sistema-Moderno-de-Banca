"""CONTROL DE CAJEROS: listado MI CAJA + ajuste contable de banca negativa.

Solo entorno local SQLite (conftest). No toca Render ni PostgreSQL de producción.
Los ajustes de prueba usan MODO_DESARROLLO y saldo_caja_prueba.
"""
from apps.api import db as dbmod
from apps.api.models import Usuario
from apps.api.servicios import mi_caja_de


def _cajera(entorno, usuario):
    for fila in entorno.c.get("/usuarios", headers=entorno.admin).json():
        if fila["usuario"] == usuario:
            return fila
    raise AssertionError(usuario)


def _poner_mi_caja_prueba(usuario_login, monto):
    """Fija saldo_caja_prueba sin tocar Banco General (solo tests locales)."""
    db = dbmod.nueva_sesion()
    try:
        u = db.query(Usuario).filter_by(usuario=usuario_login).first()
        assert u is not None
        u.saldo_caja_prueba = monto
        db.commit()
    finally:
        db.close()


def _mi_caja_terminal(entorno, headers):
    return entorno.c.get("/terminal/sorteos", headers=headers).json()["mi_caja"]


def test_control_lista_positivo_negativo_y_cero(entorno, monkeypatch):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    b = entorno.banca(saldo=5000, usuario="eli", clave="prueba123")
    entorno.operador("ana", "prueba123", b["sucursal"]["id"])
    entorno.operador("rosa", "prueba123", b["sucursal"]["id"])
    _poner_mi_caja_prueba("eli", -1835)
    _poner_mi_caja_prueba("ana", 250.50)
    _poner_mi_caja_prueba("rosa", 0)

    r = entorno.c.get("/control-cajeros?desde=2026-11-14&hasta=2026-11-14", headers=entorno.admin)
    assert r.status_code == 200, r.text
    datos = r.json()
    assert datos["es_prueba"] is True
    assert datos["resumen"]["total_cajeros"] >= 3
    assert datos["resumen"]["cajeros_negativos"] >= 1
    assert datos["resumen"]["cajeros_positivos"] >= 1
    por_usuario = {c["usuario"]: c for c in datos["cajeros"]}
    assert por_usuario["eli"]["estado"] == "deuda"
    assert por_usuario["eli"]["puede_ajustar"] is True
    assert float(por_usuario["eli"]["balance_real"]) == -1835
    assert por_usuario["ana"]["estado"] == "positivo"
    assert por_usuario["ana"]["puede_ajustar"] is False
    assert por_usuario["rosa"]["estado"] == "cuadrado"
    # Negativos primero.
    assert datos["cajeros"][0]["estado"] == "deuda"
    # Balance real = MI CAJA (no se inventa con el filtro de fechas).
    assert float(por_usuario["eli"]["balance_real"]) == float(_mi_caja_terminal(entorno, b["headers"]))


def test_ajuste_completo_parcial_tope_e_idempotencia(entorno, monkeypatch):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    b = entorno.banca(saldo=8000, usuario="eli", clave="prueba123")
    eli = _cajera(entorno, "eli")
    general_antes = entorno.saldo(b["sucursal"]["id"])
    _poner_mi_caja_prueba("eli", -1835)

    # Exceso sobre la deuda.
    exceso = entorno.c.post("/control-cajeros/ajuste", json={
        "usuario_id": eli["id"], "monto": 2000, "motivo": "Exceso",
        "operacion_id": "aj-exceso-1", "balance_visto": -1835,
    }, headers=entorno.admin)
    assert exceso.status_code == 400, exceso.text
    assert float(_mi_caja_terminal(entorno, b["headers"])) == -1835

    # Parcial.
    parcial = entorno.c.post("/control-cajeros/ajuste", json={
        "usuario_id": eli["id"], "monto": 1000, "motivo": "Ajuste parcial banca negativa",
        "operacion_id": "aj-parcial-1", "balance_visto": -1835,
    }, headers=entorno.admin)
    assert parcial.status_code == 201, parcial.text
    cuerpo = parcial.json()
    assert float(cuerpo["balance_anterior"]) == -1835
    assert float(cuerpo["monto"]) == 1000
    assert float(cuerpo["balance_posterior"]) == -835
    assert cuerpo["descuenta_caja_general"] is False
    assert float(_mi_caja_terminal(entorno, b["headers"])) == -835
    assert entorno.saldo(b["sucursal"]["id"]) == general_antes

    # Completo hasta cero.
    completo = entorno.c.post("/control-cajeros/ajuste", json={
        "usuario_id": eli["id"], "monto": 835, "motivo": "Ajuste de banca negativa.",
        "operacion_id": "aj-completo-1", "balance_visto": -835,
    }, headers=entorno.admin)
    assert completo.status_code == 201, completo.text
    assert float(completo.json()["balance_posterior"]) == 0
    assert float(_mi_caja_terminal(entorno, b["headers"])) == 0
    assert entorno.saldo(b["sucursal"]["id"]) == general_antes

    # Idempotencia: mismo operacion_id no duplica.
    otra = entorno.c.post("/control-cajeros/ajuste", json={
        "usuario_id": eli["id"], "monto": 835, "motivo": "Ajuste de banca negativa.",
        "operacion_id": "aj-completo-1", "balance_visto": -835,
    }, headers=entorno.admin)
    assert otra.status_code == 201
    assert otra.json()["id"] == completo.json()["id"]
    assert float(_mi_caja_terminal(entorno, b["headers"])) == 0

    hist = entorno.c.get("/control-cajeros/ajustes", headers=entorno.admin)
    assert hist.status_code == 200
    ops = {h["operacion_id"] for h in hist.json()}
    assert "aj-parcial-1" in ops and "aj-completo-1" in ops
    assert "aj-exceso-1" not in ops


def test_balance_cambiado_cancela_ajuste(entorno, monkeypatch):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    b = entorno.banca(saldo=3000, usuario="eli", clave="prueba123")
    eli = _cajera(entorno, "eli")
    _poner_mi_caja_prueba("eli", -500)
    r = entorno.c.post("/control-cajeros/ajuste", json={
        "usuario_id": eli["id"], "monto": 500, "motivo": "Desfasado",
        "operacion_id": "aj-stale-1", "balance_visto": -1835,
    }, headers=entorno.admin)
    assert r.status_code == 409, r.text
    assert float(_mi_caja_terminal(entorno, b["headers"])) == -500


def test_no_ajustar_positivo_ni_cero(entorno, monkeypatch):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    b = entorno.banca(saldo=3000, usuario="eli", clave="prueba123")
    eli = _cajera(entorno, "eli")
    _poner_mi_caja_prueba("eli", 100)
    r = entorno.c.post("/control-cajeros/ajuste", json={
        "usuario_id": eli["id"], "monto": 50, "motivo": "No aplica",
        "operacion_id": "aj-pos-1", "balance_visto": 100,
    }, headers=entorno.admin)
    assert r.status_code == 400
    _poner_mi_caja_prueba("eli", 0)
    r2 = entorno.c.post("/control-cajeros/ajuste", json={
        "usuario_id": eli["id"], "monto": 1, "motivo": "No aplica",
        "operacion_id": "aj-cero-1", "balance_visto": 0,
    }, headers=entorno.admin)
    assert r2.status_code == 400
    assert float(_mi_caja_terminal(entorno, b["headers"])) == 0


def test_supervisor_y_cajero_no_ajustan(entorno, monkeypatch):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    b = entorno.banca(saldo=3000, usuario="eli", clave="prueba123")
    eli = _cajera(entorno, "eli")
    _poner_mi_caja_prueba("eli", -100)
    supervisor = entorno.c.post("/usuarios", json={
        "nombre": "Supervisor", "usuario": "supcc", "rol": "supervisor",
        "sucursal_id": b["sucursal"]["id"], "clave": "sup123",
    }, headers=entorno.admin)
    assert supervisor.status_code == 201, supervisor.text
    sesion = entorno.c.post("/auth/login", json={"usuario": "supcc", "clave": "sup123"})
    cab = {"Authorization": f"Bearer {sesion.json()['token']}"}
    assert entorno.c.get("/control-cajeros", headers=cab).status_code == 403
    assert entorno.c.post("/control-cajeros/ajuste", json={
        "usuario_id": eli["id"], "monto": 100, "motivo": "No",
        "operacion_id": "aj-sup-1", "balance_visto": -100,
    }, headers=cab).status_code == 403
    assert entorno.c.get("/control-cajeros", headers=b["headers"]).status_code == 401


def test_ajuste_no_rompe_mi_caja_ni_banco_general(entorno, monkeypatch):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    b = entorno.banca(saldo=5764, usuario="eli", clave="prueba123")
    eli = _cajera(entorno, "eli")
    sorteo = entorno.sorteo_id("LOTEDOM")
    entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [sorteo], "numeros": "25", "monto": 10}])
    assert float(_mi_caja_terminal(entorno, b["headers"])) == 10
    _poner_mi_caja_prueba("eli", -50)
    general = entorno.saldo(b["sucursal"]["id"])
    r = entorno.c.post("/control-cajeros/ajuste", json={
        "usuario_id": eli["id"], "monto": 50, "motivo": "Ajuste de banca negativa.",
        "operacion_id": "aj-int-1", "balance_visto": -50,
    }, headers=entorno.admin)
    assert r.status_code == 201, r.text
    assert float(_mi_caja_terminal(entorno, b["headers"])) == 0
    assert entorno.saldo(b["sucursal"]["id"]) == general
    # Indicadores de MI CAJA incluyen ajustes_ciclo y cuadre coherente.
    ind = entorno.c.get("/terminal/sorteos", headers=b["headers"]).json()
    assert "ajustes_ciclo" in ind
    assert float(ind["ajustes_ciclo"]) == 50
    assert float(ind["mi_caja"]) == 0
    db = dbmod.nueva_sesion()
    try:
        u = db.get(Usuario, eli["id"])
        assert float(mi_caja_de(u)) == 0
        assert float(u.saldo_caja or 0) == 0  # caja real intacta en modo prueba
    finally:
        db.close()
