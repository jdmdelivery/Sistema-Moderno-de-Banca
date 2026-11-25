"""VER CONTRASEÑA: cifrado AES-GCM, aislamiento entre bancas y datos intactos.

Solo datos ficticios. No toca PostgreSQL de producción ni Render.
"""
import base64

from apps.api import clave_consulta, db as dbmod, servicios
from apps.api.models import Auditoria, Ticket, Usuario
from apps.api.security import hash_clave, verificar_clave


CLAVE_SUPER = "AuditLocal9!"
CLAVE_ADM = "AdminFicticio1!"
CLAVE_CAJ = "CajeraFicticia1!"


def _super(entorno):
    db = dbmod.nueva_sesion()
    try:
        j = db.query(Usuario).filter_by(usuario="JDMCASHNOW").first()
        if j is None:
            db.add(Usuario(
                nombre="JDMCASHNOW", usuario="JDMCASHNOW", rol="super_admin",
                sucursal_id=None, activo=True, eliminado=False, suspendido=False,
                estado_aprobacion="aprobado", clave_hash=hash_clave(CLAVE_SUPER),
            ))
        else:
            j.rol = "super_admin"
            j.clave_hash = hash_clave(CLAVE_SUPER)
            j.activo = True
            j.eliminado = False
        db.commit()
    finally:
        db.close()
    r = entorno.c.post("/auth/login", json={"usuario": "JDMCASHNOW", "clave": CLAVE_SUPER})
    assert r.status_code == 200, r.text
    h = {"Authorization": f"Bearer {r.json()['token']}"}
    entorno.super_admin = h
    return h


def _dos_bancas(entorno, monkeypatch):
    monkeypatch.delenv("COMPAT_GLOBAL_FORZADO", raising=False)
    super_h = _super(entorno)
    # Códigos distintos a la sucursal sembrada de prueba (también "1301").
    castillo = entorno.sucursal(codigo="C1301", nombre="BANCA CASTILLO")
    peguero = entorno.sucursal(codigo="P1401", nombre="BANCA PEGUERO")
    for user, sid, nombre in (
        ("admcast", castillo["id"], "Admin Castillo"),
        ("admpeg", peguero["id"], "Admin Peguero"),
    ):
        r = entorno.c.post("/usuarios", json={
            "nombre": nombre, "usuario": user, "rol": "admin",
            "sucursal_id": sid, "clave": CLAVE_ADM, "activo": True,
        }, headers=super_h)
        assert r.status_code == 201, r.text
    r = entorno.c.post("/usuarios", json={
        "nombre": "Operador 1301", "usuario": "1301", "rol": "operador",
        "sucursal_id": castillo["id"], "clave": CLAVE_CAJ, "activo": True,
    }, headers=super_h)
    assert r.status_code == 201, r.text
    op1301 = r.json()
    r = entorno.c.post("/usuarios", json={
        "nombre": "Cajera Peguero", "usuario": "cajpeg", "rol": "operador",
        "sucursal_id": peguero["id"], "clave": CLAVE_CAJ, "activo": True,
    }, headers=super_h)
    assert r.status_code == 201, r.text
    op_peg = r.json()
    hc = {
        "Authorization": f"Bearer {entorno.c.post('/auth/login', json={'usuario': 'admcast', 'clave': CLAVE_ADM}).json()['token']}"
    }
    hp = {
        "Authorization": f"Bearer {entorno.c.post('/auth/login', json={'usuario': 'admpeg', 'clave': CLAVE_ADM}).json()['token']}"
    }
    return castillo, peguero, hc, hp, op1301, op_peg, super_h


def test_cifrar_descifrar_aes_gcm_roundtrip():
    blob = clave_consulta.cifrar_clave_consulta("secreto-ficticio")
    assert blob.startswith("v1$gcm$")
    assert "secreto" not in blob
    assert clave_consulta.descifrar_clave_consulta(blob) == "secreto-ficticio"


