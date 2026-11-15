"""Bloqueo/desbloqueo de usuarios: acceso en tiempo real sin tocar caja ni tickets."""
from apps.api.comun import MSG_USUARIO_BLOQUEADO


def _crear_cajero(entorno, usuario="caja01", clave="prueba123"):
    b = entorno.banca(saldo=1000, usuario=usuario, clave=clave)
    return b


def test_bloquear_impide_login_terminal_y_conserva_caja(entorno, monkeypatch):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    b = _crear_cajero(entorno, "bloq1", "prueba123")
    sorteo = entorno.sorteo_id("La Primera 12")
    t = entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [sorteo], "numeros": "11", "monto": 10}])
    caja_antes = entorno.c.get("/terminal/sorteos", headers=b["headers"]).json()["mi_caja"]
    usuarios = entorno.c.get("/usuarios", headers=entorno.admin).json()
    cajero = next(u for u in usuarios if u["usuario"] == "bloq1")
    assert cajero["estado"] == "ACTIVO"

    r = entorno.c.post(f"/usuarios/{cajero['id']}/bloquear", headers=entorno.admin)
    assert r.status_code == 200, r.text
    assert r.json()["estado"] == "BLOQUEADO"
    assert r.json()["activo"] is False
    assert float(r.json()["saldo_caja_prueba"]) == float(caja_antes)

    login = entorno.c.post("/terminal/login", json={"usuario": "bloq1", "clave": "prueba123"})
    assert login.status_code == 401
    assert login.json()["detail"] == MSG_USUARIO_BLOQUEADO

    # Sesión previa queda cortada de inmediato (token invalidado).
    sorteos = entorno.c.get("/terminal/sorteos", headers=b["headers"])
    assert sorteos.status_code == 401
    assert "sesión" in sorteos.json()["detail"].lower() or sorteos.json()["detail"] == MSG_USUARIO_BLOQUEADO

    # Caja e historial intactos.
    despues = entorno.c.get("/usuarios", headers=entorno.admin).json()
    cajero2 = next(u for u in despues if u["usuario"] == "bloq1")
    assert cajero2["estado"] == "BLOQUEADO"
    assert float(cajero2["saldo_caja_prueba"]) == float(caja_antes)
    consulta = entorno.c.post(
        "/panel/tickets/consultar",
        json={"id": t["id"], "serial": t["serial"]},
        headers=entorno.admin,
    )
    assert consulta.status_code == 200
    assert consulta.json()["estado"] == "vendido"
    assert entorno.saldo(b["sucursal"]["id"]) == 1000.00


def test_sesion_abierta_queda_cortada_al_bloquear(entorno):
    b = _crear_cajero(entorno, "bloq2", "prueba123")
    usuarios = entorno.c.get("/usuarios", headers=entorno.admin).json()
    cajero = next(u for u in usuarios if u["usuario"] == "bloq2")
    assert entorno.c.get("/terminal/sorteos", headers=b["headers"]).status_code == 200
    assert entorno.c.post(f"/usuarios/{cajero['id']}/bloquear", headers=entorno.admin).status_code == 200
    for ruta, metodo, cuerpo in (
        ("/terminal/sorteos", "get", None),
        ("/terminal/tickets/consultar", "post", {"id": 1, "serial": "x"}),
        ("/terminal/tickets/anular", "post", {"id": 1, "serial": "x", "motivo": "x"}),
        ("/terminal/tickets/pagar", "post", {"id": 1, "serial": "x"}),
    ):
        if metodo == "get":
            r = entorno.c.get(ruta, headers=b["headers"])
        else:
            r = entorno.c.post(ruta, json=cuerpo, headers=b["headers"])
        assert r.status_code == 401, ruta
        detalle = r.json()["detail"].lower()
        assert "sesión" in detalle or "bloqueado" in detalle


