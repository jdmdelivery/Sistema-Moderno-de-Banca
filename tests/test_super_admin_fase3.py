"""FASE 3: JDMCASHNOW Super Admin, paneles y aislamiento diferido (local)."""
import os

from apps.api import db as dbmod
from apps.api.models import Usuario
from apps.api.security import hash_clave


CLAVE_SUPER = "JdmcLocalTest9!"


def _crear_jdmcashnow(entorno, clave=CLAVE_SUPER, reset_clave=True):
    """Crea JDMCASHNOW sin tocar la cuenta admin (Alfredo)."""
    db = dbmod.nueva_sesion()
    try:
        alfredo = db.query(Usuario).filter_by(usuario="admin").one()
        alfredo_rol = alfredo.rol
        alfredo_hash = alfredo.clave_hash
        existente = db.query(Usuario).filter_by(usuario="JDMCASHNOW").first()
        if existente is None:
            db.add(Usuario(
                nombre="JDMCASHNOW",
                usuario="JDMCASHNOW",
                rol="super_admin",
                sucursal_id=None,
                activo=True,
                eliminado=False,
                suspendido=False,
                estado_aprobacion="aprobado",
                clave_hash=hash_clave(clave),
            ))
        else:
            existente.rol = "super_admin"
            existente.sucursal_id = None
            existente.activo = True
            existente.eliminado = False
            existente.suspendido = False
            existente.estado_aprobacion = "aprobado"
            if reset_clave:
                existente.clave_hash = hash_clave(clave)
        db.commit()
        alfredo2 = db.query(Usuario).filter_by(usuario="admin").one()
        assert alfredo2.rol == alfredo_rol
        assert alfredo2.clave_hash == alfredo_hash
    finally:
        db.close()
    login = entorno.c.post("/auth/login", json={"usuario": "JDMCASHNOW", "clave": clave})
    assert login.status_code == 200, login.text
    body = login.json()
    assert body["usuario"]["rol"] == "super_admin"
    assert body["usuario"]["usuario"] == "JDMCASHNOW"
    headers = {"Authorization": f"Bearer {body['token']}"}
    entorno.super_admin = headers
    return headers, body["usuario"]


def test_jdmcashnow_login_y_alfred_intacto(entorno):
    # Antes: compat global
    login_a = entorno.c.post("/auth/login", json={"usuario": "admin", "clave": "admin123"})
    assert login_a.status_code == 200
    assert login_a.json()["usuario"]["compat_global"] is True
    assert login_a.json()["usuario"]["rol"] == "admin"

    super_h, yo = _crear_jdmcashnow(entorno)
    assert yo["compat_global"] is False

    # Alfredo sigue admin con la misma clave
    login_b = entorno.c.post("/auth/login", json={"usuario": "admin", "clave": "admin123"})
    assert login_b.status_code == 200
    assert login_b.json()["usuario"]["rol"] == "admin"
    assert login_b.json()["usuario"]["usuario"] == "admin"

    yo_super = entorno.c.get("/auth/yo", headers=super_h)
    assert yo_super.status_code == 200
    assert yo_super.json()["rol"] == "super_admin"
    assert yo_super.json()["compat_global"] is False


def test_aislamiento_diferido_con_flag(entorno):
    os.environ["COMPAT_GLOBAL_FORZADO"] = "1"
    try:
        super_h, yo = _crear_jdmcashnow(entorno)
        assert yo["compat_global"] is True  # diferido
        # Admin global sigue viendo crear sucursal en compat forzado
        castillo = entorno.sucursal(codigo="5301", nombre="CASTILLO DIF")
        login_a = entorno.c.post("/auth/login", json={"usuario": "admin", "clave": "admin123"})
        h_a = {"Authorization": f"Bearer {login_a.json()['token']}"}
        assert login_a.json()["usuario"]["compat_global"] is True
        lista = entorno.c.get("/sucursales", headers=h_a)
        assert lista.status_code == 200
        assert any(s["id"] == castillo["id"] for s in lista.json())
        # Super igual opera
        cola = entorno.c.get("/super/cajeros-pendientes", headers=super_h)
        assert cola.status_code == 200
    finally:
        os.environ.pop("COMPAT_GLOBAL_FORZADO", None)


