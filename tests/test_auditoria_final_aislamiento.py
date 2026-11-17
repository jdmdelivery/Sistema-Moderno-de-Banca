"""Auditoría final: CASTILLO ↔ PEGUERO, JDMCASHNOW, Alfred, sin fugas API."""
from apps.api import db as dbmod
from apps.api.models import Usuario
from apps.api.security import hash_clave


CLAVE = "AuditLocal9!"


def _super(entorno):
    db = dbmod.nueva_sesion()
    try:
        alfredo = db.query(Usuario).filter_by(usuario="admin").one()
        rol, h = alfredo.rol, alfredo.clave_hash
        j = db.query(Usuario).filter_by(usuario="JDMCASHNOW").first()
        if j is None:
            db.add(Usuario(
                nombre="JDMCASHNOW", usuario="JDMCASHNOW", rol="super_admin",
                sucursal_id=None, activo=True, eliminado=False, suspendido=False,
                estado_aprobacion="aprobado", clave_hash=hash_clave(CLAVE),
            ))
        else:
            j.rol = "super_admin"
            j.activo = True
            j.eliminado = False
            j.estado_aprobacion = "aprobado"
            j.clave_hash = hash_clave(CLAVE)
        db.commit()
        alfredo2 = db.query(Usuario).filter_by(usuario="admin").one()
        assert alfredo2.rol == rol == "admin"
        assert alfredo2.clave_hash == h
    finally:
        db.close()
    r = entorno.c.post("/auth/login", json={"usuario": "JDMCASHNOW", "clave": CLAVE})
    assert r.status_code == 200, r.text
    assert r.json()["usuario"]["rol"] == "super_admin"
    h = {"Authorization": f"Bearer {r.json()['token']}"}
    entorno.super_admin = h
    return h


def _admins_castillo_peguero(entorno, super_h):
    castillo = entorno.sucursal(codigo="1301", nombre="BANCA CASTILLO")
    peguero = entorno.sucursal(codigo="1401", nombre="BANCA PEGUERO")
    entorno.c.post("/usuarios", json={
        "nombre": "Admin Castillo", "usuario": "admcast", "rol": "admin",
        "sucursal_id": castillo["id"], "clave": "prueba123", "activo": True,
    }, headers=super_h)
    entorno.c.post("/usuarios", json={
        "nombre": "Admin Peguero", "usuario": "admpeg", "rol": "admin",
        "sucursal_id": peguero["id"], "clave": "prueba123", "activo": True,
    }, headers=super_h)
    # Cajeros aprobados por Super (intactos / operativos)
    for user, sid in (("cajcast", castillo["id"]), ("cajpeg", peguero["id"])):
        r = entorno.c.post("/usuarios", json={
            "nombre": user, "usuario": user, "rol": "operador",
            "sucursal_id": sid, "clave": "prueba123", "activo": True,
        }, headers=super_h)
        assert r.status_code == 201, r.text
        assert r.json()["estado_aprobacion"] == "aprobado"
    hc = {"Authorization": f"Bearer {entorno.c.post('/auth/login', json={'usuario': 'admcast', 'clave': 'prueba123'}).json()['token']}"}
    hp = {"Authorization": f"Bearer {entorno.c.post('/auth/login', json={'usuario': 'admpeg', 'clave': 'prueba123'}).json()['token']}"}
    return castillo, peguero, hc, hp


def test_jdmcashnow_login_alfred_intact_y_sin_admin_global(entorno):
    login_a = entorno.c.post("/auth/login", json={"usuario": "admin", "clave": "admin123"})
    assert login_a.status_code == 200
    assert login_a.json()["usuario"]["rol"] == "admin"
    assert login_a.json()["usuario"]["compat_global"] is True

    super_h = _super(entorno)
    # Alfredo sigue con la misma clave y rol
    login_b = entorno.c.post("/auth/login", json={"usuario": "admin", "clave": "admin123"})
    assert login_b.status_code == 200
    assert login_b.json()["usuario"]["rol"] == "admin"
    # Tras Super Admin, compat off → ningún admin tiene alcance global
    assert login_b.json()["usuario"]["compat_global"] is False
    yo = entorno.c.get("/auth/yo", headers=super_h).json()
    assert yo["usuario"] == "JDMCASHNOW"
    assert yo["compat_global"] is False


