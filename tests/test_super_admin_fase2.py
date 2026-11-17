"""FASE 2: Super Admin, aprobación de cajeros y aislamiento por sucursal.

Nota FASE 3: el Super Admin real de producción es JDMCASHNOW (cuenta nueva).
Estos tests siguen usando un super de prueba local; no representan promover a Alfredo.
"""
from apps.api import db as dbmod
from apps.api.models import Usuario
from apps.api.permisos import MSG_PENDIENTE_APROBACION
from apps.api.security import hash_clave


def _promover_super(entorno, usuario="admin"):
    """Helper de prueba: crea/usa un super_admin de laboratorio.

    En go-live el Super Admin es JDMCASHNOW (ver test_super_admin_fase3 / script).
    Aquí NO se usa como política de producción sobre Alfredo.
    """
    db = dbmod.nueva_sesion()
    try:
        if usuario == "admin":
            # Preferir cuenta de laboratorio distinta de Alfredo cuando sea posible
            lab = db.query(Usuario).filter_by(usuario="JDMCASHNOW").first()
            if lab is None:
                db.add(Usuario(
                    nombre="JDMCASHNOW",
                    usuario="JDMCASHNOW",
                    rol="super_admin",
                    sucursal_id=None,
                    activo=True,
                    eliminado=False,
                    suspendido=False,
                    estado_aprobacion="aprobado",
                    clave_hash=hash_clave("admin123"),
                ))
            else:
                lab.rol = "super_admin"
                lab.activo = True
                lab.eliminado = False
                lab.estado_aprobacion = "aprobado"
                lab.clave_hash = hash_clave("admin123")
            alfredo = db.query(Usuario).filter_by(usuario="admin").one()
            assert alfredo.rol == "admin"
            db.commit()
            login_user, login_clave = "JDMCASHNOW", "admin123"
        else:
            u = db.query(Usuario).filter_by(usuario=usuario).one()
            u.rol = "super_admin"
            u.sucursal_id = None
            db.commit()
            login_user, login_clave = usuario, "admin123"
    finally:
        db.close()
    login = entorno.c.post("/auth/login", json={"usuario": login_user, "clave": login_clave})
    assert login.status_code == 200, login.text
    assert login.json()["usuario"]["rol"] == "super_admin"
    assert login.json()["usuario"]["compat_global"] is False
    headers = {"Authorization": f"Bearer {login.json()['token']}"}
    entorno.super_admin = headers
    return headers


def test_compat_global_sin_super_admin(entorno):
    login = entorno.c.post("/auth/login", json={"usuario": "admin", "clave": "admin123"})
    assert login.status_code == 200
    assert login.json()["usuario"]["compat_global"] is True
    suc = entorno.sucursal(codigo="9001", nombre="TEMP A")
    # Sin Super Admin, crear cajero queda aprobado (compat).
    r = entorno.c.post("/usuarios", json={
        "nombre": "Cajero Compat", "usuario": "comp1", "rol": "operador",
        "sucursal_id": suc["id"], "clave": "prueba123", "activo": True,
    }, headers=entorno.admin)
    assert r.status_code == 201, r.text
    assert r.json()["estado_aprobacion"] == "aprobado"
    assert r.json()["estado"] == "ACTIVO"
    term = entorno.c.post("/terminal/login", json={"usuario": "comp1", "clave": "prueba123"})
    assert term.status_code == 200, term.text