def test_listado_usuarios_no_expone_secreto(entorno):
    entorno.banca(saldo=100, codigo="L1301", usuario="vend1", clave="1234")
    lista = entorno.c.get("/usuarios", headers=entorno.admin).json()
    for u in lista:
        assert "clave" not in u or u.get("clave") in (None, "")
        assert "clave_hash" not in u
        assert "clave_consulta_cifrada" not in u
        assert "tiene_clave_consulta" in u
    vend = next(u for u in lista if u["usuario"] == "vend1")
    assert vend["tiene_clave_consulta"] is True


def test_ver_clave_ok_tras_crear_y_auditoria_sin_password(entorno, monkeypatch):
    monkeypatch.delenv("COMPAT_GLOBAL_FORZADO", raising=False)
    _, _, hc, _, op1301, _, _ = _dos_bancas(entorno, monkeypatch)
    r = entorno.c.post(
        f"/usuarios/{op1301['id']}/ver-clave",
        json={"clave_admin": CLAVE_ADM},
        headers=hc,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["usuario"] == "1301"
    assert body["clave"] == CLAVE_CAJ
    assert body["id"] == op1301["id"]

    db = dbmod.nueva_sesion()
    try:
        filas = db.query(Auditoria).filter_by(accion="ver_clave").all()
        assert filas
        for f in filas:
            assert CLAVE_CAJ not in (f.detalle_json or "")
            assert CLAVE_ADM not in (f.detalle_json or "")
    finally:
        db.close()


def test_admin_castillo_no_ve_clave_peguero_ni_con_compat(entorno, monkeypatch):
    monkeypatch.setenv("COMPAT_GLOBAL_FORZADO", "1")
    # Con Super Admin + flag, admcast sigue sin poder ver cajera de otra banca.
    _, _, hc, _, _, op_peg, _ = _dos_bancas(entorno, monkeypatch)
    # Re-login admcast (compat activo)
    hc = {
        "Authorization": f"Bearer {entorno.c.post('/auth/login', json={'usuario': 'admcast', 'clave': CLAVE_ADM}).json()['token']}"
    }
    r = entorno.c.post(
        f"/usuarios/{op_peg['id']}/ver-clave",
        json={"clave_admin": CLAVE_ADM},
        headers=hc,
    )
    assert r.status_code == 403, r.text
    assert "otra banca" in r.json()["detail"].lower() or "consultar" in r.json()["detail"].lower()


def test_no_consultar_admin_ni_sin_reauth(entorno, monkeypatch):
    _, _, hc, _, op1301, _, _ = _dos_bancas(entorno, monkeypatch)
    adm = next(u for u in entorno.c.get("/usuarios", headers=hc).json() if u["usuario"] == "admcast")
    r = entorno.c.post(
        f"/usuarios/{adm['id']}/ver-clave",
        json={"clave_admin": CLAVE_ADM},
        headers=hc,
    )
    assert r.status_code == 403
    r = entorno.c.post(
        f"/usuarios/{op1301['id']}/ver-clave",
        json={"clave_admin": "clave-mala"},
        headers=hc,
    )
    assert r.status_code == 401


def test_editar_nombre_y_clave_usuario_1301_conserva_id_y_ventas(entorno, monkeypatch):
    """Cambia nombre/clave del operador '1301' sin alterar tickets ni saldos."""
    monkeypatch.delenv("COMPAT_GLOBAL_FORZADO", raising=False)
    castillo, _, hc, _, op1301, _, super_h = _dos_bancas(entorno, monkeypatch)
    entorno.recargar(castillo["id"], 5000)
    headers = entorno.login_terminal("1301", CLAVE_CAJ)
    sid = entorno.sorteo_id("La Primera 12")
    t1 = entorno.vender_ok(headers, [{"tipo": "QN", "sorteos": [sid], "numeros": "02", "monto": 20}])
    id_interno = op1301["id"]

    db = dbmod.nueva_sesion()
    try:
        u = db.get(Usuario, id_interno)
        hash_antes = u.clave_hash
        saldo_antes = float(u.saldo_caja or 0)
        tickets_antes = db.query(Ticket).filter_by(usuario_id=id_interno).count()
        assert tickets_antes >= 1
    finally:
        db.close()

    saldo_suc_antes = entorno.saldo(castillo["id"])
    r = entorno.c.put(
        f"/usuarios/{id_interno}",
        json={
            "nombre": "Operador 1301 Renombrado",
            "usuario": "1301",
            "rol": "operador",
            "sucursal_id": castillo["id"],
            "clave": "NuevaClaveFicticia2!",
            "activo": True,
        },
        headers=super_h,
    )
    assert r.status_code == 200, r.text
    assert r.json()["id"] == id_interno
    assert r.json()["nombre"] == "Operador 1301 Renombrado"

    db = dbmod.nueva_sesion()
    try:
        u = db.get(Usuario, id_interno)
        assert u.id == id_interno
        assert u.clave_hash != hash_antes
        assert verificar_clave("NuevaClaveFicticia2!", u.clave_hash)
        assert float(u.saldo_caja or 0) == saldo_antes
        tickets_despues = db.query(Ticket).filter_by(usuario_id=id_interno).count()
        assert tickets_despues == tickets_antes
        assert db.get(Ticket, t1["id"]).usuario_id == id_interno
    finally:
        db.close()

    assert entorno.saldo(castillo["id"]) == saldo_suc_antes
    # Sigue entrando con la nueva clave; la vieja no.
    assert entorno.c.post("/terminal/login", json={"usuario": "1301", "clave": CLAVE_CAJ}).status_code == 401
    assert entorno.c.post(
        "/terminal/login", json={"usuario": "1301", "clave": "NuevaClaveFicticia2!"}
    ).status_code == 200

    r = entorno.c.post(
        f"/usuarios/{id_interno}/ver-clave",
        json={"clave_admin": CLAVE_ADM},
        headers=hc,
    )
    assert r.status_code == 200
    assert r.json()["clave"] == "NuevaClaveFicticia2!"


def test_sin_blob_mensaje_no_disponible(entorno, monkeypatch):
    monkeypatch.delenv("COMPAT_GLOBAL_FORZADO", raising=False)
    _, _, hc, _, op1301, _, _ = _dos_bancas(entorno, monkeypatch)
    db = dbmod.nueva_sesion()
    try:
        u = db.get(Usuario, op1301["id"])
        u.clave_consulta_cifrada = None
        db.commit()
    finally:
        db.close()
    r = entorno.c.post(
        f"/usuarios/{op1301['id']}/ver-clave",
        json={"clave_admin": CLAVE_ADM},
        headers=hc,
    )
    assert r.status_code == 409
    assert "aún no disponible" in r.json()["detail"].lower()


def test_fallo_cifrado_en_cambio_invalida_blob_previo(entorno, monkeypatch):
    monkeypatch.delenv("COMPAT_GLOBAL_FORZADO", raising=False)
    castillo, _, hc, _, op1301, _, super_h = _dos_bancas(entorno, monkeypatch)
    assert entorno.c.post(
        f"/usuarios/{op1301['id']}/ver-clave",
        json={"clave_admin": CLAVE_ADM},
        headers=hc,
    ).status_code == 200
    # Quitar clave maestra: el PUT rehashea y debe invalidar el recuperable.
    monkeypatch.delenv("CLAVE_CONSULTA_USUARIOS", raising=False)
    r = entorno.c.put(
        f"/usuarios/{op1301['id']}",
        json={
            "nombre": op1301["nombre"],
            "usuario": "1301",
            "rol": "operador",
            "sucursal_id": castillo["id"],
            "clave": "OtraClaveFicticia3!",
            "activo": True,
        },
        headers=super_h,
    )
    assert r.status_code == 200, r.text
    # Restaurar clave para intentar ver
    monkeypatch.setenv(
        "CLAVE_CONSULTA_USUARIOS",
        base64.b64encode(bytes(range(32))).decode("ascii"),
    )
    r = entorno.c.post(
        f"/usuarios/{op1301['id']}/ver-clave",
        json={"clave_admin": CLAVE_ADM},
        headers=hc,
    )
    assert r.status_code == 409
    # Login con la nueva clave sigue OK (PBKDF2 intacto).
    assert entorno.c.post(
        "/terminal/login", json={"usuario": "1301", "clave": "OtraClaveFicticia3!"}
    ).status_code == 200


def test_login_no_se_rompe_sin_clave_maestra(entorno, monkeypatch):
    monkeypatch.delenv("CLAVE_CONSULTA_USUARIOS", raising=False)
    b = entorno.banca(saldo=50, codigo="9901", usuario="vendx", clave="abcd")
    assert b["headers"]
    r = entorno.c.post("/terminal/login", json={"usuario": "vendx", "clave": "abcd"})
    assert r.status_code == 200
    assert "aviso_consulta_clave" in r.json()


def test_limite_intentos_reauth(entorno, monkeypatch):
    monkeypatch.delenv("COMPAT_GLOBAL_FORZADO", raising=False)
    _, _, hc, _, op1301, _, _ = _dos_bancas(entorno, monkeypatch)
    for _ in range(5):
        r = entorno.c.post(
            f"/usuarios/{op1301['id']}/ver-clave",
            json={"clave_admin": "mala"},
            headers=hc,
        )
        assert r.status_code == 401
    r = entorno.c.post(
        f"/usuarios/{op1301['id']}/ver-clave",
        json={"clave_admin": CLAVE_ADM},
        headers=hc,
    )
    assert r.status_code == 429


def test_captura_login_no_guarda_si_hash_ya_no_coincide(entorno):
    """Simula carrera: UPDATE … WHERE clave_hash=viejo no pisa el blob nuevo."""
    db = dbmod.nueva_sesion()
    try:
        hash_viejo = hash_clave("clave-vieja")
        u = Usuario(
            nombre="Carrera Hash", usuario="carrerahash", rol="operador",
            clave_hash=hash_viejo,
            activo=True, eliminado=False, suspendido=False,
            estado_aprobacion="aprobado",
        )
        db.add(u)
        db.flush()
        assert clave_consulta.guardar_consulta_en_usuario(
            db, u, "clave-vieja", invalidar_si_falla=True
        )
        blob_viejo = u.clave_consulta_cifrada
        # Otro proceso cambia hash + cifra la nueva clave.
        u.clave_hash = hash_clave("clave-nueva")
        db.flush()
        assert clave_consulta.guardar_consulta_en_usuario(
            db, u, "clave-nueva", invalidar_si_falla=True
        )
        blob_nuevo = u.clave_consulta_cifrada
        assert blob_nuevo != blob_viejo
        # Login concurrente aún “pensaba” el hash viejo → 0 filas.
        afectadas = clave_consulta._update_consulta_si_hash(
            db, u.id, blob_viejo, hash_viejo
        )
        assert afectadas == 0
        db.refresh(u)
        assert u.clave_consulta_cifrada == blob_nuevo
        assert clave_consulta.descifrar_clave_consulta(u.clave_consulta_cifrada) == "clave-nueva"
        db.commit()
    finally:
        db.close()


def test_rate_limit_reauth_persiste_entre_sesiones_db(entorno, monkeypatch):
    """Los fallos viven en auditoria: otra 'sesión' DB ve el mismo contador."""
    monkeypatch.delenv("COMPAT_GLOBAL_FORZADO", raising=False)
    _, _, hc, _, op1301, _, _ = _dos_bancas(entorno, monkeypatch)
    for _ in range(5):
        assert entorno.c.post(
            f"/usuarios/{op1301['id']}/ver-clave",
            json={"clave_admin": "mala"},
            headers=hc,
        ).status_code == 401
    # Simula otro worker leyendo la misma BD.
    db = dbmod.nueva_sesion()
    try:
        adm = db.query(Usuario).filter_by(usuario="admcast").one()
        assert clave_consulta.exceso_intentos_ver_clave(
            db, adm.id, servicios.ahora_local()
        )
    finally:
        db.close()
    assert entorno.c.post(
        f"/usuarios/{op1301['id']}/ver-clave",
        json={"clave_admin": CLAVE_ADM},
        headers=hc,
    ).status_code == 429


def test_sql_aditivo_postgres_compatible():
    """La migración usa ADD COLUMN IF NOT EXISTS en PostgreSQL (db._agregar_columna)."""
    from apps.api import db as dbmod
    class _Eng:
        class dialect:
            name = "postgresql"
    assert "IF NOT EXISTS" in dbmod._agregar_columna(_Eng)
    class _EngLite:
        class dialect:
            name = "sqlite"
    assert dbmod._agregar_columna(_EngLite) == "ADD COLUMN"
