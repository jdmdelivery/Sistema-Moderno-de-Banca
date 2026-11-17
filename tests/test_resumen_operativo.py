"""Fase A: Dashboard operativo unificado sin migrar es_prueba ni sumar ledgers."""


def _inicio(entorno, desde=None, hasta=None, headers=None):
    consulta = "/reportes/inicio"
    if desde:
        consulta += f"?desde={desde}&hasta={hasta}"
    return entorno.c.get(consulta, headers=headers or entorno.admin)


def test_operativo_sigue_reales_sin_modo_desarrollo(entorno):
    b = entorno.banca(saldo=50000, codigo="OP01", nombre="BANCA OP REAL", usuario="opreal", clave="prueba123")
    sorteo = entorno.sorteo_id("La Primera 12")
    entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [sorteo], "numeros": "11", "monto": 25}])
    r = _inicio(entorno, "2026-11-14", "2026-11-14").json()
    assert r["modo_desarrollo"] is False
    assert r["ledger_operativo"] == "reales"
    assert r["operativo"] == r["reales"]
    assert r["operativo"]["ventas"] == "25.00"
    assert r["operativo"]["tickets"] == 1
    assert r["prueba"]["ventas"] == "0.00"
    # Clasificación interna intacta
    assert "reales" in r and "prueba" in r


def test_operativo_usa_prueba_en_modo_desarrollo_sin_sumar(entorno, monkeypatch):
    b = entorno.banca(saldo=50000, codigo="OP02", nombre="BANCA OP DEV", usuario="opdev", clave="prueba123")
    sorteo = entorno.sorteo_id("LOTEDOM")
    entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [sorteo], "numeros": "07", "monto": 10}])
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [sorteo], "numeros": "08", "monto": 40}])
    entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [sorteo], "numeros": "09", "monto": 60}])
    r = _inicio(entorno, "2026-11-14", "2026-11-14").json()
    assert r["modo_desarrollo"] is True
    assert r["ledger_operativo"] == "prueba"
    assert r["operativo"] == r["prueba"]
    assert r["reales"]["ventas"] == "10.00"
    assert r["prueba"]["ventas"] == "100.00"
    assert r["prueba"]["tickets"] == 2
    # Nunca suma reales+prueba
    assert r["operativo"]["ventas"] == "100.00"
    assert r["operativo"]["tickets"] == 2
    assert float(r["operativo"]["ventas"]) != float(r["reales"]["ventas"]) + float(r["prueba"]["ventas"])


def test_operativo_respeta_aislamiento_por_sucursal(entorno, monkeypatch):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    from apps.api import db as dbmod
    from apps.api.models import Usuario
    from apps.api.security import hash_clave

    peg = entorno.banca(saldo=20000, codigo="PEGX", nombre="BANCA PEGUERO X", usuario="cajpegx", clave="prueba123")
    cas = entorno.banca(saldo=20000, codigo="CASX", nombre="BANCA CASTILLO X", usuario="cajcasx", clave="prueba123")
    sorteo = entorno.sorteo_id("LOTEDOM")
    entorno.vender_ok(peg["headers"], [{"tipo": "QN", "sorteos": [sorteo], "numeros": "12", "monto": 30}])
    entorno.vender_ok(cas["headers"], [{"tipo": "QN", "sorteos": [sorteo], "numeros": "13", "monto": 70}])

    db = dbmod.nueva_sesion()
    try:
        db.add(Usuario(
            nombre="Admin Peg X", usuario="adm_pegx", rol="admin",
            sucursal_id=peg["sucursal"]["id"], activo=True, eliminado=False,
            suspendido=False, estado_aprobacion="aprobado",
            clave_hash=hash_clave("AdminPegX1!"),
        ))
        db.add(Usuario(
            nombre="Admin Cas X", usuario="adm_casx", rol="admin",
            sucursal_id=cas["sucursal"]["id"], activo=True, eliminado=False,
            suspendido=False, estado_aprobacion="aprobado",
            clave_hash=hash_clave("AdminCasX1!"),
        ))
        # Super para desactivar compat
        if db.query(Usuario).filter_by(usuario="JDMCASHNOW").first() is None:
            db.add(Usuario(
                nombre="JDMCASHNOW", usuario="JDMCASHNOW", rol="super_admin",
                sucursal_id=None, activo=True, eliminado=False, suspendido=False,
                estado_aprobacion="aprobado", clave_hash=hash_clave("SuperTest123!"),
            ))
        db.commit()
    finally:
        db.close()

    login_p = entorno.c.post("/auth/login", json={"usuario": "adm_pegx", "clave": "AdminPegX1!"})
    login_c = entorno.c.post("/auth/login", json={"usuario": "adm_casx", "clave": "AdminCasX1!"})
    assert login_p.status_code == 200 and login_c.status_code == 200
    hp = {"Authorization": f"Bearer {login_p.json()['token']}"}
    hc = {"Authorization": f"Bearer {login_c.json()['token']}"}

    rp = _inicio(entorno, "2026-11-14", "2026-11-14", headers=hp).json()
    rc = _inicio(entorno, "2026-11-14", "2026-11-14", headers=hc).json()
    assert rp["operativo"]["ventas"] == "30.00"
    assert rp["operativo"]["tickets"] == 1
    assert rc["operativo"]["ventas"] == "70.00"
    assert rc["operativo"]["tickets"] == 1
    assert rp["sucursal_id"] == peg["sucursal"]["id"]
    assert rc["sucursal_id"] == cas["sucursal"]["id"]


def test_dashboard_html_sin_division_reales_prueba(entorno):
    html = entorno.c.get("/").text
    js = entorno.c.get("/static/app.js").text
    assert 'id="inicio-operativo"' in html
    assert "inicio-reales" not in html
    assert "inicio-prueba" not in html
    assert "Separados de reales" not in html
    assert "r.operativo" in js or "operativo" in js