def test_desbloquear_permite_login_otra_vez(entorno):
    b = _crear_cajero(entorno, "bloq3", "prueba123")
    usuarios = entorno.c.get("/usuarios", headers=entorno.admin).json()
    cajero = next(u for u in usuarios if u["usuario"] == "bloq3")
    assert entorno.c.post(f"/usuarios/{cajero['id']}/bloquear", headers=entorno.admin).status_code == 200
    assert entorno.c.post(f"/usuarios/{cajero['id']}/desbloquear", headers=entorno.admin).status_code == 200
    login = entorno.c.post("/terminal/login", json={"usuario": "bloq3", "clave": "prueba123"})
    assert login.status_code == 200, login.text
    assert "token" in login.json()
    headers = {"Authorization": f"Bearer {login.json()['token']}"}
    assert entorno.c.get("/terminal/sorteos", headers=headers).status_code == 200


def test_admin_no_puede_bloquearse_ni_dejar_sin_admins(entorno):
    yo = entorno.c.get("/auth/yo", headers=entorno.admin).json()
    r = entorno.c.post(f"/usuarios/{yo['id']}/bloquear", headers=entorno.admin)
    assert r.status_code == 400
    assert "sí mismo" in r.json()["detail"].lower() or "si mismo" in r.json()["detail"].lower()


def test_supervisor_no_bloquea(entorno):
    entorno.c.post(
        "/usuarios",
        json={
            "nombre": "SUPER", "usuario": "super1", "rol": "supervisor",
            "clave": "prueba123", "activo": True,
        },
        headers=entorno.admin,
    )
    b = _crear_cajero(entorno, "bloq4", "prueba123")
    cajero = next(u for u in entorno.c.get("/usuarios", headers=entorno.admin).json() if u["usuario"] == "bloq4")
    login = entorno.c.post("/auth/login", json={"usuario": "super1", "clave": "prueba123"})
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['token']}"}
    r = entorno.c.post(f"/usuarios/{cajero['id']}/bloquear", headers=headers)
    assert r.status_code == 403


def test_bloqueo_queda_en_auditoria(entorno):
    b = _crear_cajero(entorno, "bloq5", "prueba123")
    cajero = next(u for u in entorno.c.get("/usuarios", headers=entorno.admin).json() if u["usuario"] == "bloq5")
    assert entorno.c.post(f"/usuarios/{cajero['id']}/bloquear", headers=entorno.admin).status_code == 200
    filas = entorno.c.get("/auditoria?entidad=usuario&accion=bloqueo", headers=entorno.admin).json()
    assert filas
    assert filas[0]["detalle"]["bloqueado_usuario"] == "bloq5"
    assert entorno.c.post(f"/usuarios/{cajero['id']}/desbloquear", headers=entorno.admin).status_code == 200
    filas2 = entorno.c.get("/auditoria?entidad=usuario&accion=desbloqueo", headers=entorno.admin).json()
    assert filas2
    assert filas2[0]["detalle"]["desbloqueado_usuario"] == "bloq5"


def test_editar_usuario_no_cambia_estado_por_checkbox(entorno):
    b = _crear_cajero(entorno, "bloq6", "prueba123")
    cajero = next(u for u in entorno.c.get("/usuarios", headers=entorno.admin).json() if u["usuario"] == "bloq6")
    r = entorno.c.put(
        f"/usuarios/{cajero['id']}",
        json={
            "nombre": "CAJA 6", "usuario": "bloq6", "rol": "operador",
            "sucursal_id": cajero["sucursal_id"], "activo": False,
        },
        headers=entorno.admin,
    )
    assert r.status_code == 200
    assert r.json()["activo"] is True
    assert r.json()["estado"] == "ACTIVO"


def test_pwa_manifest_y_sw_disponibles(entorno):
    m = entorno.c.get("/manifest.webmanifest")
    assert m.status_code == 200
    assert m.json()["name"] == "Banca Moderna Admin"
    sw = entorno.c.get("/sw.js")
    assert sw.status_code == 200
    assert b"banca-admin-shell" in sw.content
    assert entorno.c.get("/static/icons/icon-192.png").status_code == 200
    assert entorno.c.get("/static/style.css").status_code == 200
    html = entorno.c.get("/").text
    assert 'id="btn-menu"' in html
    assert "manifest.webmanifest" in html