def test_panel_super_resumen_y_aprobacion(entorno):
    super_h, _ = _crear_jdmcashnow(entorno)
    castillo = entorno.sucursal(codigo="5401", nombre="BANCA CASTILLO F3")
    peguero = entorno.sucursal(codigo="5402", nombre="BANCA PEGUERO F3")

    adm = entorno.c.post("/usuarios", json={
        "nombre": "Admin Castillo F3", "usuario": "admcastf3", "rol": "admin",
        "sucursal_id": castillo["id"], "clave": "prueba123", "activo": True,
    }, headers=super_h)
    assert adm.status_code == 201, adm.text

    login_adm = entorno.c.post("/auth/login", json={"usuario": "admcastf3", "clave": "prueba123"})
    h_adm = {"Authorization": f"Bearer {login_adm.json()['token']}"}
    assert login_adm.json()["usuario"]["compat_global"] is False

    # Solo su sucursal
    solo = entorno.c.get("/sucursales", headers=h_adm).json()
    assert [s["id"] for s in solo] == [castillo["id"]]
    assert entorno.c.get(f"/sucursales/{peguero['id']}/movimientos", headers=h_adm).status_code == 403

    # No ve panel super
    assert entorno.c.get("/super/resumen", headers=h_adm).status_code == 403
    assert entorno.c.get("/super/cajeros-pendientes", headers=h_adm).status_code == 403

    cajero = entorno.c.post("/usuarios", json={
        "nombre": "Cajero F3", "usuario": "cajf3", "rol": "operador",
        "sucursal_id": castillo["id"], "clave": "prueba123", "activo": True,
    }, headers=h_adm)
    assert cajero.status_code == 201
    assert cajero.json()["estado_aprobacion"] == "pendiente"

    resumen = entorno.c.get("/super/resumen", headers=super_h)
    assert resumen.status_code == 200, resumen.text
    data = resumen.json()
    assert data["cajeros_pendientes_total"] >= 1
    assert data["compat_global"] is False
    fila = next(s for s in data["sucursales"] if s["id"] == castillo["id"])
    assert fila["cajeros_pendientes"] >= 1
    assert any(a["usuario"] == "admcastf3" for a in fila["admins"])

    ok = entorno.c.post(f"/super/cajeros/{cajero.json()['id']}/aprobar", headers=super_h)
    assert ok.status_code == 200
    term = entorno.c.post("/terminal/login", json={"usuario": "cajf3", "clave": "prueba123"})
    assert term.status_code == 200


def test_admin_no_crea_super_ni_toca_jdmcashnow(entorno):
    super_h, _ = _crear_jdmcashnow(entorno)
    suc = entorno.sucursal(codigo="5501", nombre="SUC F3X")
    entorno.c.post("/usuarios", json={
        "nombre": "Admin X F3", "usuario": "admxf3", "rol": "admin",
        "sucursal_id": suc["id"], "clave": "prueba123", "activo": True,
    }, headers=super_h)
    login = entorno.c.post("/auth/login", json={"usuario": "admxf3", "clave": "prueba123"})
    h = {"Authorization": f"Bearer {login.json()['token']}"}
    no = entorno.c.post("/usuarios", json={
        "nombre": "Fake Super", "usuario": "fakesuper", "rol": "super_admin",
        "sucursal_id": None, "clave": "prueba123", "activo": True,
    }, headers=h)
    assert no.status_code == 403
    yo = entorno.c.get("/auth/yo", headers=super_h).json()
    assert entorno.c.post(f"/usuarios/{yo['id']}/bloquear", headers=h).status_code == 403


def test_script_crear_jdmcashnow_sqlite_aislado(tmp_path, monkeypatch):
    """El script de creación corre en BD aislada; la clave solo viene del entorno."""
    import importlib.util
    import sys
    from pathlib import Path

    from apps.api import db as dbmod
    # El fixture autouse `entorno` ya abrió otra SQLite; liberarla antes de reconfigurar.
    if dbmod._engine is not None:
        dbmod._engine.dispose()

    dbfile = tmp_path / "jdmc_aislado.db"
    url = "sqlite:///" + str(dbfile).replace("\\", "/")
    monkeypatch.setenv("JDMCASHNOW_CLAVE", CLAVE_SUPER)
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.delenv("COMPAT_GLOBAL_FORZADO", raising=False)

    from apps.api.db import configurar, init_db, nueva_sesion
    configurar(url)
    init_db()
    db = nueva_sesion()
    try:
        if db.query(Usuario).filter_by(usuario="admin").first() is None:
            db.add(Usuario(
                nombre="Alfredo", usuario="admin", rol="admin",
                activo=True, eliminado=False, estado_aprobacion="aprobado",
                clave_hash=hash_clave("admin123"),
            ))
            db.commit()
        alfred_antes = db.query(Usuario).filter_by(usuario="admin").one()
        rol_antes = alfred_antes.rol
        hash_antes = alfred_antes.clave_hash
    finally:
        db.close()

    script = Path(__file__).resolve().parents[1] / "docs" / "respaldos" / "_crear_jdmcashnow_super_admin.py"
    spec = importlib.util.spec_from_file_location("crear_jdmc", script)
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setattr(sys, "argv", [
        "crear_jdmc", "--database-url", url,
    ])
    spec.loader.exec_module(mod)
    assert mod.main() == 0

    configurar(url)
    db = nueva_sesion()
    try:
        j = db.query(Usuario).filter_by(usuario="JDMCASHNOW").one()
        assert j.rol == "super_admin"
        a = db.query(Usuario).filter_by(usuario="admin").one()
        assert a.rol == rol_antes == "admin"
        assert a.clave_hash == hash_antes
    finally:
        db.close()
    # Liberar SQLite en Windows para el teardown del fixture entorno.
    from apps.api import db as dbmod
    try:
        eng = dbmod.engine()
        eng.dispose()
    except Exception:
        pass
