"""Admin de sucursal no accede a consorcio; Super Admin sí. SUNMI intacto."""
from apps.api import db as dbmod
from apps.api.models import Usuario
from apps.api.security import hash_clave


CLAVE_SUPER = "SuperTest123!"


def _super(entorno):
    """Crea JDMCASHNOW directo en BD (API no permite al admin inicial)."""
    db = dbmod.nueva_sesion()
    try:
        existente = db.query(Usuario).filter_by(usuario="JDMCASHNOW").first()
        if existente is None:
            db.add(Usuario(
                nombre="JDMCASHNOW", usuario="JDMCASHNOW", rol="super_admin",
                sucursal_id=None, activo=True, eliminado=False, suspendido=False,
                estado_aprobacion="aprobado", clave_hash=hash_clave(CLAVE_SUPER),
            ))
        else:
            existente.rol = "super_admin"
            existente.activo = True
            existente.eliminado = False
            existente.suspendido = False
            existente.estado_aprobacion = "aprobado"
            existente.clave_hash = hash_clave(CLAVE_SUPER)
        db.commit()
    finally:
        db.close()
    login = entorno.c.post("/auth/login", json={"usuario": "JDMCASHNOW", "clave": CLAVE_SUPER})
    assert login.status_code == 200, login.text
    entorno.super_admin = {"Authorization": f"Bearer {login.json()['token']}"}
    return entorno.super_admin


def _admin_sucursal(entorno, super_h, usuario="adm_peg", suc_nombre="BANCA PEGUERO MENU"):
    suc = entorno.sucursal(codigo="PEG9", nombre=suc_nombre)
    r = entorno.c.post("/usuarios", json={
        "nombre": "Admin Peg", "usuario": usuario, "rol": "admin",
        "sucursal_id": suc["id"], "clave": "AdminPeg123!", "activo": True,
    }, headers=super_h)
    assert r.status_code in (200, 201), r.text
    login = entorno.c.post("/auth/login", json={"usuario": usuario, "clave": "AdminPeg123!"})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['token']}"}, suc


def test_admin_sucursal_bloqueado_en_consorcio_api(entorno):
    super_h = _super(entorno)
    admin_h, suc = _admin_sucursal(entorno, super_h)
    for path in (
        "/auditoria",
        "/fuente-resultados",
        "/resultados",
        "/terminales",
        "/super/cajeros-pendientes",
        "/super/resumen",
        "/movil/admin?seccion=resultados",
    ):
        assert entorno.c.get(path, headers=admin_h).status_code == 403, path
    assert entorno.c.post("/sorteos", json={
        "nombre": "Sorteo Prohibido", "hora_sorteo": "12:00", "hora_cierre": "11:55",
        "dias_activos": [6], "activo": True, "orden": 1,
    }, headers=admin_h).status_code == 403
    assert entorno.c.post("/terminales", json={
        "sucursal_id": suc["id"], "numero_terminal": 3, "serial_sunmi": "BLOCK-ADM-001",
    }, headers=admin_h).status_code == 403
    # Catálogo de sorteos (solo lectura para filtros) sigue permitido
    assert entorno.c.get("/sorteos", headers=admin_h).status_code == 200


def test_super_admin_conserva_consorcio(entorno):
    super_h = _super(entorno)
    assert entorno.c.get("/auditoria", headers=super_h).status_code == 200
    assert entorno.c.get("/fuente-resultados", headers=super_h).status_code == 200
    assert entorno.c.get("/resultados", headers=super_h).status_code == 200
    assert entorno.c.get("/terminales", headers=super_h).status_code == 200
    assert entorno.c.get("/super/cajeros-pendientes", headers=super_h).status_code == 200
    assert entorno.c.get("/sorteos", headers=super_h).status_code == 200


def test_sunmi_sigue_viendo_sorteos_tras_bloqueo_panel(entorno):
    super_h = _super(entorno)
    admin_h, suc = _admin_sucursal(entorno, super_h, usuario="adm_sun", suc_nombre="BANCA SUN MENU")
    entorno.operador("caj_sun", "prueba123", suc["id"])
    users = entorno.c.get("/usuarios?estado=todos", headers=super_h).json()
    caj = next(u for u in users if u["usuario"] == "caj_sun")
    if caj.get("estado_aprobacion") == "pendiente":
        assert entorno.c.post(f"/super/cajeros/{caj['id']}/aprobar", headers=super_h).status_code == 200
    term = entorno.login_terminal("caj_sun", "prueba123")
    r = entorno.c.get("/terminal/sorteos", headers=term)
    assert r.status_code == 200, r.text
    assert "sorteos" in r.json()
    assert entorno.c.post("/terminales", json={
        "sucursal_id": suc["id"], "numero_terminal": 8, "serial_sunmi": "NO-ADM-TERM",
    }, headers=admin_h).status_code == 403