def test_castillo_no_ve_peguero_en_rutas_criticas(entorno):
    super_h = _super(entorno)
    castillo, peguero, hc, hp = _admins_castillo_peguero(entorno, super_h)

    # Sucursales
    assert [s["id"] for s in entorno.c.get("/sucursales", headers=hc).json()] == [castillo["id"]]
    assert [s["id"] for s in entorno.c.get("/sucursales", headers=hp).json()] == [peguero["id"]]
    assert entorno.c.get(f"/sucursales/{peguero['id']}/movimientos", headers=hc).status_code == 403
    assert entorno.c.get(f"/sucursales/{castillo['id']}/movimientos", headers=hp).status_code == 403

    # Recarga cruzada
    assert entorno.c.post(
        f"/sucursales/{peguero['id']}/recargar",
        json={"monto": 10, "referencia": "x"}, headers=hc,
    ).status_code == 403

    # Reportes / tickets / caja / fondos / entregas / ganadores / comisiones
    hoy = "2026-11-16"
    assert entorno.c.get(f"/reportes/resumen?desde={hoy}&hasta={hoy}&sucursal_id={peguero['id']}", headers=hc).status_code == 403
    assert entorno.c.get(f"/reportes/ventas?desde={hoy}&hasta={hoy}&sucursal_id={peguero['id']}", headers=hc).status_code == 403
    assert entorno.c.get(f"/panel/tickets?sucursal_id={peguero['id']}", headers=hc).status_code == 403
    assert entorno.c.get(f"/caja/transacciones?sucursal_id={peguero['id']}", headers=hc).status_code == 403
    assert entorno.c.get(f"/cuadres?sucursal_id={peguero['id']}", headers=hc).status_code == 403
    assert entorno.c.get(f"/fondos?sucursal_id={peguero['id']}", headers=hc).status_code == 403
    assert entorno.c.get(f"/entregas?sucursal_id={peguero['id']}", headers=hc).status_code == 403
    assert entorno.c.get(f"/ganadores?sucursal_id={peguero['id']}", headers=hc).status_code == 403
    assert entorno.c.get(f"/comisiones?sucursal_id={peguero['id']}", headers=hc).status_code == 403
    assert entorno.c.get(f"/reportes/pendientes?desde={hoy}&hasta={hoy}&sucursal_id={peguero['id']}", headers=hc).status_code == 403
    assert entorno.c.get(f"/movil/admin?sucursal_id={peguero['id']}", headers=hc).status_code == 403

    # Sin parámetro: no debe listar la otra banca en usuarios
    users_c = entorno.c.get("/usuarios", headers=hc).json()
    assert all(u.get("sucursal_id") in (None, castillo["id"]) or u["rol"] == "admin" for u in users_c)
    assert not any(u.get("usuario") == "cajpeg" for u in users_c)
    # Gestión de terminales (listar/crear): solo Super Admin tras aislamiento
    assert entorno.c.get("/terminales", headers=hc).status_code == 403
    assert entorno.c.post("/terminales", json={
        "sucursal_id": peguero["id"], "numero_terminal": 9, "serial_sunmi": "CROSS-CAST-001",
    }, headers=hc).status_code == 403
    # Super sí ve ambas
    ids = {s["id"] for s in entorno.c.get("/sucursales", headers=super_h).json()}
    assert castillo["id"] in ids and peguero["id"] in ids


def test_cajeros_aprobados_siguen_entrando_terminal(entorno):
    super_h = _super(entorno)
    _admins_castillo_peguero(entorno, super_h)
    for u in ("cajcast", "cajpeg"):
        t = entorno.c.post("/terminal/login", json={"usuario": u, "clave": "prueba123"})
        assert t.status_code == 200, t.text


def test_compat_forzado_mantiene_alcance_hasta_desactivar(entorno, monkeypatch):
    monkeypatch.setenv("COMPAT_GLOBAL_FORZADO", "1")
    super_h = _super(entorno)
    # Con flag, login Super sigue OK pero compat_global True
    login = entorno.c.post("/auth/login", json={"usuario": "JDMCASHNOW", "clave": CLAVE})
    assert login.status_code == 200
    assert login.json()["usuario"]["compat_global"] is True
    castillo = entorno.sucursal(codigo="6301", nombre="CAST TEMP")
    # Admin seed sigue global
    h_admin = entorno.admin
    lista = entorno.c.get("/sucursales", headers=h_admin).json()
    assert any(s["id"] == castillo["id"] for s in lista)
    monkeypatch.delenv("COMPAT_GLOBAL_FORZADO", raising=False)
    # Tras quitar flag (mismo proceso): nuevo login refleja aislamiento
    login2 = entorno.c.post("/auth/login", json={"usuario": "JDMCASHNOW", "clave": CLAVE})
    assert login2.json()["usuario"]["compat_global"] is False