def test_aprobacion_cajero_requiere_super_admin(entorno):
    super_h = _promover_super(entorno)
    castillo = entorno.sucursal(codigo="1301", nombre="BANCA CASTILLO")
    peguero = entorno.sucursal(codigo="1401", nombre="BANCA PEGUERO")

    admin_cast = entorno.c.post("/usuarios", json={
        "nombre": "Admin Castillo", "usuario": "admcast", "rol": "admin",
        "sucursal_id": castillo["id"], "clave": "prueba123", "activo": True,
    }, headers=super_h)
    assert admin_cast.status_code == 201, admin_cast.text

    login_adm = entorno.c.post("/auth/login", json={"usuario": "admcast", "clave": "prueba123"})
    assert login_adm.status_code == 200
    h_adm = {"Authorization": f"Bearer {login_adm.json()['token']}"}

    # Admin de sucursal crea cajero → PENDIENTE
    cajero = entorno.c.post("/usuarios", json={
        "nombre": "Cajero Nuevo", "usuario": "cajnew", "rol": "operador",
        "sucursal_id": castillo["id"], "clave": "prueba123", "activo": True,
    }, headers=h_adm)
    assert cajero.status_code == 201, cajero.text
    assert cajero.json()["estado_aprobacion"] == "pendiente"
    assert cajero.json()["estado"] == "PENDIENTE"

    # No puede entrar a SUNMI
    term = entorno.c.post("/terminal/login", json={"usuario": "cajnew", "clave": "prueba123"})
    assert term.status_code == 401
    assert MSG_PENDIENTE_APROBACION in term.json()["detail"]

    # Admin NO puede aprobar
    no = entorno.c.post(f"/super/cajeros/{cajero.json()['id']}/aprobar", headers=h_adm)
    assert no.status_code == 403

    # Super ve cola y aprueba
    cola = entorno.c.get("/super/cajeros-pendientes", headers=super_h)
    assert cola.status_code == 200
    assert any(u["usuario"] == "cajnew" for u in cola.json())
    ok = entorno.c.post(f"/super/cajeros/{cajero.json()['id']}/aprobar", headers=super_h)
    assert ok.status_code == 200, ok.text
    assert ok.json()["estado_aprobacion"] == "aprobado"
    assert ok.json()["aprobado_por"] is not None

    term2 = entorno.c.post("/terminal/login", json={"usuario": "cajnew", "clave": "prueba123"})
    assert term2.status_code == 200, term2.text

    # Rechazo de otro cajero
    cajero2 = entorno.c.post("/usuarios", json={
        "nombre": "Cajero Rech", "usuario": "cajrech", "rol": "operador",
        "sucursal_id": castillo["id"], "clave": "prueba123", "activo": True,
    }, headers=h_adm)
    assert cajero2.status_code == 201
    rej = entorno.c.post(
        f"/super/cajeros/{cajero2.json()['id']}/rechazar",
        json={"motivo": "datos incompletos"},
        headers=super_h,
    )
    assert rej.status_code == 200
    assert rej.json()["estado_aprobacion"] == "rechazado"
    term3 = entorno.c.post("/terminal/login", json={"usuario": "cajrech", "clave": "prueba123"})
    assert term3.status_code == 401

    # Aislamiento: admin CASTILLO no ve PEGUERO
    solo = entorno.c.get("/sucursales", headers=h_adm).json()
    assert all(s["id"] == castillo["id"] for s in solo)
    mov = entorno.c.get(f"/sucursales/{peguero['id']}/movimientos", headers=h_adm)
    assert mov.status_code == 403


def test_supervisor_limitado_a_su_sucursal(entorno):
    a = entorno.sucursal(codigo="2101", nombre="SUC A")
    b = entorno.sucursal(codigo="2102", nombre="SUC B")
    entorno.c.post("/usuarios", json={
        "nombre": "Sup A", "usuario": "supa", "rol": "supervisor",
        "sucursal_id": a["id"], "clave": "prueba123", "activo": True,
    }, headers=entorno.admin)
    login = entorno.c.post("/auth/login", json={"usuario": "supa", "clave": "prueba123"})
    assert login.status_code == 200
    h = {"Authorization": f"Bearer {login.json()['token']}"}
    sucs = entorno.c.get("/sucursales", headers=h).json()
    assert [s["id"] for s in sucs] == [a["id"]]
    assert entorno.c.get(f"/sucursales/{b['id']}/movimientos", headers=h).status_code == 403


def test_super_admin_crea_cajero_aprobado_directo(entorno):
    super_h = _promover_super(entorno)
    suc = entorno.sucursal(codigo="3101", nombre="SUC SUPER")
    r = entorno.c.post("/usuarios", json={
        "nombre": "Cajero Directo", "usuario": "cajdir", "rol": "operador",
        "sucursal_id": suc["id"], "clave": "prueba123", "activo": True,
    }, headers=super_h)
    assert r.status_code == 201, r.text
    assert r.json()["estado_aprobacion"] == "aprobado"
    term = entorno.c.post("/terminal/login", json={"usuario": "cajdir", "clave": "prueba123"})
    assert term.status_code == 200


def test_admin_no_puede_tocar_super_admin(entorno):
    super_h = _promover_super(entorno)
    suc = entorno.sucursal(codigo="4101", nombre="SUC X")
    entorno.c.post("/usuarios", json={
        "nombre": "Admin X", "usuario": "admx", "rol": "admin",
        "sucursal_id": suc["id"], "clave": "prueba123", "activo": True,
    }, headers=super_h)
    login = entorno.c.post("/auth/login", json={"usuario": "admx", "clave": "prueba123"})
    h = {"Authorization": f"Bearer {login.json()['token']}"}
    yo = entorno.c.get("/auth/yo", headers=super_h).json()
    assert entorno.c.post(f"/usuarios/{yo['id']}/bloquear", headers=h).status_code == 403
    assert entorno.c.get("/super/cajeros-pendientes", headers=h).status_code == 403
