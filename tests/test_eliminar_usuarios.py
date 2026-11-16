"""Eliminación de usuarios: física sin historial, lógica con historial."""
from apps.api.comun import MSG_USUARIO_BLOQUEADO


def test_eliminar_sin_historial_es_fisica(entorno):
    r = entorno.c.post("/usuarios", json={
        "nombre": "Sin Historial", "usuario": "sinhist1", "rol": "operador",
        "sucursal_id": entorno.banca(usuario="tmpv1", clave="prueba123")["sucursal"]["id"],
        "clave": "prueba123", "activo": True,
    }, headers=entorno.admin)
    assert r.status_code == 201, r.text
    uid = r.json()["id"]
    baja = entorno.c.post(f"/usuarios/{uid}/eliminar", json={"confirmar": True, "motivo": "prueba"}, headers=entorno.admin)
    assert baja.status_code == 200, baja.text
    assert baja.json()["modo"] == "fisica"
    lista = entorno.c.get("/usuarios?estado=todos", headers=entorno.admin).json()
    assert all(u["id"] != uid for u in lista)


def test_eliminar_con_historial_es_logica_y_conserva(entorno, monkeypatch):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    b = entorno.banca(saldo=5000, usuario="hist1", clave="prueba123")
    sorteo = entorno.sorteo_id("LOTEDOM")
    t = entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [sorteo], "numeros": "11", "monto": 10}])
    cajero = next(u for u in entorno.c.get("/usuarios", headers=entorno.admin).json() if u["usuario"] == "hist1")
    baja = entorno.c.post(
        f"/usuarios/{cajero['id']}/eliminar",
        json={"confirmar": True, "motivo": "cierre"},
        headers=entorno.admin,
    )
    assert baja.status_code == 200, baja.text
    assert baja.json()["modo"] == "logica"
    assert baja.json()["usuario"]["estado"] == "ELIMINADO"
    # Ticket intacto
    consulta = entorno.c.post(
        "/panel/tickets/consultar",
        json={"id": t["id"], "serial": t["serial"]},
        headers=entorno.admin,
    )
    assert consulta.status_code == 200
    assert consulta.json()["estado"] == "vendido"
    assert float(consulta.json()["total"]) == 10
    # No login
    login = entorno.c.post("/terminal/login", json={"usuario": "hist1", "clave": "prueba123"})
    assert login.status_code == 401
    assert login.json()["detail"] == MSG_USUARIO_BLOQUEADO
    # No desbloquear
    des = entorno.c.post(f"/usuarios/{cajero['id']}/desbloquear", headers=entorno.admin)
    assert des.status_code == 409
    # Aparece en eliminados
    elim = entorno.c.get("/usuarios?estado=eliminados", headers=entorno.admin).json()
    assert any(u["id"] == cajero["id"] and u["estado"] == "ELIMINADO" for u in elim)
    # No en operativos
    ops = entorno.c.get("/usuarios", headers=entorno.admin).json()
    assert all(u["id"] != cajero["id"] for u in ops)


def test_no_eliminar_ultimo_admin_ni_a_si_mismo(entorno):
    yo = entorno.c.get("/auth/yo", headers=entorno.admin).json()
    r = entorno.c.post(f"/usuarios/{yo['id']}/eliminar", json={"confirmar": True}, headers=entorno.admin)
    assert r.status_code == 400


def test_supervisor_no_elimina(entorno):
    entorno.c.post("/usuarios", json={
        "nombre": "SUPER E", "usuario": "supe1", "rol": "supervisor", "clave": "prueba123", "activo": True,
    }, headers=entorno.admin)
    b = entorno.banca(usuario="vict1", clave="prueba123")
    cajero = next(u for u in entorno.c.get("/usuarios", headers=entorno.admin).json() if u["usuario"] == "vict1")
    login = entorno.c.post("/auth/login", json={"usuario": "supe1", "clave": "prueba123"})
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['token']}"}
    r = entorno.c.post(f"/usuarios/{cajero['id']}/eliminar", json={"confirmar": True}, headers=headers)
    assert r.status_code == 403


def test_exige_confirmacion(entorno):
    b = entorno.banca(usuario="conf1", clave="prueba123")
    cajero = next(u for u in entorno.c.get("/usuarios", headers=entorno.admin).json() if u["usuario"] == "conf1")
    r = entorno.c.post(f"/usuarios/{cajero['id']}/eliminar", json={"confirmar": False}, headers=entorno.admin)
    assert r.status_code == 400


def test_eliminar_con_auditoria_es_logica(entorno):
    """Filas en auditoría (FK) bloquean borrado físico; debe quedar ELIMINADO sin 500."""
    from apps.api import db as dbmod
    from apps.api.models import Auditoria

    entorno.banca(usuario="aud1", clave="prueba123")
    cajero = next(u for u in entorno.c.get("/usuarios", headers=entorno.admin).json() if u["usuario"] == "aud1")
    db = dbmod.nueva_sesion()
    try:
        db.add(Auditoria(
            entidad="usuario", entidad_id=str(cajero["id"]), accion="login_test",
            usuario_id=cajero["id"], detalle_json="{}",
        ))
        db.commit()
    finally:
        db.close()
    baja = entorno.c.post(
        f"/usuarios/{cajero['id']}/eliminar",
        json={"confirmar": True, "motivo": "auditoria"},
        headers=entorno.admin,
    )
    assert baja.status_code == 200, baja.text
    assert baja.json()["modo"] == "logica"
    assert baja.json()["usuario"]["estado"] == "ELIMINADO"
